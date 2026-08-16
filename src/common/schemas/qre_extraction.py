"""QREExtractionIR - the Part 1 output contract.

What the QRE Reader produces and the Part 2 Semantic Interpreter consumes
(CLAUDE.md Section 12). This is a cross-agent contract, which is why it lives in
``common/schemas`` rather than inside Agent 1 (Sections 26 and 41).

NOT YET FROZEN. ``SCHEMA_VERSION`` is 0.1.0 and stays unfrozen through Stages 5
and 6, so that deterministic validation and the first evaluation against ground
truth can still reshape it. Once frozen, Section 18 applies: no silent changes,
breaking changes only through a new version.

This layer records what a QRE SAYS. It does not record what a QRE MEANS.
An instruction is stored as the text that was written, with its location and a
shallow kind - never as a parsed condition. "Show if: Q5 contains any
touchpoint" is preserved verbatim; deciding that it denotes ``contains_any`` is
Part 2's work (Sections 7.1 and 19).

Note on ``SourceRef``: it deliberately duplicates the shape of ingestion's
``SourceLocation`` rather than importing it. That type is Agent 1 internal and
free to change; this one is a contract. Importing it would make every ingestion
tweak a contract change, which is the coupling Section 26 exists to prevent.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "0.1.0"


class Origin(str, Enum):
    """How a value came to be known (CLAUDE.md Section 14).

    Part 1 produces ``EXTRACTED`` and ``DERIVED`` only. ``INFERRED`` belongs to
    Part 2. Presenting an inference as something the QRE stated is the failure
    this enum exists to make impossible.
    """

    EXTRACTED = "extracted"
    DERIVED = "derived"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class InstructionKind(str, Enum):
    """Shallow classification of an instruction, from cue words only."""

    ROUTING = "routing"
    DISPLAY = "display"
    VALIDATION = "validation"
    QUOTA = "quota"
    RANDOMIZATION = "randomization"
    PIPING = "piping"
    DISPOSITION = "disposition"
    PROGRAMMING_NOTE = "programming_note"
    UNCLASSIFIED = "unclassified"


class ReviewReason(str, Enum):
    """Why an item needs a human."""

    UNRECOGNIZED_TABLE = "unrecognized_table"
    AMBIGUOUS_INSTRUCTION_KIND = "ambiguous_instruction_kind"
    MISSING_QUESTION_ID = "missing_question_id"
    UNMAPPED_COLUMN = "unmapped_column"
    UNPARSED_SIGNIFICANT_CONTENT = "unparsed_significant_content"
    NO_QUESTIONS_FOUND = "no_questions_found"


class SourceRef(BaseModel):
    """Where a piece of content came from in the source QRE (Section 15)."""

    document: str
    order_index: int
    page: int | None = None
    table_index: int | None = None
    row: int | None = None
    column: int | None = None


class Evidence(BaseModel):
    """One reason the reader believes what it believes.

    Section 32 requires confidence grounded in something measurable rather than
    a self-reported number. Recording the signal and its value is what makes
    calibration possible later, and what lets a reviewer judge whether the
    reader's reasoning was sound rather than only whether its answer looks
    plausible.
    """

    signal: str
    value: str
    detail: str | None = None


class Confidence(BaseModel):
    """A score with its supporting evidence.

    UNCALIBRATED. The score is an internal, deterministic measure of match
    strength; it is not a probability of correctness. Section 32 requires
    calibration against ground truth before any threshold here means anything.
    """

    score: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)


class ReviewItem(BaseModel):
    """Something a human should look at before this extraction is trusted."""

    reason: ReviewReason
    message: str
    source: SourceRef | None = None
    related_qid: str | None = None
    requires_review: bool = True


class ExtractedOption(BaseModel):
    """A response option as written.

    ``code`` is None when the QRE gave a label without a code. Section 13 is
    explicit that a missing code must stay missing - a fabricated code is worse
    than an absent one, because it looks like data.
    """

    label: str
    code: str | None = None
    origin: Origin = Origin.EXTRACTED
    source: SourceRef


class ExtractedInstruction(BaseModel):
    """A programming instruction, preserved as written.

    ``raw_text`` is byte-identical to the source. Tidying whitespace or
    rephrasing is already interpretation, and would destroy the evidence Part 2
    and any reviewer need (Section 19).
    """

    raw_text: str
    kind: InstructionKind = InstructionKind.UNCLASSIFIED
    qid: str | None = None
    origin: Origin = Origin.EXTRACTED
    confidence: Confidence
    source: SourceRef


class ExtractedQuestion(BaseModel):
    """A question as observed, with no semantics attached."""

    qid: str | None = None
    text: str | None = None
    raw_type: str | None = None
    options: list[ExtractedOption] = Field(default_factory=list)
    raw_options_text: str | None = None
    raw_instructions: list[str] = Field(default_factory=list)
    section: str | None = None
    origin: Origin = Origin.EXTRACTED
    confidence: Confidence
    source: SourceRef


class Section(BaseModel):
    """A document section, as far as the document itself declares one."""

    title: str
    level: int | None = None
    source: SourceRef


class UnparsedContent(BaseModel):
    """Content the reader could not classify, retained rather than dropped.

    Section 16: unknown content is preferable to silent loss. ``requires_review``
    is set only for content showing a signal of significance - flagging every
    leftover line would produce a queue nobody reads.
    """

    text: str
    reason: str
    source: SourceRef
    requires_review: bool = False


class SourceDocument(BaseModel):
    """Identity of the ingested document this extraction came from."""

    filename: str
    sha256: str
    format: str
    page_count: int | None = None
    ingestion_adapter: str
    ingestion_adapter_version: str


class ExtractionRun(BaseModel):
    """What produced this IR, for reproducibility (Section 50).

    No timestamp: it would make two runs over identical input differ, and
    byte-identical output is exactly what reproducibility testing checks. When a
    run happened belongs in the run ledger, not in the artifact.
    """

    reader: str
    reader_version: str
    patterns_fingerprint: str


class QREExtractionIR(BaseModel):
    """The complete Part 1 extraction for one QRE document.

    Instructions are held in one list carrying a ``kind`` rather than in
    separate ``routing_blocks`` / ``validation_blocks`` / ... arrays as Section
    12 sketches. Two reasons, both from the corpus: instructions frequently sit
    together in a single cell, and a cue like "terminate" legitimately reads as
    both routing and disposition. Separate arrays would force an exclusive
    choice at the moment of lowest information; one list with a kind and a
    confidence records the ambiguity honestly and sends it to review. The named
    views below preserve the documented access pattern.
    """

    schema_version: str = SCHEMA_VERSION
    document: SourceDocument
    extraction: ExtractionRun

    sections: list[Section] = Field(default_factory=list)
    questions: list[ExtractedQuestion] = Field(default_factory=list)
    instructions: list[ExtractedInstruction] = Field(default_factory=list)
    unparsed_content: list[UnparsedContent] = Field(default_factory=list)
    review_queue: list[ReviewItem] = Field(default_factory=list)

    def _of_kind(self, kind: InstructionKind) -> list[ExtractedInstruction]:
        return [i for i in self.instructions if i.kind is kind]

    @property
    def routing_blocks(self) -> list[ExtractedInstruction]:
        return self._of_kind(InstructionKind.ROUTING)

    @property
    def display_blocks(self) -> list[ExtractedInstruction]:
        return self._of_kind(InstructionKind.DISPLAY)

    @property
    def validation_blocks(self) -> list[ExtractedInstruction]:
        return self._of_kind(InstructionKind.VALIDATION)

    @property
    def quota_blocks(self) -> list[ExtractedInstruction]:
        return self._of_kind(InstructionKind.QUOTA)

    @property
    def randomization_blocks(self) -> list[ExtractedInstruction]:
        return self._of_kind(InstructionKind.RANDOMIZATION)

    @property
    def piping_blocks(self) -> list[ExtractedInstruction]:
        return self._of_kind(InstructionKind.PIPING)

    @property
    def disposition_blocks(self) -> list[ExtractedInstruction]:
        return self._of_kind(InstructionKind.DISPOSITION)

    @property
    def programming_notes(self) -> list[ExtractedInstruction]:
        return self._of_kind(InstructionKind.PROGRAMMING_NOTE)

    @property
    def needs_review(self) -> bool:
        return bool(self.review_queue)
