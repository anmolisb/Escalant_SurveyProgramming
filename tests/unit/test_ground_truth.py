"""Tests for the ground-truth loader and the scoring harness.

The harness is exercised against a small hand-built example rather than the
corpus, because no real ground truth exists yet - and manufacturing some here
would be the exact correlated-authorship failure decision 0003 prohibits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.schemas.ground_truth import (
    GroundTruthDocument,
    GroundTruthOption,
    GroundTruthQuestion,
)
from src.common.schemas.qre_extraction import (
    Confidence,
    ExtractedOption,
    ExtractedQuestion,
    ExtractionRun,
    Origin,
    QREExtractionIR,
    SourceDocument,
    SourceRef,
)
from src.evaluation.ground_truth import (
    GroundTruthFormatError,
    load_worksheet,
    write_worksheet,
)
from src.evaluation.scoring import CorpusScore, normalize, score_document

SHA = "a" * 64


# --- Worksheets -------------------------------------------------------------


def test_generated_worksheet_is_blank(tmp_path: Path):
    """Decision 0003: pre-filled answers turn derivation into verification."""
    path = write_worksheet("S01_example.docx", SHA, tmp_path / "s01.gt.csv")
    content = path.read_text(encoding="utf-8")

    assert "source_sha256: " + SHA in content
    assert "qid,question_text" in content
    body = [
        line
        for line in content.splitlines()
        if line and not line.startswith("#") and not line.startswith("qid,")
    ]
    assert body == [], "the worksheet must contain no answers"


def _filled(tmp_path: Path, rows: str, coded_by: str = "A. Reviewer") -> Path:
    path = tmp_path / "doc.gt.csv"
    path.write_text(
        f"# source_document: doc.docx\n"
        f"# source_sha256: {SHA}\n"
        f"# coded_by: {coded_by}\n"
        f"# coding_pass: first\n"
        "qid,question_text,question_type,options,option_codes,instructions,section,notes\n"
        + rows,
        encoding="utf-8",
    )
    return path


def test_loads_a_filled_worksheet(tmp_path: Path):
    path = _filled(
        tmp_path,
        "Q1,Which brand?,single,Brand A; Brand B,1;2,Show if S1 = 1,Screener,\n",
    )
    truth = load_worksheet(path)

    assert truth.coded_by == "A. Reviewer"
    question = truth.question("Q1")
    assert question.question_type == "single"
    assert [o.label for o in question.options] == ["Brand A", "Brand B"]
    assert [o.code for o in question.options] == ["1", "2"]
    assert question.instructions == ["Show if S1 = 1"]


def test_unattributed_ground_truth_is_rejected(tmp_path: Path):
    """Independence cannot be audited if nobody signed the file."""
    path = _filled(tmp_path, "Q1,Which brand?,single,,,,,\n", coded_by="")
    with pytest.raises(GroundTruthFormatError, match="coded_by"):
        load_worksheet(path)


def test_option_and_code_counts_must_agree(tmp_path: Path):
    """Padding codes to fit would fabricate data inside the measuring stick."""
    path = _filled(tmp_path, "Q1,Which brand?,single,A; B; C,1;2,,,\n")
    with pytest.raises(GroundTruthFormatError, match="codes"):
        load_worksheet(path)


def test_duplicate_question_ids_are_rejected(tmp_path: Path):
    path = _filled(tmp_path, "Q1,First,single,,,,,\nQ1,Second,single,,,,,\n")
    with pytest.raises(GroundTruthFormatError, match="duplicate"):
        load_worksheet(path)


def test_blank_rows_are_ignored(tmp_path: Path):
    path = _filled(tmp_path, "Q1,Which brand?,single,,,,,\n,,,,,,,\n,,,,,,,\n")
    assert len(load_worksheet(path).questions) == 1


# --- Scoring ----------------------------------------------------------------


def _ir(questions: list[ExtractedQuestion], sha: str = SHA) -> QREExtractionIR:
    return QREExtractionIR(
        document=SourceDocument(
            filename="doc.docx",
            sha256=sha,
            format="docx",
            ingestion_adapter="test",
            ingestion_adapter_version="0",
        ),
        extraction=ExtractionRun(
            reader="test", reader_version="0", patterns_fingerprint="0"
        ),
        questions=questions,
    )


def _question(qid: str, text: str, qtype: str, options: list[str]) -> ExtractedQuestion:
    ref = SourceRef(document="doc.docx", order_index=0)
    return ExtractedQuestion(
        qid=qid,
        text=text,
        raw_type=qtype,
        options=[
            ExtractedOption(label=o, origin=Origin.DERIVED, source=ref) for o in options
        ],
        confidence=Confidence(score=0.9),
        source=ref,
    )


def _truth(questions: list[GroundTruthQuestion]) -> GroundTruthDocument:
    return GroundTruthDocument(
        source_document="doc.docx",
        source_sha256=SHA,
        coded_by="A. Reviewer",
        questions=questions,
    )


def test_perfect_extraction_scores_one():
    ir = _ir([_question("Q1", "Which brand?", "single", ["A", "B"])])
    truth = _truth(
        [
            GroundTruthQuestion(
                qid="Q1",
                text="Which brand?",
                question_type="single",
                options=[GroundTruthOption(label="A"), GroundTruthOption(label="B")],
            )
        ]
    )
    score = score_document(ir, truth)
    assert score.recall == 1.0 and score.precision == 1.0
    assert score.mismatches == []


def test_a_missed_question_lowers_recall_and_is_named():
    ir = _ir([_question("Q1", "Which brand?", "single", [])])
    truth = _truth(
        [
            GroundTruthQuestion(qid="Q1", text="Which brand?"),
            GroundTruthQuestion(qid="Q2", text="Why?"),
        ]
    )
    score = score_document(ir, truth)
    assert score.recall == 0.5
    assert score.missed_qids == ["Q2"]


def test_an_invented_question_lowers_precision_and_is_named():
    ir = _ir(
        [
            _question("Q1", "Which brand?", "single", []),
            _question("S01", "TITLE PAGE", "single", []),
        ]
    )
    truth = _truth([GroundTruthQuestion(qid="Q1", text="Which brand?")])
    score = score_document(ir, truth)
    assert score.precision == 0.5
    assert score.spurious_qids == ["S01"]


def test_mismatches_report_both_values():
    """A score without the offending values cannot be acted on."""
    ir = _ir([_question("Q1", "Which brand?", "multi", ["A"])])
    truth = _truth(
        [
            GroundTruthQuestion(
                qid="Q1",
                text="Which brand?",
                question_type="single",
                options=[GroundTruthOption(label="A"), GroundTruthOption(label="B")],
            )
        ]
    )
    score = score_document(ir, truth)
    fields = {m.field for m in score.mismatches}
    assert "type" in fields and "options" in fields
    type_mismatch = next(m for m in score.mismatches if m.field == "type")
    assert type_mismatch.expected == "single" and type_mismatch.actual == "multi"


def test_scoring_refuses_a_stale_ground_truth():
    """Coding was done against specific bytes; scoring other bytes is meaningless."""
    ir = _ir([_question("Q1", "Which brand?", "single", [])], sha="b" * 64)
    truth = _truth([GroundTruthQuestion(qid="Q1")])
    with pytest.raises(ValueError, match="different version"):
        score_document(ir, truth)


def test_comparison_ignores_whitespace_but_not_wording():
    assert normalize("  Which   BRAND? ") == normalize("which brand?")
    assert normalize("Which brand?") != normalize("Which brands?")


def test_formats_are_reported_separately():
    """A strong DOCX average must not be able to hide a weak PDF one."""
    strong = score_document(
        _ir([_question("Q1", "A", "single", [])]),
        _truth([GroundTruthQuestion(qid="Q1", text="A")]),
    )
    weak = score_document(
        _ir([_question("Q1", "A", "single", [])]),
        _truth(
            [GroundTruthQuestion(qid="Q1", text="A"), GroundTruthQuestion(qid="Q2")]
        ),
    )
    weak.format = "pdf"

    result = CorpusScore(documents=[strong, weak])
    assert result.recall("docx") == 1.0
    assert result.recall("pdf") == 0.5
    assert "pdf" in result.report()
