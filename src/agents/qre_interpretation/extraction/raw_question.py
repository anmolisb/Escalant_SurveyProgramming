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

    def by_id(self) -> dict[str, RawQuestion]:
        """Questions keyed by id. Later duplicates overwrite earlier ones.

        Duplicate ids are separately flagged in `review_queue`; use `questions`
        when every row matters.
        """
        return {q.id: q for q in self.questions if q.id}
