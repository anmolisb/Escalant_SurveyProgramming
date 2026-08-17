"""Deterministic validation results for a QREExtractionIR.

Section 45 requires Part 1 to "detect duplicates and malformed objects" and
"produce deterministic validation errors", and Section 7's Pass 7 is blunt about
the consequence: invalid output must fail validation and must not be passed
downstream.

Two severities, and the line between them matters. An ERROR means the IR is
structurally wrong - it violates something the schema promises, and anything
consuming it would be building on a broken foundation. A WARNING means the IR is
well-formed but something about it is suspicious in a way a human should judge.
A missing question identifier is an error; an instruction referring to a
question that was never extracted is a warning, because the fault may lie in the
QRE rather than in the reader, and validation is not entitled to decide which.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from src.common.schemas.qre_extraction import SourceRef


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class IssueCode(str, Enum):
    """Named so that a check can be tracked over time rather than re-described.

    Each maps to a failure mode in Section 39; the mapping is noted in
    validators.py where the check is implemented.
    """

    # Structural - the IR itself is wrong.
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    DUPLICATE_QUESTION_ID = "duplicate_question_id"
    QUESTION_WITHOUT_IDENTITY = "question_without_identity"
    EMPTY_OPTION_LABEL = "empty_option_label"
    EMPTY_INSTRUCTION_TEXT = "empty_instruction_text"
    MALFORMED_DOCUMENT_HASH = "malformed_document_hash"
    PROVENANCE_DOCUMENT_MISMATCH = "provenance_document_mismatch"

    # Suspicious - well-formed, but a human should look.
    NO_QUESTIONS_EXTRACTED = "no_questions_extracted"
    QUESTION_WITHOUT_TEXT = "question_without_text"
    QUESTION_WITHOUT_OPTIONS = "question_without_options"
    DUPLICATE_OPTION_LABEL = "duplicate_option_label"
    PARTIAL_OPTION_CODES = "partial_option_codes"
    UNRESOLVED_QUESTION_REFERENCE = "unresolved_question_reference"
    INSTRUCTION_ORPHANED = "instruction_orphaned"


class ValidationIssue(BaseModel):
    """One finding, located so it can be acted on."""

    code: IssueCode
    severity: Severity
    message: str
    qid: str | None = None
    source: SourceRef | None = None

    def __str__(self) -> str:
        where = f" [{self.qid}]" if self.qid else ""
        return f"{self.severity.value.upper()}{where} {self.code.value}: {self.message}"


class ValidationReport(BaseModel):
    """The outcome of validating one extraction."""

    document: str
    schema_version: str
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        """True when nothing structurally wrong was found.

        Warnings do not make an extraction invalid. They make it worth reading.
        """
        return not self.errors

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for issue in self.issues:
            tally[issue.code.value] = tally.get(issue.code.value, 0) + 1
        return dict(sorted(tally.items()))

    def summary(self) -> str:
        state = "VALID" if self.is_valid else "INVALID"
        return (
            f"{state}  {self.document}  "
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        )
