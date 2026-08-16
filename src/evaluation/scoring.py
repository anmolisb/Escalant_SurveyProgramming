"""Scoring extraction against hand-coded ground truth.

Implements the Part 1 metrics in CLAUDE.md Section 38: question precision and
recall, option accuracy, type accuracy and instruction capture.

Two principles shape what this reports.

Errors are named, not just counted. A score of 0.87 tells nobody what to fix.
Every mismatch is returned with its question id and both values, because the
purpose of measuring is to find the failure, and an aggregate hides exactly the
detail needed to act on it.

Matching is exact unless the QRE itself is ambiguous. Comparison normalizes only
whitespace and case, never wording. A scorer that accepts "close enough" answers
will report success on an extraction that quietly changed what a question asked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.common.schemas.ground_truth import GroundTruthDocument
from src.common.schemas.qre_extraction import QREExtractionIR

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Whitespace and case only. Wording is never altered."""
    return _WHITESPACE.sub(" ", (text or "").strip()).lower()


@dataclass
class Mismatch:
    """One concrete disagreement, stated so it can be acted on."""

    qid: str
    field: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return f"{self.qid}.{self.field}: expected {self.expected!r}, got {self.actual!r}"


@dataclass
class DocumentScore:
    """Metrics for one document, with the underlying errors retained."""

    document: str
    format: str

    expected_questions: int = 0
    extracted_questions: int = 0
    matched_questions: int = 0

    missed_qids: list[str] = field(default_factory=list)
    spurious_qids: list[str] = field(default_factory=list)
    mismatches: list[Mismatch] = field(default_factory=list)

    type_checked: int = 0
    type_correct: int = 0
    options_checked: int = 0
    options_correct: int = 0
    instructions_expected: int = 0
    instructions_captured: int = 0

    @property
    def recall(self) -> float:
        """Share of real questions found. Misses are the dangerous error."""
        if not self.expected_questions:
            return 0.0
        return self.matched_questions / self.expected_questions

    @property
    def precision(self) -> float:
        """Share of extracted questions that are real. Low means invention."""
        if not self.extracted_questions:
            return 0.0
        return self.matched_questions / self.extracted_questions

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def type_accuracy(self) -> float:
        return self.type_correct / self.type_checked if self.type_checked else 0.0

    @property
    def option_accuracy(self) -> float:
        return (
            self.options_correct / self.options_checked if self.options_checked else 0.0
        )

    @property
    def instruction_capture(self) -> float:
        if not self.instructions_expected:
            return 0.0
        return self.instructions_captured / self.instructions_expected


def score_document(
    ir: QREExtractionIR, truth: GroundTruthDocument
) -> DocumentScore:
    """Compare one extraction against its ground truth."""
    if ir.document.sha256 != truth.source_sha256:
        raise ValueError(
            f"Ground truth for {truth.source_document} was coded against a "
            "different version of the document. Recode it rather than scoring "
            "against bytes nobody read."
        )

    score = DocumentScore(document=ir.document.filename, format=ir.document.format)

    extracted = {q.qid: q for q in ir.questions if q.qid}
    expected = {q.qid: q for q in truth.questions}

    score.expected_questions = len(expected)
    score.extracted_questions = len(extracted)
    score.missed_qids = sorted(set(expected) - set(extracted))
    score.spurious_qids = sorted(set(extracted) - set(expected))

    for qid in sorted(set(expected) & set(extracted)):
        score.matched_questions += 1
        want, got = expected[qid], extracted[qid]

        if want.text:
            # Ground truth holds the question's wording; the reader may have
            # captured it with an identifier prefix, which is not an error.
            if normalize(want.text) not in normalize(got.text):
                score.mismatches.append(
                    Mismatch(qid, "text", want.text, got.text or "")
                )

        if want.question_type:
            score.type_checked += 1
            if normalize(want.question_type) == normalize(got.raw_type):
                score.type_correct += 1
            else:
                score.mismatches.append(
                    Mismatch(qid, "type", want.question_type, got.raw_type or "")
                )

        if want.options:
            score.options_checked += 1
            want_labels = [normalize(o.label) for o in want.options]
            got_labels = [normalize(o.label) for o in got.options]
            if want_labels == got_labels:
                score.options_correct += 1
            else:
                score.mismatches.append(
                    Mismatch(
                        qid,
                        "options",
                        "; ".join(o.label for o in want.options),
                        "; ".join(o.label for o in got.options),
                    )
                )

            for want_option, got_option in zip(want.options, got.options):
                if want_option.code and want_option.code != got_option.code:
                    score.mismatches.append(
                        Mismatch(
                            qid,
                            f"code[{want_option.label}]",
                            want_option.code,
                            got_option.code or "",
                        )
                    )

        for instruction in want.instructions:
            score.instructions_expected += 1
            haystack = " ".join(normalize(r) for r in got.raw_instructions)
            if normalize(instruction) in haystack:
                score.instructions_captured += 1
            else:
                score.mismatches.append(
                    Mismatch(qid, "instruction", instruction, "not captured")
                )

    return score


