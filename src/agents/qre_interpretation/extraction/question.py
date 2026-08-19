"""Interpreted question representation — the Step 5 output contract.

The step table specifies the output exactly:

    Out: list of Question objects
         {id, wording, type, options[], validation_rules[], display_condition,
          randomize, dynamic_option_source}

Where Step 4 hands on raw strings, Step 5 hands on typed structures: an options
*list* rather than "Yes; No", a parsed validation *object* rather than
`Validate: {...}`, and a display condition with an operator rather than a
sentence. That is the whole point of the step — Agent 2 can consume these
directly instead of re-parsing prose.

Every object keeps the source text it came from, so an interpretation can always
be checked against what the document actually said (CLAUDE.md §15), and records
how it was arrived at (§14): `extracted` for a value read straight off the page,
`derived` for one obtained deterministically, `inferred` where a model reasoned
about it, `unknown` where nothing could be established.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ingestion.normalized_document import SourceReference

# ---------------------------------------------------------------------------
# Provenance of an interpreted value (CLAUDE.md §14)
# ---------------------------------------------------------------------------

PROV_EXTRACTED = "extracted"
PROV_DERIVED = "derived"
PROV_INFERRED = "inferred"
PROV_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Display-condition operators
# ---------------------------------------------------------------------------
# Typed operators rather than opaque condition strings, per CLAUDE.md §20:
# prefer {"operator": "contains_any", "question_id": "Q1", "values": [...]}
# over "Q1 & [1,2,3,4] != []".

OP_ALWAYS = "always"
OP_EQUALS = "equals"
OP_NOT_EQUALS = "not_equals"
OP_IN = "in"
OP_NOT_IN = "not_in"
OP_CONTAINS_ANY = "contains_any"
OP_CONTAINS_ALL = "contains_all"
OP_GREATER_THAN = "greater_than"
OP_LESS_THAN = "less_than"

#: Operators a condition may legitimately carry. A converter returning anything
#: outside this set is rejected, so the contract cannot widen silently (§17).
KNOWN_OPERATORS = (
    OP_ALWAYS,
    OP_EQUALS,
    OP_NOT_EQUALS,
    OP_IN,
    OP_NOT_IN,
    OP_CONTAINS_ANY,
    OP_CONTAINS_ALL,
    OP_GREATER_THAN,
    OP_LESS_THAN,
)


@dataclass(frozen=True)
class Option:
    """One response option.

    Attributes:
        label: the option text as written, e.g. "Very poor".
        code:  the response code where the source supplies one, e.g. "1" from
               "1 - Very poor" or "1=Yes". None when the source gives a label
               only — never invented, per CLAUDE.md §13.
        raw:   the original unsplit option text, e.g. "1 - Very poor".
    """

    label: str
    code: str | None
    raw: str


@dataclass(frozen=True)
class ValidationRule:
    """One validation rule, with its JSON payload parsed.

    Attributes:
        raw:        the source instruction, e.g. 'Validate: {"min_length": 10}'.
        parameters: the decoded JSON object, e.g. {"min_length": 10}. Empty when
                    the payload could not be decoded — `parse_error` says why,
                    and `raw` still holds the text so nothing is lost.
        parse_error: decoder message when the payload was not valid JSON.
    """

    raw: str
    parameters: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None

    @property
    def is_parsed(self) -> bool:
        return self.parse_error is None and bool(self.parameters)


@dataclass(frozen=True)
class DisplayCondition:
    """When a question is shown, as a machine-evaluable structure.

    Attributes:
        raw:         source text, e.g. "Show if: Q5 == 'Yes'".
        operator:    one of KNOWN_OPERATORS, or None when unresolved.
        question_id: the question the condition tests, e.g. "Q5". None for
                     `always`, or when unresolved.
        values:      the values compared against, as written.
        provenance:  how the operator was arrived at (§14).
        note:        why it is unresolved, when it is.
    """

    raw: str
    operator: str | None = None
    question_id: str | None = None
    values: tuple[str, ...] = ()
    provenance: str = PROV_UNKNOWN
    note: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.operator is not None

    @property
    def is_unconditional(self) -> bool:
        return self.operator == OP_ALWAYS


@dataclass(frozen=True)
class MatrixSpec:
    """Rows and scale of a matrix/grid question.

    Attributes:
        rows:  the statements rated, one per matrix row.
        scale: the shared answer scale applied to every row.
    """

    rows: tuple[Option, ...] = ()
    scale: tuple[Option, ...] = ()


@dataclass(frozen=True)
class Question:
    """One interpreted question — the Step 5 output object.

    The specified fields:
        id, wording, type:      carried through from Step 4 unchanged.
        options:                `options_raw` split into typed Options. Empty for
                                a question with no option list.
        validation_rules:       validation instructions with JSON decoded.
        display_condition:      when the question is shown. None when the source
                                states nothing.
        randomize:              True when a randomization instruction is present.
        dynamic_option_source:  the piping instruction, where one is given.

    Supporting fields:
        matrix:            rows and scale, for matrix/grid questions.
        randomize_notes:   the randomization instruction text, since "Randomize"
                           and "…displayed in randomized order; store display
                           order" are both randomization but say different things.
        source_reference:  provenance back to the source row.
        raw_question_id:   the Step 4 row this came from, for traceability.
    """

    id: str
    wording: str
    type: str
    options: tuple[Option, ...] = ()
    validation_rules: tuple[ValidationRule, ...] = ()
    display_condition: DisplayCondition | None = None
    randomize: bool = False
    dynamic_option_source: str | None = None

    matrix: MatrixSpec | None = None
    randomize_notes: tuple[str, ...] = ()
    source_reference: SourceReference | None = None
    raw_question_id: str = ""

    def to_record(self) -> dict:
        """Flat, serializable form — the shape Agent 2 consumes.

        Mirrors `RawQuestion.to_record`: named keys for everything, with the
        source text alongside each interpreted value so the interpretation stays
        auditable.
        """
        return {
            "id": self.id,
            "wording": self.wording,
            "type": self.type,
            "options": [
                {"label": o.label, "code": o.code, "raw": o.raw} for o in self.options
            ],
            "validation_rules": [
                {
                    "raw": v.raw,
                    "parameters": v.parameters,
                    "parse_error": v.parse_error,
                }
                for v in self.validation_rules
            ],
            "display_condition": (
                {
                    "raw": self.display_condition.raw,
                    "operator": self.display_condition.operator,
                    "question_id": self.display_condition.question_id,
                    "values": list(self.display_condition.values),
                    "provenance": self.display_condition.provenance,
                    "note": self.display_condition.note,
                }
                if self.display_condition is not None
                else None
            ),
            "randomize": self.randomize,
            "randomize_notes": list(self.randomize_notes),
            "dynamic_option_source": self.dynamic_option_source,
            "matrix": (
                {
                    "rows": [
                        {"label": o.label, "code": o.code, "raw": o.raw}
                        for o in self.matrix.rows
                    ],
                    "scale": [
                        {"label": o.label, "code": o.code, "raw": o.raw}
                        for o in self.matrix.scale
                    ],
                }
                if self.matrix is not None
                else None
            ),
            "source_reference": (
                {
                    "document": self.source_reference.document,
                    "order_index": self.source_reference.order_index,
                    "text": self.source_reference.text,
                }
                if self.source_reference is not None
                else None
            ),
        }


@dataclass(frozen=True)
class QuestionLogic:
    """Step 5's return value: the Question list plus what needs review.

    Same shape as Step 2's `SectionedDocument` and Step 4's `QuestionExtraction`
    — the list the step table names, wrapped so the review queue travels with it.
    """

    questions: list[Question]
    review_queue: list[Any] = field(default_factory=list)

    def by_id(self) -> dict[str, Question]:
        return {q.id: q for q in self.questions if q.id}

    @property
    def unresolved_conditions(self) -> list[Question]:
        """Questions whose display condition could not be given an operator."""
        return [
            q
            for q in self.questions
            if q.display_condition is not None and not q.display_condition.is_resolved
        ]

    def to_dict(self) -> dict:
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
        }
