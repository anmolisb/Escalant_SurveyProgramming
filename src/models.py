"""Pydantic schemas for every stage artifact and every LLM response.

Naming convention: `Stage1*` … `Stage4*` for artifacts written to disk,
`LLM*` for schemas passed to instructor as a response model.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Target headings — the four blocks the pipeline extracts
# ---------------------------------------------------------------------------


class TargetHeading(str, Enum):
    QUESTIONNAIRE = "Questionnaire"
    ROUTING_AND_TERMINATION = "Routing and termination"
    ACCEPTANCE_TEST_SCENARIOS = "Acceptance test scenarios"
    COMPLETION_MESSAGES = "Completion messages"
    # Sections the pipeline previously ignored. These name concepts, not
    # document conventions: a QRE calling its quota section "Sample & Quotas"
    # still matches, by shape if not by name, and no target has to be present.
    QUOTA_CONTROLS = "Quota controls"
    STUDY_SPECIFICATION = "Study specification"
    PROGRAMMING_AND_QA = "Programming and QA requirements"


class FlagStatus(str, Enum):
    NOT_PRESENT = "NOT_PRESENT"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"


class FlagSeverity(str, Enum):
    """How much a flag should stop things.

    Without this every flag looked equally urgent, so in practice none of them
    were prioritised at all.
    """

    #: Output is incomplete or unusable as it stands. Do not build on it.
    BLOCKING = "BLOCKING"
    #: Worth a look, but the artifact is still usable.
    WARNING = "WARNING"
    #: Recorded for the audit trail; no action expected.
    INFO = "INFO"


class Origin(str, Enum):
    """Where a value came from, per CLAUDE.md §14.

    An inference must never be presented as something the QRE stated.
    """

    #: Read directly out of the document.
    EXTRACTED = "extracted"
    #: Worked out from extracted values by fixed rules, with no judgement.
    DERIVED = "derived"
    #: Produced by semantic reasoning, and therefore not guaranteed correct.
    INFERRED = "inferred"
    #: The source does not say.
    UNKNOWN = "unknown"
    #: The source supports more than one reading.
    AMBIGUOUS = "ambiguous"


#: Bumped when an artifact's shape changes in a way a reader must know about.
#: Artifacts written before headers existed carry no version at all, which is
#: itself the signal that they predate this.
SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Provenance — shared by every stage
# ---------------------------------------------------------------------------


class SourceDocument(BaseModel):
    """The QRE an artifact was produced from.

    The digest is what makes this useful: a filename alone cannot tell you that
    the client sent a revised document, and a stale artifact next to a changed
    QRE is the kind of error nobody notices by eye.
    """

    filename: str
    #: SHA-256 of the file. Null when the document was not readable at the time
    #: of writing, which happens re-running a later stage from saved artifacts.
    sha256: str | None = None
    bytes: int | None = None


class ArtifactEnvelope(BaseModel):
    """Header wrapped around every artifact this pipeline writes.

    Before this, `stage4_questionnaire.json` was a bare array. Two runs of two
    different QREs produced files that were indistinguishable without reading
    the survey content itself, and nothing recorded which document, which code
    version, or when.

    Readers should treat a payload with no `schema_version` as pre-header and
    read it as the content itself.
    """

    schema_version: str = SCHEMA_VERSION
    artifact: str
    stage: int
    survey_id: str
    source_document: SourceDocument
    generated_at: str
    #: Number of records, for list artifacts. Null for a single object.
    item_count: int | None = None
    content: Any


class SourceReference(BaseModel):
    """Where a piece of extracted content came from in the source document.

    Answers "where did this come from in the QRE?" for review, debugging and
    defect traceability. Every field is optional because what is knowable varies
    by source: a table row can name its row index, a sentence transcribed out of
    a prose block cannot.

    Page number is deliberately absent. python-docx reads the document body, not
    its rendered pagination, so a page number here would be a guess.
    """

    document: str | None = None
    section: str | None = None
    heading_text: str | None = None
    #: Stage 1 block index — the position of the paragraph or table in the body.
    block_order: int | None = None
    #: Row within a table, counting data rows only, so 0 is the row under the
    #: header. None for prose, where rows do not map one to one.
    row_index: int | None = None
    source_kind: str | None = None
    #: Verbatim source text, where a single short span can be pointed at.
    text: str | None = None


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


class FlagTarget(BaseModel):
    """The specific thing a flag is about.

    `target_heading` says which section; this says which item inside it. Before
    this existed, a flag about routing rule R18 had to put "R18" into
    `candidate_heading`, a field meant for heading-match candidates, so nothing
    could route a flag to the right item or count flags per rule.
    """

    #: What sort of thing `id` names: question, rule, scenario, message,
    #: statement, option or section. Left open rather than fixed to an enum,
    #: because new kinds appear as the pipeline learns to read more of a QRE.
    kind: str
    id: str


class ReviewFlag(BaseModel):
    target_heading: TargetHeading
    status: FlagStatus
    candidate_heading: str | None = None
    confidence: float | None = None
    reasoning: str
    #: Flags written before severity existed load as WARNING, which is the
    #: neutral reading: they were worth recording but nothing was stopped.
    severity: FlagSeverity = FlagSeverity.WARNING
    target: FlagTarget | None = None


class UnclassifiedSection(BaseModel):
    """A heading whose content matched no target.

    Kept rather than dropped. A section this pipeline does not yet understand is
    still part of the QRE: C02's `Quota controls` and
    `Programming and QA requirements` both describe real survey behaviour, and
    before this existed they were discarded at Stage 2 without a trace. Retaining
    them means a later stage — or a human — can still see what was there.
    """

    heading_text: str
    heading_order: int
    heading_level: int
    blocks: list[Paragraph | Table]
    reason: str = "heading matched no known target"
    requires_review: bool = True


class Stage2Blocks(BaseModel):
    source: str
    blocks: list[ContentBlock]
    flags: list[ReviewFlag]
    #: Sections that matched no target. Defaults to empty so artifacts written
    #: before this field existed still load.
    unclassified: list[UnclassifiedSection] = Field(default_factory=list)


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
    #: Index-aligned with `rows`: `row_sources[i]` describes where `rows[i]` came
    #: from. A parallel list rather than a field on each row, so `rows` keeps its
    #: plain dict shape — Stage 4 reads it by column name, and Stage 5's audit
    #: relies on it staying row-aligned with Stage 4's output.
    #:
    #: Empty on artifacts written before provenance existed, so consumers must
    #: tolerate a list that is absent or shorter than `rows`.
    row_sources: list[SourceReference] = Field(default_factory=list)


class ExtractedStatement(BaseModel):
    """One statement captured verbatim from a prose section.

    Part 1 records what the QRE says; Part 2 decides what it means. A quota line
    such as "QUOTA_REGION: hard quota on D1: North=20%, ..." is kept whole here,
    not broken into cells and percentages, because splitting it is interpretation
    and belongs downstream (CLAUDE.md §19).
    """

    #: Leading identifier where the line supplies one, e.g. QUOTA_REGION.
    code: str | None = None
    #: Leading label where the line reads "Label: value", e.g. Mode.
    label: str | None = None
    #: The statement as written, minus only the code or label prefix.
    text: str
    #: The whole line as it appeared, including any prefix.
    raw_text: str
    source_reference: SourceReference | None = None


class LLMCompletionMessages(BaseModel):
    """LLM response for transcribing prose completion messages (Stage 3)."""

    rows: list[dict[str, str]] = Field(
        description="One object per message, keys taken verbatim from the source"
    )


# ---------------------------------------------------------------------------
# Stage 4 — deep parse
# ---------------------------------------------------------------------------


class Option(BaseModel):
    #: A handle for this option, derived from the question id and the option's
    #: position, e.g. `Q1-O3`. NOT a response code: CLAUDE.md §13 forbids
    #: inventing those, and `code` below stays null where the QRE supplied none.
    #: This exists so later stages and other agents can refer to an option
    #: without matching on its label text, which changes with any rewording.
    #: Null where the question has no id to derive it from.
    option_id: str | None = None
    code: str | None = None
    label: str
    #: The number this option stands for, where the QRE wrote one — read from the
    #: code if it is numeric, otherwise from the label. Derived, not invented:
    #: Q8's labels really are "0" to "10", and Q13's scale really does write
    #: "1 - Very low; 2; 3; 4; 5 - Very high". Null wherever neither is a number,
    #: which is most options: "Auto Brand A" and the age band "60+" have no
    #: numeric value.
    #:
    #: Exists so a scale can be ordered and its endpoints found without parsing
    #: label text downstream. Deliberately separate from the question's
    #: `min_value` / `max_value`, which are extracted from an explicit
    #: `Validate:` instruction and must not be confused with a derived reading.
    numeric_value: float | None = None


class Question(BaseModel):
    id: str
    #: Position in the questionnaire, counting from 1 in document order.
    #:
    #: Derived, not read: the QRE states the order by the sequence it writes the
    #: rows in, and this records that sequence explicitly so it survives being
    #: stored, re-serialised or re-sorted. C02 runs S1-S4, Q1-Q21, D1-D4, then
    #: Q22-Q23 — sorting those ids alphabetically would move the demographics to
    #: the end and quietly change the survey.
    #:
    #: Distinct from `source_reference.row_index`, which restarts at zero for
    #: each table and so cannot order a questionnaire split across two of them.
    seq: int | None = None
    wording: str
    type: str
    options: list[Option] = Field(default_factory=list)
    matrix_rows: list[Option] = Field(default_factory=list)
    display_condition: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    #: Kept as the QRE wrote it. `int | float` rather than plain `float` so a
    #: whole number stays whole: a constant sum written as 100 should not come
    #: back as 100.0, which reads as a precision the source never claimed and
    #: which LimeSurvey would have to round back.
    min_value: int | float | None = None
    max_value: int | float | None = None
    min_selections: int | None = None
    exclusive_option: str | None = None
    sum_to: int | float | None = None
    randomize: bool = False
    optional: bool = False
    dynamic_option_source: str | None = None
    #: Validation settings with no field of their own, kept with their original
    #: JSON type. Previously every value was run through `json.dumps`, so Q9's
    #: scale arrived as a string that merely looked like a list and its
    #: `require_each_row` as the word "true" — both of which had to be parsed a
    #: second time downstream, and one day would have been parsed wrongly.
    other_attributes: dict[str, Any] = Field(default_factory=dict)
    #: Where this came from in the QRE. None on artifacts written before
    #: provenance existed.
    source_reference: SourceReference | None = None


class LLMQuestionFields(BaseModel):
    """LLM response for splitting one question's inline attributes (Stage 4)."""

    display_condition: str | None = None
    randomize: bool = False
    optional: bool = False
    dynamic_option_source: str | None = None
    other_attributes: dict[str, str] = Field(default_factory=dict)


