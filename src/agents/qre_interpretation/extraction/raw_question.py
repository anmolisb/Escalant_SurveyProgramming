"""Raw question representation — the Step 4 output contract.

The step table specifies the output exactly:

    Out: list of RawQuestion objects
         {id, wording, type, options_raw, display_validation_raw}

`RawQuestion` carries those five fields under those exact names, plus the
provenance and extraction metadata CLAUDE.md §15 requires on every extracted
element.

Naming note. CLAUDE.md §13's illustrative example uses `qid`, `text`, `raw_type`,
`options` and `raw_instructions` for the same concepts. The step-table names are
used here because they are the specification this step was built to, and because
the `_raw` suffix states the Step 4/5 boundary in the field name itself. §13
presents its example as "observable information such as", not a fixed schema.

The `_raw` fields hold source text verbatim. Nothing here is split, parsed or
interpreted — "Yes; No" stays one string, `Validate: {"min_length": 10}` stays
one string, and a cell holding two instructions on two lines keeps its newline.
Splitting and parsing belong to Step 5 (CLAUDE.md §19).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ingestion.normalized_document import SourceReference
from .instruction_splitter import (
    KIND_DISPLAY,
    KIND_DYNAMIC_OPTIONS,
    KIND_OPTIONALITY,
    KIND_OTHER,
    KIND_RANDOMIZATION,
    KIND_VALIDATION,
    Instruction,
)
from .sectioned_document import ReviewItem


@dataclass(frozen=True)
class ExtraColumn:
    """One table column that matched no known role, preserved verbatim.

    Keyed by column index rather than header text. An earlier version used a
    {header_text: cell_text} dict, which silently dropped content whenever two
    unmapped columns shared a header name — including the common case of two
    blank header cells, where every such column collapsed onto the key "".
    Discarding content that way violates CLAUDE.md §16.

    Attributes:
        column_index: 0-based position in the source row, so the column is
                      locatable even when its header is blank or duplicated.
        header:       header cell text, possibly empty.
        value:        cell text for this question's row, verbatim.
    """

    column_index: int
    header: str
    value: str


@dataclass(frozen=True)
class RawQuestion:
    """One question row, pulled from the questionnaire table as-is.

    The five specified fields:
        id:                     question identifier, e.g. "S1", "Q6".
        wording:                question wording / instruction text.
        type:                   question type as written, e.g. "single", "multi",
                                "text". Not mapped to any platform's type system.
        options_raw:            options / scale cell, verbatim. "Yes; No" is one
                                string; the sample QRE's "—" for no options stays
                                "—" rather than becoming an empty list, since
                                deciding what "—" means is interpretation.
        display_validation_raw: display / validation cell, verbatim, including
                                any embedded newlines separating multiple
                                instructions.

    Supporting fields:
        extra_columns:    table columns that did not map to one of the five
                          roles, preserved rather than dropped (§16, §17).
        instructions:     `display_validation_raw` split into individually
                          classified lines. See the accessors below.
        row_index:        1-based row number within the source table, excluding
                          the header. Locates the question for review.
        source_reference: provenance — document, table block position, and the
                          row's joined source text.

    A field the source did not supply is an empty string, never invented content
    (CLAUDE.md §30). `empty_fields` reports which.
    """

    id: str
    wording: str
    type: str
    options_raw: str
    display_validation_raw: str

    row_index: int
    source_reference: SourceReference
    extra_columns: tuple[ExtraColumn, ...] = ()
    instructions: tuple[Instruction, ...] = ()

    # -- separated instruction views -----------------------------------------
    # `display_validation_raw` frequently packs several unrelated instructions
    # into one cell. Agent 2 needs them apart: a display condition and a
    # validation rule map to different survey constructs. These accessors read
    # from `instructions`, which holds each line classified and in source order.
    #
    # Field names follow the Step 5 output contract in the agent specification:
    # {..., validation_rules[], display_condition, randomize,
    #  dynamic_option_source}. Every value is the source line verbatim — split
    # and labelled, never parsed (CLAUDE.md §19).

    def _of_kind(self, kind: str) -> tuple[str, ...]:
        return tuple(i.text for i in self.instructions if i.kind == kind)

    @property
    def display_condition(self) -> str | None:
        """When the question is shown, e.g. "Show if: Q5 == 'Yes'" or "Always show".

        None when the cell states no display rule. Where a cell carries more
        than one, they are joined with " AND " in source order — but they are
        also individually available via `display_conditions`, because combining
        them is the caller's decision to make, not this accessor's.
        """
        conditions = self._of_kind(KIND_DISPLAY)
        if not conditions:
            return None
        return conditions[0] if len(conditions) == 1 else " AND ".join(conditions)

    @property
    def display_conditions(self) -> tuple[str, ...]:
        """Every display/routing instruction, unjoined, in source order."""
        return self._of_kind(KIND_DISPLAY)

    @property
    def validation_rules(self) -> tuple[str, ...]:
        """Validation instructions, e.g. 'Validate: {"min_length": 10}'.

        Still strings: the JSON payload is not parsed here.
        """
        return self._of_kind(KIND_VALIDATION)

    @property
    def randomize(self) -> tuple[str, ...]:
        """Randomization instructions, e.g. "Randomize"."""
        return self._of_kind(KIND_RANDOMIZATION)

    @property
    def dynamic_option_source(self) -> str | None:
        """Piping instruction, e.g. "Show only touchpoints selected at Q5."."""
        piped = self._of_kind(KIND_DYNAMIC_OPTIONS)
        return piped[0] if piped else None

    @property
    def optionality(self) -> tuple[str, ...]:
        """Mandatory/optional instructions, e.g. "Optional"."""
        return self._of_kind(KIND_OPTIONALITY)

    @property
    def unclassified_instructions(self) -> tuple[str, ...]:
        """Instruction lines matching no known kind. Preserved and reported."""
        return self._of_kind(KIND_OTHER)

    def to_record(self) -> dict:
        """Flat, serializable form — the shape Agent 2 consumes.

        The separated instruction fields above are properties, and
        `dataclasses.asdict` serializes fields only. Without this, a JSON
        consumer would see the `instructions` list and have to re-group it by
        `kind` to find the display condition — pushing the very work this split
        exists to remove back onto the survey builder.

        Emits three groups, in order:
          - the five specified Step 4 fields;
          - the separated instruction fields, as named keys;
          - provenance and audit material, including the untouched
            `display_validation_raw` and the ordered `instructions` list, so any
            separated value can be checked against its source.
        """
        return {
            # the five specified fields
            "id": self.id,
            "wording": self.wording,
            "type": self.type,
            "options_raw": self.options_raw,
            # separated instruction fields, named for direct consumption
            "display_condition": self.display_condition,
            "display_conditions": list(self.display_conditions),
            "validation_rules": list(self.validation_rules),
            "randomize": list(self.randomize),
            "dynamic_option_source": self.dynamic_option_source,
            "optionality": list(self.optionality),
            "unclassified_instructions": list(self.unclassified_instructions),
            # audit trail
            "display_validation_raw": self.display_validation_raw,
            "instructions": [
                {
                    "kind": i.kind,
                    "text": i.text,
                    "line_index": i.line_index,
                }
                for i in self.instructions
            ],
            "row_index": self.row_index,
            "source_reference": {
                "document": self.source_reference.document,
                "order_index": self.source_reference.order_index,
                "text": self.source_reference.text,
            },
            "extra_columns": [
                {
                    "column_index": e.column_index,
                    "header": e.header,
                    "value": e.value,
                }
                for e in self.extra_columns
            ],
            "empty_fields": self.empty_fields,
        }

    @property
    def empty_fields(self) -> list[str]:
        """Which of the five specified fields the source left empty.

        A statement of fact, not a defect list. An empty `options_raw` on a free-
        text question is correct — the field is not applicable there, and
        CLAUDE.md §18 requires applicability and requirement to stay distinct.
        Deciding which fields a given `type` makes applicable would mean
        interpreting the type, which belongs to Step 5. So this reports what is
        empty and leaves the judgement to the step that can make it; only an
        empty `id` or `wording` is treated as a defect worth flagging.
        """
        return [
            name
            for name in ("id", "wording", "type", "options_raw", "display_validation_raw")
            if not getattr(self, name).strip()
        ]


@dataclass(frozen=True)
class QuestionExtraction:
    """Step 4's return value: the RawQuestion list plus what needs review.

    The step table names a list as the output; `.questions` is that list. It is
    wrapped so the review queue travels with it — discarding flagged rows or
    unmapped columns to satisfy a bare-list signature would violate §16, and
    `QREExtractionIR` needs the queue at Step 10 regardless. Same shape as
    Step 2's `SectionedDocument`.

    Attributes:
        questions:        the extracted questions, in table order.
        review_queue:     rows and columns needing human attention.
        column_mapping:   which table header supplied each of the five roles,
                          as {role: header_text}. Records how the table was
                          interpreted, so a mis-mapping is diagnosable.
        unmapped_headers: table headers that matched no role. Their content is
                          still preserved in each question's `extra_columns`.
        source_tables:    order_index of each table block parsed.
    """

    questions: list[RawQuestion]
    review_queue: list[ReviewItem]
    column_mapping: dict[str, str] = field(default_factory=dict)
    unmapped_headers: list[str] = field(default_factory=list)
    source_tables: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serializable form, with each question emitted via `to_record`.

        Used instead of `dataclasses.asdict` so the separated instruction fields
        reach the JSON artifact as named keys rather than only as a list the
        consumer must re-group.
        """
        return {
            "questions": [q.to_record() for q in self.questions],
            "review_queue": [
                {
                    "element": r.element,
                    "reason": r.reason,
                    "detail": r.detail,
                    "source_reference": (
                        {
                            "document": r.source_reference.document,
                            "order_index": r.source_reference.order_index,
                            "text": r.source_reference.text,
                        }
                        if r.source_reference is not None
                        else None
                    ),
                }
                for r in self.review_queue
            ],
            "column_mapping": dict(self.column_mapping),
            "unmapped_headers": list(self.unmapped_headers),
            "source_tables": list(self.source_tables),
        }

    def by_id(self) -> dict[str, RawQuestion]:
        """Questions keyed by id. Later duplicates overwrite earlier ones.

        Duplicate ids are separately flagged in `review_queue`; use `questions`
        when every row matters.
        """
        return {q.id: q for q in self.questions if q.id}