@dataclass
class CorpusScore:
    """Aggregate across documents, reported per format as well as overall.

    Formats are kept apart deliberately. DOCX questions come from a structured
    table and PDF questions from prose, so they fail differently - and a strong
    DOCX average is more than capable of hiding a weak PDF one.
    """

    documents: list[DocumentScore] = field(default_factory=list)

    def by_format(self, fmt: str) -> list[DocumentScore]:
        return [d for d in self.documents if d.format == fmt]

    @staticmethod
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def recall(self, fmt: str | None = None) -> float:
        docs = self.by_format(fmt) if fmt else self.documents
        return self._mean([d.recall for d in docs])

    def precision(self, fmt: str | None = None) -> float:
        docs = self.by_format(fmt) if fmt else self.documents
        return self._mean([d.precision for d in docs])

    @property
    def total_mismatches(self) -> int:
        return sum(len(d.mismatches) for d in self.documents)

    def report(self) -> str:
        """A plain-text summary, errors first."""
        lines = [
            f"{'document':46} {'recall':>7} {'prec':>7} {'type':>7} {'opts':>7} {'instr':>7}",
        ]
        for d in sorted(self.documents, key=lambda x: x.document):
            lines.append(
                f"{d.document:46} {d.recall:7.2f} {d.precision:7.2f} "
                f"{d.type_accuracy:7.2f} {d.option_accuracy:7.2f} "
                f"{d.instruction_capture:7.2f}"
            )

        lines.append("")
        for fmt in sorted({d.format for d in self.documents}):
            lines.append(
                f"{fmt:>6}: recall {self.recall(fmt):.2f}  "
                f"precision {self.precision(fmt):.2f}  "
                f"({len(self.by_format(fmt))} documents)"
            )
        lines.append(
            f"overall: recall {self.recall():.2f}  precision {self.precision():.2f}"
        )

        missed = [(d.document, d.missed_qids) for d in self.documents if d.missed_qids]
        spurious = [
            (d.document, d.spurious_qids) for d in self.documents if d.spurious_qids
        ]
        if missed:
            lines.append("\nMISSED questions (extraction failed to find):")
            for document, qids in missed:
                lines.append(f"  {document}: {', '.join(qids)}")
        if spurious:
            lines.append("\nSPURIOUS questions (extraction invented):")
            for document, qids in spurious:
                lines.append(f"  {document}: {', '.join(qids)}")
        if self.total_mismatches:
            lines.append(f"\n{self.total_mismatches} field mismatches:")
            for d in self.documents:
                for mismatch in d.mismatches[:5]:
                    lines.append(f"  {d.document}: {mismatch}")
                if len(d.mismatches) > 5:
                    lines.append(f"  {d.document}: ... {len(d.mismatches) - 5} more")

        return "\n".join(lines)