class RoutingRule(BaseModel):
    rule: str
    #: The condition exactly as the QRE wrote it. Trustworthy: on C02 all twenty
    #: match the source document word for word.
    condition_raw: str
    #: A formal reading of `condition_raw`, produced by a language model.
    #:
    #: NOT TRUSTWORTHY, and deliberately kept anyway. On C02 two of the twenty
    #: changed meaning — R5 turned an "only answer" test into an "among the
    #: answers" test, and R19 came out as a condition that can never be true —
    #: one came back empty, and the same operator is written three different
    #: ways across the set. There is no grammar behind this field.
    #:
    #: Do not parse it. Part 2 builds the real condition from `condition_raw`;
    #: this is kept as a hint and as evidence of what the model thought.
    #: See `condition_expression_origin`.
    condition_expression: str | None = None
    #: How `condition_expression` was produced. Always `inferred` when there is
    #: one, because a model wrote it. Null when there is none.
    condition_expression_origin: Origin | None = None
    action: str
    destination: str
    #: Where this came from in the QRE. None on artifacts written before
    #: provenance existed.
    source_reference: SourceReference | None = None


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
    #: Questions the scenario supplies an answer for, in the order written.
    #: Read from the keys of `key_inputs`, so it needs no knowledge of the
    #: questionnaire and makes no claim about whether the set is sufficient.
    input_question_ids: list[str] = Field(default_factory=list)
    #: Every identifier-shaped token in the expected outcome — questions it
    #: expects to see or not see, and the disposition it expects to end at.
    #:
    #: Collected without deciding which is which, because telling a question id
    #: from a disposition code needs the questionnaire and the message list.
    #: Stage 5 resolves these against both; anything that resolves to nothing is
    #: a broken reference in the QRE.
    referenced_ids: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    #: Where this came from in the QRE. None on artifacts written before
    #: provenance existed.
    source_reference: SourceReference | None = None


