"""Deterministic validation of a QREExtractionIR.

Every check here is code, not judgement. Section 29 puts duplicate detection,
reference validation and consistency checks squarely on the deterministic side,
and Section 43's fifth principle is that code decides - a model may explain a
defect but must never be the authority on whether one exists.

The checks map onto the failure modes in Section 39; each is annotated with the
mode it guards. They are cheap, and they catch the class of error that survives
a clean test run because it depends on the specific document rather than on the
code path.
"""

from __future__ import annotations

import re

from src.common.schemas.qre_extraction import (
    SCHEMA_VERSION,
    QREExtractionIR,
)
from src.common.schemas.validation import (
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
)

from .extraction.extractor import ExtractionPatterns, load_patterns

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _unanchored(pattern: re.Pattern) -> re.Pattern:
    """Reuse a configured question-ID pattern for searching inside text.

    The configured patterns are anchored to the start of a cell because that is
    where an identifier introduces a question. Finding a *reference* to one means
    looking anywhere in a sentence, so the anchor is dropped rather than a second
    pattern being hard-coded here - the vocabulary stays in configuration
    (Sections 9, 61).
    """
    return re.compile(pattern.pattern.lstrip("^"))


def validate(
    ir: QREExtractionIR, patterns: ExtractionPatterns | None = None
) -> ValidationReport:
    """Check an extraction for structural faults and suspicious content."""
    patterns = patterns or load_patterns()
    issues: list[ValidationIssue] = []

    def error(code: IssueCode, message: str, **kwargs) -> None:
        issues.append(
            ValidationIssue(
                code=code, severity=Severity.ERROR, message=message, **kwargs
            )
        )

    def warn(code: IssueCode, message: str, **kwargs) -> None:
        issues.append(
            ValidationIssue(
                code=code, severity=Severity.WARNING, message=message, **kwargs
            )
        )

    # --- document-level integrity ------------------------------------------

    if ir.schema_version != SCHEMA_VERSION:
        error(
            IssueCode.SCHEMA_VERSION_MISMATCH,
            f"IR declares schema {ir.schema_version} but this code implements "
            f"{SCHEMA_VERSION}. The artifact is stale or was written by another "
            "version; re-extract rather than reinterpreting it.",
        )

    if not _SHA256.match(ir.document.sha256 or ""):
        error(
            IssueCode.MALFORMED_DOCUMENT_HASH,
            "Document hash is not a 64-character hex digest, so this extraction "
            "cannot be tied to the bytes it came from (Section 50).",
        )

    # --- questions ----------------------------------------------------------

    if not ir.questions:
        warn(
            IssueCode.NO_QUESTIONS_EXTRACTED,
            "No questions were extracted. Either the document holds none, or its "
            "conventions are absent from the extraction vocabulary.",
        )

    seen: dict[str, int] = {}
    for question in ir.questions:
        # Section 39, mode 2: wrong or missing question IDs.
        if not question.qid and not question.text:
            error(
                IssueCode.QUESTION_WITHOUT_IDENTITY,
                "A question has neither an identifier nor wording, so nothing "
                "downstream can refer to it.",
                source=question.source,
            )
            continue

        if question.qid:
            # Section 39, mode 29: duplicate question interpretation.
            seen[question.qid] = seen.get(question.qid, 0) + 1

        if question.qid and not question.text:
            warn(
                IssueCode.QUESTION_WITHOUT_TEXT,
                "Question has an identifier but no wording. A question nobody "
                "can read cannot be reviewed or tested.",
                qid=question.qid,
                source=question.source,
            )

        # Section 39, mode 3: missing options.
        if question.raw_options_text and not question.options:
            warn(
                IssueCode.QUESTION_WITHOUT_OPTIONS,
                "Options text is present but no options were split out of it.",
                qid=question.qid,
                source=question.source,
            )

        labels = [o.label.strip().lower() for o in question.options]
        for label in {label for label in labels if labels.count(label) > 1}:
            warn(
                IssueCode.DUPLICATE_OPTION_LABEL,
                f"Option {label!r} appears more than once. This is usually a "
                "split that went wrong, or a genuine duplicate in the QRE.",
                qid=question.qid,
                source=question.source,
            )

        for option in question.options:
            if not option.label.strip():
                error(
                    IssueCode.EMPTY_OPTION_LABEL,
                    "An option has an empty label.",
                    qid=question.qid,
                    source=option.source,
                )

        # Section 39, mode 4: incorrect option codes. Partial coding usually
        # means the split misread the cell, and a half-coded option list is
        # worse than an uncoded one because it looks deliberate.
        coded = [o for o in question.options if o.code]
        if coded and len(coded) != len(question.options):
            warn(
                IssueCode.PARTIAL_OPTION_CODES,
                f"{len(coded)} of {len(question.options)} options carry a code. "
                "Either the QRE codes them inconsistently or the split misread "
                "the cell; no codes were invented for the remainder.",
                qid=question.qid,
                source=question.source,
            )

    for qid, count in sorted(seen.items()):
        if count > 1:
            error(
                IssueCode.DUPLICATE_QUESTION_ID,
                f"Question id {qid!r} appears {count} times. Downstream logic "
                "referring to it cannot know which is meant.",
                qid=qid,
            )

    # --- instructions and references ---------------------------------------

    known_qids = {q.qid for q in ir.questions if q.qid}
    searchers = [_unanchored(p) for p in patterns.question_id_patterns]

    for instruction in ir.instructions:
        if not instruction.raw_text.strip():
            error(
                IssueCode.EMPTY_INSTRUCTION_TEXT,
                "An instruction has no text.",
                qid=instruction.qid,
                source=instruction.source,
            )
            continue

        if instruction.qid and instruction.qid not in known_qids:
            error(
                IssueCode.INSTRUCTION_ORPHANED,
                f"Instruction is attached to {instruction.qid!r}, which is not "
                "among the extracted questions.",
                qid=instruction.qid,
                source=instruction.source,
            )

        # Section 39, mode 26: references to non-existent questions. Reported as
        # a warning, not an error - a dangling reference may be a real defect in
        # the QRE rather than a fault in extraction, and validation is not
        # entitled to decide which.
        referenced: set[str] = set()
        for searcher in searchers:
            referenced.update(m.group(1) for m in searcher.finditer(instruction.raw_text))

        for reference in sorted(referenced - known_qids - {instruction.qid}):
            warn(
                IssueCode.UNRESOLVED_QUESTION_REFERENCE,
                f"Instruction refers to {reference!r}, which was not extracted "
                "from this document. Either the reference is wrong in the QRE or "
                "the question was missed.",
                qid=instruction.qid,
                source=instruction.source,
            )

    # --- provenance ---------------------------------------------------------

    document_name = ir.document.filename
    for label, items in (
        ("question", ir.questions),
        ("instruction", ir.instructions),
        ("section", ir.sections),
        ("unparsed content", ir.unparsed_content),
    ):
        for item in items:
            if item.source.document != document_name:
                error(
                    IssueCode.PROVENANCE_DOCUMENT_MISMATCH,
                    f"A {label} claims to come from "
                    f"{item.source.document!r}, but this IR is for "
                    f"{document_name!r}. Provenance that points at the wrong "
                    "document is worse than none (Section 15).",
                    source=item.source,
                )

    return ValidationReport(
        document=document_name, schema_version=ir.schema_version, issues=issues
    )
