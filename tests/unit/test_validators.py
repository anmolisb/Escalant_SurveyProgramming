"""Tests for deterministic IR validation.

Each check is tested against a minimal IR built to trigger it, rather than
against the corpus. A check that only fires on one fixture stops being a check
the moment the fixture changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.qre_interpretation.extraction import read_file, split_options
from src.agents.qre_interpretation.validators import validate
from src.common.schemas.qre_extraction import (
    SCHEMA_VERSION,
    Confidence,
    ExtractedInstruction,
    ExtractedOption,
    ExtractedQuestion,
    ExtractionRun,
    InstructionKind,
    Origin,
    QREExtractionIR,
    SourceDocument,
    SourceRef,
)
from src.common.schemas.validation import IssueCode, Severity
from src.evaluation import corpus

SHA = "a" * 64
REF = SourceRef(document="doc.docx", order_index=0)


def _ir(**kwargs) -> QREExtractionIR:
    return QREExtractionIR(
        document=SourceDocument(
            filename="doc.docx",
            sha256=kwargs.pop("sha256", SHA),
            format="docx",
            ingestion_adapter="test",
            ingestion_adapter_version="0",
        ),
        extraction=ExtractionRun(
            reader="test", reader_version="0", patterns_fingerprint="0"
        ),
        **kwargs,
    )


def _question(qid=None, text="Which brand?", options=None, ref=REF):
    return ExtractedQuestion(
        qid=qid,
        text=text,
        options=options or [],
        confidence=Confidence(score=0.9),
        source=ref,
    )


def _instruction(text="Skip to Q8", qid=None, ref=REF):
    return ExtractedInstruction(
        raw_text=text,
        kind=InstructionKind.ROUTING,
        qid=qid,
        confidence=Confidence(score=0.7),
        source=ref,
    )


def _codes(report, code: IssueCode) -> list:
    return [i for i in report.issues if i.code is code]


# --- Structural errors ------------------------------------------------------


def test_duplicate_question_ids_are_an_error():
    report = validate(_ir(questions=[_question("Q1"), _question("Q1")]))
    assert not report.is_valid
    assert _codes(report, IssueCode.DUPLICATE_QUESTION_ID)


def test_a_question_with_no_identity_is_an_error():
    report = validate(_ir(questions=[_question(qid=None, text=None)]))
    assert not report.is_valid
    assert _codes(report, IssueCode.QUESTION_WITHOUT_IDENTITY)


def test_empty_option_label_is_an_error():
    question = _question(
        "Q1", options=[ExtractedOption(label="  ", origin=Origin.DERIVED, source=REF)]
    )
    report = validate(_ir(questions=[question]))
    assert not report.is_valid
    assert _codes(report, IssueCode.EMPTY_OPTION_LABEL)


def test_malformed_document_hash_is_an_error():
    report = validate(_ir(sha256="not-a-hash", questions=[_question("Q1")]))
    assert not report.is_valid
    assert _codes(report, IssueCode.MALFORMED_DOCUMENT_HASH)


def test_schema_version_mismatch_is_an_error():
    ir = _ir(questions=[_question("Q1")])
    ir.schema_version = "0.0.1-old"
    report = validate(ir)
    assert not report.is_valid
    assert _codes(report, IssueCode.SCHEMA_VERSION_MISMATCH)


def test_provenance_pointing_at_another_document_is_an_error():
    """Provenance that points at the wrong document is worse than none."""
    stray = SourceRef(document="somewhere_else.docx", order_index=0)
    report = validate(_ir(questions=[_question("Q1", ref=stray)]))
    assert not report.is_valid
    assert _codes(report, IssueCode.PROVENANCE_DOCUMENT_MISMATCH)


def test_instruction_attached_to_an_unknown_question_is_an_error():
    report = validate(
        _ir(questions=[_question("Q1")], instructions=[_instruction(qid="Q99")])
    )
    assert not report.is_valid
    assert _codes(report, IssueCode.INSTRUCTION_ORPHANED)


# --- Warnings ---------------------------------------------------------------


def test_a_dangling_reference_is_a_warning_not_an_error():
    """The fault may be in the QRE, and validation may not decide which."""
    report = validate(
        _ir(
            questions=[_question("Q1")],
            instructions=[_instruction("Skip to Q8 if selected")],
        )
    )
    issues = _codes(report, IssueCode.UNRESOLVED_QUESTION_REFERENCE)
    assert issues and issues[0].severity is Severity.WARNING
    assert report.is_valid, "a dangling reference does not make the IR malformed"


def test_partial_option_codes_warn():
    options = [
        ExtractedOption(label="Yes", code="1", origin=Origin.DERIVED, source=REF),
        ExtractedOption(label="No", code=None, origin=Origin.DERIVED, source=REF),
    ]
    report = validate(_ir(questions=[_question("Q1", options=options)]))
    assert _codes(report, IssueCode.PARTIAL_OPTION_CODES)
    assert report.is_valid


def test_duplicate_option_labels_warn():
    options = [
        ExtractedOption(label="Yes", origin=Origin.DERIVED, source=REF),
        ExtractedOption(label="yes", origin=Origin.DERIVED, source=REF),
    ]
    report = validate(_ir(questions=[_question("Q1", options=options)]))
    assert _codes(report, IssueCode.DUPLICATE_OPTION_LABEL)


def test_no_questions_warns():
    report = validate(_ir())
    assert _codes(report, IssueCode.NO_QUESTIONS_EXTRACTED)


def test_a_clean_ir_is_valid_and_quiet():
    report = validate(
        _ir(
            questions=[
                _question(
                    "Q1",
                    options=[
                        ExtractedOption(
                            label="Yes", code="1", origin=Origin.DERIVED, source=REF
                        ),
                        ExtractedOption(
                            label="No", code="2", origin=Origin.DERIVED, source=REF
                        ),
                    ],
                )
            ],
            instructions=[_instruction("Always show", qid="Q1")],
        )
    )
    assert report.is_valid
    assert report.issues == []


# --- Regression: the bug this validator found -------------------------------


def test_option_codes_are_numbers_or_single_letters():
    """Regression for a fabricated code.

    "Rows: Access" parsed as code "Rows" for label "Access", inventing a code
    the QRE never gave. Found by the partial_option_codes check, not by any test
    written beforehand.
    """
    assert split_options("Rows: Access; Communication") == [
        ("Rows: Access", None),
        ("Communication", None),
    ]
    assert split_options("1 = Male; 2 = Female") == [("Male", "1"), ("Female", "2")]
    assert split_options("A) Yes; B) No") == [("Yes", "A"), ("No", "B")]
    assert split_options("1 - Very poor; 2 - Poor") == [
        ("1 - Very poor", None),
        ("2 - Poor", None),
    ]


# --- Corpus ------------------------------------------------------------------


@pytest.mark.parametrize("path", corpus.development_corpus(), ids=lambda p: p.name)
def test_validation_runs_on_every_document(path: Path):
    """Validation must never crash, whatever the extraction produced."""
    report = validate(read_file(path))
    assert report.document == path.name
    assert report.schema_version == SCHEMA_VERSION


def test_validation_is_deterministic(sample_docx: Path):
    ir = read_file(sample_docx)
    assert validate(ir).model_dump_json() == validate(ir).model_dump_json()