class CompletionMessage(BaseModel):
    code: str
    message: str
    #: Where this came from in the QRE. None on artifacts written before
    #: provenance existed.
    source_reference: SourceReference | None = None


# ---------------------------------------------------------------------------
# Part 2 — the typed condition
# ---------------------------------------------------------------------------


class ConditionOp(str, Enum):
    """Operators a condition can use.

    A closed set on purpose. The whole problem with Stage 4's
    `condition_expression` is that it is free text, so the same operator comes
    out written three different ways and nothing can check it. Choosing from a
    fixed list makes that impossible by construction.
    """

    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    IN = "in"
    NOT_IN = "not_in"
    #: The answer set is exactly this set — "Q1 == ['None of these']" means None
    #: of these was the ONLY answer, which is not the same as it being among
    #: them. Stage 4's expression lost that distinction on C02's rule R5.
    SET_EQ = "set_eq"
    CONTAINS = "contains"
    CONTAINS_ANY = "contains_any"
    CONTAINS_ALL = "contains_all"
    AND = "and"
    OR = "or"
    NOT = "not"
    #: Whether the question was put to the respondent at all. Needed because a
    #: condition can refer to a question that was skipped.
    ANSWERED = "answered"
    UNANSWERED = "unanswered"


class Aggregate(str, Enum):
    SUM = "sum"
    COUNT = "count"


