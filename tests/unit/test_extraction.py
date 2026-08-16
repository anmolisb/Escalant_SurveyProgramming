"""QRE Reader tests.

Three of these carry more weight than the rest: content conservation, verbatim
preservation, and vocabulary independence. They guard the properties that make
the extraction trustworthy rather than merely present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.qre_interpretation.extraction import (
    classify_instruction,
    load_patterns,
    map_columns,
    read,
    read_file,
    split_options,
)
from src.agents.qre_interpretation.extraction.extractor import (
    corroborate_prose_question,
)
from src.agents.qre_interpretation.ingestion import (
    Block,
    BlockKind,
    Cell,
    DocumentFormat,
    DocumentMetadata,
    NormalizedDocument,
    SourceLocation,
    Table,
    load_document,
)
from src.common.schemas.qre_extraction import (
    SCHEMA_VERSION,
    InstructionKind,
    Origin,
    ReviewReason,
)
from src.evaluation import corpus

PATTERNS = load_patterns()


# --- Schema ----------------------------------------------------------------


def test_ir_declares_its_schema_version(sample_docx: Path):
    ir = read_file(sample_docx)
    assert ir.schema_version == SCHEMA_VERSION


def test_ir_records_what_produced_it(sample_docx: Path):
    """Section 50: a run is only reproducible if we know what made it."""
    ir = read_file(sample_docx)
    assert ir.extraction.reader_version
    assert ir.extraction.patterns_fingerprint
    assert len(ir.document.sha256) == 64


def test_named_views_partition_the_instruction_list(sample_docx: Path):
    ir = read_file(sample_docx)
    views = (
        ir.routing_blocks
        + ir.display_blocks
        + ir.validation_blocks
        + ir.quota_blocks
        + ir.randomization_blocks
        + ir.piping_blocks
        + ir.disposition_blocks
        + ir.programming_notes
    )
    unclassified = [
        i for i in ir.instructions if i.kind is InstructionKind.UNCLASSIFIED
    ]
    assert len(views) + len(unclassified) == len(ir.instructions)


# --- The three load-bearing properties --------------------------------------


@pytest.mark.parametrize("path", corpus.development_corpus(), ids=lambda p: p.name)
def test_content_is_conserved(path: Path):
    """Nothing may vanish between ingestion and extraction (Section 16).

    Silent loss is invisible in output review - a reviewer cannot notice the
    absence of something they were never shown. This asserts that every item the
    ingester found is represented somewhere in the IR, even if only as retained
    unparsed content.
    """
    document = load_document(path)
    ir = read(document)

    ingested = {item.location.order_index for item in document.ordered_items()}
    accounted = (
        {s.source.order_index for s in ir.sections}
        | {q.source.order_index for q in ir.questions}
        | {i.source.order_index for i in ir.instructions}
        | {u.source.order_index for u in ir.unparsed_content}
    )

    missing = ingested - accounted
    assert not missing, f"{len(missing)} ingested items vanished: {sorted(missing)[:10]}"


@pytest.mark.parametrize("path", corpus.development_corpus(), ids=lambda p: p.name)
def test_instruction_text_is_verbatim(path: Path):
    """Instructions are stored exactly as written (Section 19).

    Tidying whitespace or rephrasing is already interpretation, and destroys the
    evidence Part 2 and any reviewer depend on.
    """
    document = load_document(path)
    ir = read(document)

    source_texts = {b.text for b in document.blocks}
    source_texts |= {
        cell.text for table in document.tables for row in table.rows for cell in row
    }

    for instruction in ir.instructions:
        assert instruction.raw_text in source_texts, (
            f"instruction text was altered: {instruction.raw_text[:60]!r}"
        )


def _synthetic_question_table(headers: list[str]) -> NormalizedDocument:
    """A one-question table using whatever headers the caller supplies."""

    def cell(text: str, row: int, col: int) -> Cell:
        return Cell(
            text=text,
            location=SourceLocation(
                document="synthetic.docx",
                order_index=1,
                table_index=0,
                row=row,
                column=col,
            ),
        )

    rows = [
        [cell(h, 0, i) for i, h in enumerate(headers)],
        [
            cell("Q1", 1, 0),
            cell("Which brand did you use?", 1, 1),
            cell("single", 1, 2),
            cell("Brand A; Brand B", 1, 3),
            cell("Show if S1 = 1", 1, 4),
        ],
    ]
    return NormalizedDocument(
        metadata=DocumentMetadata(
            filename="synthetic.docx",
            sha256="0" * 64,
            format=DocumentFormat.DOCX,
            adapter="test",
            adapter_version="0.0.0",
        ),
        blocks=[
            Block(
                text="Preamble",
                kind=BlockKind.PARAGRAPH,
                location=SourceLocation(document="synthetic.docx", order_index=0),
            )
        ],
        tables=[
            Table(
                n_rows=2,
                n_columns=len(headers),
                rows=rows,
                location=SourceLocation(
                    document="synthetic.docx", order_index=1, table_index=0
                ),
            )
        ],
    )


def test_unknown_headers_are_flagged_not_guessed():
    """A QRE with unfamiliar column names must degrade safely.

    This is the test that would have failed if the reader had hard-coded the
    synthetic corpus's headers (Sections 9, 10).
    """
    document = _synthetic_question_table(
        ["Ref-Nr", "Frage", "Typ", "Antworten", "Regeln"]
    )
    ir = read(document, PATTERNS)

    assert ir.questions == [], "unknown headers must not yield guessed questions"
    assert any(
        item.reason is ReviewReason.UNRECOGNIZED_TABLE for item in ir.review_queue
    )
    assert any("Q1" in u.text for u in ir.unparsed_content), "rows must be retained"


def test_the_same_table_extracts_once_its_vocabulary_is_configured(tmp_path: Path):
    """Adding synonyms is configuration, never a code change (Section 61)."""
    config = tmp_path / "patterns.toml"
    config.write_text(
        """
