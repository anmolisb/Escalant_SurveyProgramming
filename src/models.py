"""Pydantic schemas for every stage artifact and every LLM response.

Naming convention: `Stage1*` … `Stage4*` for artifacts written to disk,
`LLM*` for schemas passed to instructor as a response model.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Target headings — the four blocks the pipeline extracts
# ---------------------------------------------------------------------------


class TargetHeading(str, Enum):
    QUESTIONNAIRE = "Questionnaire"
    ROUTING_AND_TERMINATION = "Routing and termination"
    ACCEPTANCE_TEST_SCENARIOS = "Acceptance test scenarios"
    COMPLETION_MESSAGES = "Completion messages"


class FlagStatus(str, Enum):
    NOT_PRESENT = "NOT_PRESENT"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"


# ---------------------------------------------------------------------------
# Stage 1 — ingestion
# ---------------------------------------------------------------------------


class BlockKind(str, Enum):
    PARAGRAPH = "paragraph"
    TABLE = "table"


class Paragraph(BaseModel):
    kind: BlockKind = BlockKind.PARAGRAPH
    order: int
    text: str
    style: str
    is_bold: bool
    heading_level: int | None = None


class Table(BaseModel):
    kind: BlockKind = BlockKind.TABLE
    order: int
    rows: list[list[str]]

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []


class Stage1Document(BaseModel):
    """Document body in true top-to-bottom order, paragraphs and tables interleaved."""

    source: str
    blocks: list[Paragraph | Table]


# ---------------------------------------------------------------------------
# Stage 2 — heading identification
# ---------------------------------------------------------------------------


class ContentBlock(BaseModel):
    """Everything beneath a matched heading, up to the next heading of equal or
    higher level."""

    target: TargetHeading
    heading_text: str
    heading_order: int
    heading_level: int
    matched_by: str = Field(description="direct | llm_shape")
    blocks: list[Paragraph | Table]


class ReviewFlag(BaseModel):
    target_heading: TargetHeading
    status: FlagStatus
    candidate_heading: str | None = None
    confidence: float | None = None
    reasoning: str


class Stage2Blocks(BaseModel):
    source: str
    blocks: list[ContentBlock]
    flags: list[ReviewFlag]


class LLMHeadingCandidate(BaseModel):
    """LLM response for shape-matching an unmatched heading (Stage 2)."""

    is_match: bool = Field(description="True only if the content shape matches the target")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="One sentence citing the observed shape")


# ---------------------------------------------------------------------------
# Stage 3 — literal transcription
# ---------------------------------------------------------------------------


class Stage3Block(BaseModel):
    """Literal transcription of one content block. No renaming, no splitting."""

    target: TargetHeading
    source_kind: str = Field(description="table | prose")
    rows: list[dict[str, str]]


class LLMCompletionMessages(BaseModel):
    """LLM response for transcribing prose completion messages (Stage 3)."""

    rows: list[dict[str, str]] = Field(
        description="One object per message, keys taken verbatim from the source"
    )


# ---------------------------------------------------------------------------
# Stage 4 — deep parse
# ---------------------------------------------------------------------------


class Option(BaseModel):
    code: str | None = None
    label: str


class Question(BaseModel):
    id: str
    wording: str
    type: str
    options: list[Option] = Field(default_factory=list)
    matrix_rows: list[Option] = Field(default_factory=list)
    display_condition: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    min_selections: int | None = None
    exclusive_option: str | None = None
    sum_to: float | None = None
    randomize: bool = False
    optional: bool = False
    dynamic_option_source: str | None = None
    other_attributes: dict[str, str] = Field(default_factory=dict)


class LLMQuestionFields(BaseModel):
    """LLM response for splitting one question's inline attributes (Stage 4)."""

    display_condition: str | None = None
    randomize: bool = False
    optional: bool = False
    dynamic_option_source: str | None = None
    other_attributes: dict[str, str] = Field(default_factory=dict)


class RoutingRule(BaseModel):
    rule: str
    condition_raw: str
    condition_expression: str | None = None
    action: str
    destination: str


class LLMRoutingExpression(BaseModel):
    """LLM response for translating one routing condition (Stage 4)."""

    expression: str | None = Field(
        default=None,
        description="Formal expression using question ids and option codes, or null",
    )
    reasoning: str


class AcceptanceScenario(BaseModel):
    id: str
    purpose: str
    key_inputs: dict = Field(default_factory=dict)
    expected_outcome: dict = Field(default_factory=dict)
    parse_errors: list[str] = Field(default_factory=list)


class CompletionMessage(BaseModel):
    code: str
    message: str


class Stage4Output(BaseModel):
    source: str
    questions: list[Question] = Field(default_factory=list)
    routing: list[RoutingRule] = Field(default_factory=list)
    scenarios: list[AcceptanceScenario] = Field(default_factory=list)
    messages: list[CompletionMessage] = Field(default_factory=list)
    flags: list[ReviewFlag] = Field(default_factory=list)