class Operand(BaseModel):
    """One side of a comparison.

    Deliberately one flat type rather than a union of reference-or-literal. A
    union needs the reader to work out which arm it is holding, and gets that
    wrong quietly; here `question_id` is either set or it is not.
    """

    #: Set when this side names a question's answer.
    question_id: str | None = None
    #: Set when the reference is aggregated, as in "sum(Q18)".
    aggregate: Aggregate | None = None
    #: Set when this side is a literal.
    text: str | None = None
    number: float | None = None
    #: Set when this side is a list, as in "in ['Fully','Partly']".
    values: list[str] | None = None


class Condition(BaseModel):
    """A condition as a tree, not as a string.

    Built from `RoutingRule.condition_raw`, which is verbatim source text, and
    never from `condition_expression`, which a model wrote and which changed
    meaning on two of C02's twenty rules.
    """

    op: ConditionOp
    left: Operand | None = None
    right: Operand | None = None
    #: Children, for and / or / not.
    operands: list["Condition"] = Field(default_factory=list)
    #: The text this was built from, kept so the reading can always be checked
    #: against what the QRE actually said.
    source_text: str = ""
    origin: Origin = Origin.DERIVED
    #: Set when a model proposed this rather than the parser deriving it.
    confidence: float | None = None


class LLMConditionProposal(BaseModel):
    """LLM response: a prose condition rewritten in the parser's grammar.

    The model never returns a condition tree directly. It returns text in a
    grammar the deterministic parser already checks, and the parser is what
    decides whether the proposal is usable. A proposal the parser rejects is
    thrown away, so the model cannot put anything into the specification that
    could not equally have come from the QRE writing it formally.
    """

    expression: str | None = Field(
        default=None,
        description="The condition in the given grammar, or null if it cannot be expressed",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class LLMTextPipe(BaseModel):
    """LLM response: whether a question's wording quotes an earlier answer."""

    is_pipe: bool = Field(
        description="True only if the wording refers to an answer given earlier"
    )
    source_question_id: str | None = Field(
        default=None, description="The question whose answer is quoted"
    )
    target_question_id: str | None = Field(
        default=None, description="The question whose wording does the quoting"
    )
    phrase: str | None = Field(
        default=None, description="The words that do the quoting, copied exactly"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class LLMTextPipes(BaseModel):
    """LLM response: every question whose wording quotes an earlier answer.

    Asked once for the whole questionnaire rather than once per question. A
    per-question call would cost thirty on C02 to find one, and the model needs
    to see the earlier wording anyway to judge what is being referred back to.
    """

    pipes: list[LLMTextPipe] = Field(default_factory=list)


class AuditFinding(BaseModel):
    """One thing Stage 5 noticed while comparing Stage 4 against its inputs.

    Kept separate from `ReviewFlag` on purpose. A flag records trouble a stage
    hit while producing its own output; a finding records a disagreement between
    artifacts that each looked fine on their own. Conflating them would lose
    which of the two you are reading.
    """

    #: Which check produced this, so a finding can be traced to its rule.
    check: str
    severity: FlagSeverity
    finding: str
    target: FlagTarget | None = None
    #: What the check actually saw, quoted rather than summarised.
    evidence: str | None = None
    source_reference: SourceReference | None = None


class SectionScore(BaseModel):
    """How much of one section survived the journey from Stage 3 to Stage 4."""

    target: TargetHeading
    rows_in: int
    objects_out: int
    identified: int = Field(
        description="Objects that came out carrying a non-empty identifier"
    )
    score: float
    threshold: float
    passed: bool


class Stage5Audit(BaseModel):
    """The extraction quality check.

    Audits Stage 4's output against what it was produced from. It does not
    re-extract: a second independent extraction tends to repeat the first one's
    mistakes and agree with a wrong answer rather than catch it.
    """

    source: str
    checks_run: list[str] = Field(default_factory=list)
    sections: list[SectionScore] = Field(default_factory=list)
    findings: list[AuditFinding] = Field(default_factory=list)
    blocking: int = 0
    passed: bool = True


class Stage4Output(BaseModel):
    source: str
    questions: list[Question] = Field(default_factory=list)
    routing: list[RoutingRule] = Field(default_factory=list)
    scenarios: list[AcceptanceScenario] = Field(default_factory=list)
    messages: list[CompletionMessage] = Field(default_factory=list)
    flags: list[ReviewFlag] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Part 2 — the canonical survey specification
# ---------------------------------------------------------------------------


class DestinationKind(str, Enum):
    QUESTION = "question"
    DISPOSITION = "disposition"
    #: Names a position in the flow, not a thing: C02's CURRENT_QUESTION.
    POSITION = "position"
    UNKNOWN = "unknown"


class Destination(BaseModel):
    """Where a rule sends the respondent, with its kind made explicit.

    Part 1's `destination` is one string holding three different sorts of thing
    - a question id, an ending code, and the word CURRENT_QUESTION - so every
    reader had to guess which it was holding. Guessing wrong sends a respondent
    to the wrong place.
    """

    kind: DestinationKind
    id: str
    origin: Origin = Origin.DERIVED


class RuleKind(str, Enum):
    TERMINATE = "terminate"
    SKIP = "skip"
    SHOW = "show"
    REJECT = "reject"
    OTHER = "other"


class CanonicalRule(BaseModel):
    rule_id: str
    kind: RuleKind
    #: The condition as a tree. Null where it could not be read.
    when: Condition | None = None
    #: The source text, kept when `when` is null so nothing is lost.
    when_unread: str | None = None
    destination: Destination
    #: The question after which this rule is checked. Worked out from the
    #: questions the condition names, because the QRE never states it.
    evaluation_point: str | None = None
    evaluation_point_origin: Origin = Origin.INFERRED
    #: Position in the routing table, used as precedence under
    #: `Semantics.rule_precedence`.
    precedence: int = 0
    source_reference: SourceReference | None = None


class GuardAgreement(str, Enum):
    #: Stated in one place only.
    SINGLE_SOURCE = "single_source"
    #: Stated in both the questionnaire and the routing table, identically.
    AGREE = "agree"
    #: Stated in both, differently. Needs a human.
    DISAGREE = "disagree"
    #: Stated, but not readable as a tree.
    UNREAD = "unread"


class Guard(BaseModel):
    """When a question is shown.

    Built by combining both places a QRE states this. Neither is complete on its
    own: in C02 twelve display conditions appear in both the questionnaire and
    the routing table, and Q15's appears only in the questionnaire - the routing
    table omits it, and so would anyone who read only that.
    """

    condition: Condition | None = None
    agreement: GuardAgreement
    #: Where the condition was stated: "questionnaire", or a rule id.
    sources: list[str] = Field(default_factory=list)
    raw_texts: list[str] = Field(default_factory=list)


class RandomizationScope(str, Enum):
    OPTIONS = "options"
    ROWS = "rows"


class Randomization(BaseModel):
    """What is shuffled, and what stays put.

    Part 1 records only that a question randomises. That cannot say whether the
    answer options or a matrix's rows move, nor whether an exclusive option such
    as "None of these" is anchored at the bottom, which is what convention
    expects and what the QRE never states.
    """

    question_id: str
    scope: RandomizationScope
    scope_origin: Origin = Origin.INFERRED
    #: Options that should keep their position. Empty and marked ambiguous when
    #: the QRE does not say.
    anchored: list[str] = Field(default_factory=list)
    anchored_origin: Origin = Origin.UNKNOWN
    #: The QRE asks for the shown order to be recorded for every randomised item.
    capture_display_order: bool = True


class DependencyKind(str, Enum):
    #: The options offered come from an earlier question's answers.
    OPTION_SOURCE = "option_source"
    #: The wording quotes an earlier question's answer.
    TEXT_PIPE = "text_pipe"


class Dependency(BaseModel):
    from_question: str
    to_question: str
    kind: DependencyKind
    detail: str = ""
    origin: Origin = Origin.DERIVED


class Semantics(BaseModel):
    """Decisions about how this survey's language works.

    Written down because they are decisions, not readings. Every later stage
    behaves the same way only if they are stated once, in the file, where a
    reviewer can disagree with them.
    """

    #: What a condition means when it names a question the respondent was never
    #: asked. C02's scenario T3 implies false, by expecting Q7 to Q9 hidden when
    #: Q3 was skipped, but never says so.
    unasked_reference: str = "condition_false"
    unasked_reference_origin: Origin = Origin.INFERRED
    #: Which rule wins when two apply. The routing table is ordered, but nothing
    #: states that the order means anything.
    rule_precedence: str = "document_order_first_match"
    rule_precedence_origin: Origin = Origin.INFERRED
    #: What "==" means against a multi-select answer.
    multi_equality: str = "set_equality"
    multi_equality_origin: Origin = Origin.DERIVED


class CanonicalQuestion(BaseModel):
    question_id: str
    seq: int | None = None
    guard: Guard | None = None


class CanonicalSurvey(BaseModel):
    """What the QRE means, as opposed to what it says.

    Part 1's artifacts remain the record of what was written. This is the
    reading of them, and every value it adds carries an origin saying whether it
    was extracted, derived or inferred.
    """

    source: str
    semantics: Semantics = Field(default_factory=Semantics)
    questions: list[CanonicalQuestion] = Field(default_factory=list)
    rules: list[CanonicalRule] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    randomization: list[Randomization] = Field(default_factory=list)
    #: Things a person needs to decide. Reuses the audit's finding shape so the
    #: two queues can be read together.
    review: list[AuditFinding] = Field(default_factory=list)


Condition.model_rebuild()
