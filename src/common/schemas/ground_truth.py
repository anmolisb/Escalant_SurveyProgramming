"""Hand-coded ground truth for Part 1 extraction.

What a human says a QRE contains, written independently of what the reader
extracted (CLAUDE.md Sections 33, 45, and decision 0003). This is the only
artifact in the project that can say whether the reader is *right* rather than
merely consistent.

Authored as CSV because a person has to write roughly 300 rows and CSV opens in
Excel; validated into these models on load, so the convenient authoring format
costs nothing in schema safety.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

GROUND_TRUTH_VERSION = "0.1.0"

# Separators used inside CSV cells. Chosen so that they do not collide with the
# punctuation QREs use inside option labels and instruction text.
OPTION_SEPARATOR = ";"
INSTRUCTION_SEPARATOR = "||"


class CodingPass(str, Enum):
    """Which pass produced a file, per decision 0003."""

    FIRST = "first"
    SECOND = "second"
    ADJUDICATED = "adjudicated"


class GroundTruthOption(BaseModel):
    """An option a human says the question offers."""

    label: str
    code: str | None = None


class GroundTruthQuestion(BaseModel):
    """A question a human says the QRE asks."""

    qid: str
    text: str | None = None
    question_type: str | None = None
    options: list[GroundTruthOption] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    section: str | None = None
    notes: str | None = None


class GroundTruthDocument(BaseModel):
    """The complete hand-coded expectation for one QRE.

    ``source_sha256`` ties the coding to the exact bytes that were read. If the
    fixture ever changes, the ground truth is stale and must be recoded rather
    than silently reused against a different document.

    ``coded_by`` is required and free text. Section 49's independence rule is
    only auditable if the file says who produced it, and an unattributed ground
    truth cannot be checked for the correlated-authorship problem that decision
    0003 exists to prevent.
    """

    ground_truth_version: str = GROUND_TRUTH_VERSION
    source_document: str
    source_sha256: str
    coded_by: str
    coding_pass: CodingPass = CodingPass.FIRST
    questions: list[GroundTruthQuestion] = Field(default_factory=list)

    @property
    def qids(self) -> set[str]:
        return {q.qid for q in self.questions}

    def question(self, qid: str) -> GroundTruthQuestion | None:
        for question in self.questions:
            if question.qid == qid:
                return question
        return None