[table_detection]
min_header_match_ratio = 0.6

[column_roles]
id = ["ref nr"]
wording = ["frage"]
type = ["typ"]
options = ["antworten"]
logic = ["regeln"]

[question_id]
patterns = ["^([A-Z]{1,3}\\\\d+[a-z]?)\\\\b"]

[instruction_cues]
display = ["show if"]

[review]
flag_unparsed_containing_cues = true
flag_unparsed_containing_question_id = true
""",
        encoding="utf-8",
    )

    document = _synthetic_question_table(
        ["Ref-Nr", "Frage", "Typ", "Antworten", "Regeln"]
    )
    ir = read(document, load_patterns(config))

    assert len(ir.questions) == 1
    question = ir.questions[0]
    assert question.qid == "Q1"
    assert question.text == "Which brand did you use?"
    assert [o.label for o in question.options] == ["Brand A", "Brand B"]


# --- Extraction behaviour ---------------------------------------------------


def test_questions_are_found_in_both_formats():
    for path in corpus.development_corpus():
        ir = read_file(path)
        assert ir.questions, f"{path.name} yielded no questions"


def test_options_never_get_invented_codes(sample_docx: Path):
    """Section 13: a label without a code yields None, not a made-up number."""
    ir = read_file(sample_docx)
    options = [o for q in ir.questions for o in q.options]
    assert options
    assert all(o.code is None or o.code.strip() for o in options)


def test_split_options_reads_codes_only_when_present():
    assert split_options("Yes; No") == [("Yes", None), ("No", None)]
    assert split_options("1 = Male; 2 = Female") == [("Male", "1"), ("Female", "2")]
    assert split_options("") == []


def test_derived_values_are_labelled_as_derived(sample_docx: Path):
    """Splitting a cell into options is derived, not stated (Section 14)."""
    ir = read_file(sample_docx)
    options = [o for q in ir.questions for o in q.options]
    assert all(o.origin is Origin.DERIVED for o in options)


def test_ambiguous_instructions_are_flagged_not_resolved():
    """Cues overlap; forcing a choice would discard the document's vagueness."""
    patterns = load_patterns()
    result = classify_instruction("Terminate and skip to end", patterns)
    assert result.kind is not InstructionKind.UNCLASSIFIED
    if result.ambiguous:
        assert result.score <= 0.5
        assert any(e.signal == "tied_kinds" for e in result.evidence)


def test_confidence_carries_its_evidence(sample_docx: Path):
    """Section 32: a score without evidence cannot be calibrated or reviewed."""
    ir = read_file(sample_docx)
    for question in ir.questions:
        assert question.confidence.evidence
    for instruction in ir.instructions:
        assert instruction.confidence.evidence


def test_a_label_is_not_mistaken_for_a_question():
    """A document title shaped like an ID must not become a question."""
    corroborated, _ = corroborate_prose_question("S01 - SIMPLE", "S01")
    assert not corroborated

    corroborated, _ = corroborate_prose_question(
        "Q1. Which brands have you used?", "Q1"
    )
    assert corroborated


def test_header_mapping_reports_its_match_ratio():
    mapping = map_columns(["ID", "Wording", "Type", "Nonsense"], PATTERNS)
    assert mapping.roles["id"] == 0
    assert 0.0 < mapping.match_ratio < 1.0
    assert mapping.unmapped_headers == ["Nonsense"]


# --- Reproducibility --------------------------------------------------------


def test_extraction_is_deterministic(sample_docx: Path):
    assert read_file(sample_docx).model_dump_json() == (
        read_file(sample_docx).model_dump_json()
    )


def test_the_ir_schema_records_no_wall_clock_time():
    """A time field would make two runs over identical input differ.

    Checked against the model's fields rather than the serialized output, since
    a QRE may legitimately talk about timestamps in its own text - and does.
    When a run happened belongs in the run ledger, not in the artifact.
    """
    from src.common.schemas.qre_extraction import ExtractionRun, QREExtractionIR

    time_like = {"timestamp", "created_at", "generated_at", "run_at", "date", "time"}
    for model in (QREExtractionIR, ExtractionRun):
        assert not (set(model.model_fields) & time_like), (
            f"{model.__name__} records wall-clock time, breaking byte-reproducibility"
        )
