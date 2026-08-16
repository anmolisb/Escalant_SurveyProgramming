"""Adapter tests, run against the development corpus only."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.qre_interpretation.ingestion import (
    BlockKind,
    DocumentFormat,
    UnsupportedFormatError,
    WarningCode,
    load_document,
)
from src.evaluation import corpus


# --- DOCX ------------------------------------------------------------------


def test_docx_recovers_text_and_tables(sample_docx: Path):
    doc = load_document(sample_docx)
    assert doc.metadata.format is DocumentFormat.DOCX
    assert doc.blocks, "expected text blocks"
    assert doc.tables, "expected tables; the corpus carries options in tables"


def test_docx_has_no_page_numbers():
    """DOCX stores no pagination, so claiming a page would fabricate provenance."""
    docx_files = [p for p in corpus.development_corpus() if p.suffix == ".docx"]
    doc = load_document(docx_files[0])
    assert doc.metadata.page_count is None
    assert all(b.location.page is None for b in doc.blocks)


def test_docx_preserves_document_order(sample_docx: Path):
    """The interleaving test.

    python-docx exposes paragraphs and tables as separate sequences; reading
    them naively puts every table after every paragraph. If ordering regresses,
    a table will no longer have text on both sides of it.
    """
    doc = load_document(sample_docx)
    indices = [i.location.order_index for i in doc.ordered_items()]
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices), "order_index must be unique"

    table_positions = {t.location.order_index for t in doc.tables}
    block_positions = {b.location.order_index for b in doc.blocks}
    first_table = min(table_positions)
    assert any(p < first_table for p in block_positions), "text should precede a table"
    assert any(p > first_table for p in block_positions), "text should follow a table"


def test_docx_detects_headings(sample_docx: Path):
    doc = load_document(sample_docx)
    headings = [b for b in doc.blocks if b.kind is BlockKind.HEADING]
    assert headings, "the corpus uses real Heading styles"
    assert all(h.heading_level is not None for h in headings)


# --- PDF -------------------------------------------------------------------


def test_pdf_recovers_pages_and_text(sample_pdf: Path):
    doc = load_document(sample_pdf)
    assert doc.metadata.format is DocumentFormat.PDF
    assert doc.metadata.page_count and doc.metadata.page_count > 0
    assert doc.blocks
    assert all(b.location.page is not None for b in doc.blocks), "PDF pages are known"


def test_pdf_page_numbers_are_one_based_and_within_range(sample_pdf: Path):
    doc = load_document(sample_pdf)
    pages = {b.location.page for b in doc.blocks}
    assert min(pages) >= 1
    assert max(pages) <= doc.metadata.page_count


def test_image_only_pdf_is_reported_not_silently_empty(image_only_pdf: Path):
    """CLAUDE.md Section 8: a page with no text must be surfaced.

    The failure this prevents is the quiet one - a scanned QRE producing an
    empty document that looks like a successful read.
    """
    doc = load_document(image_only_pdf)
    assert not doc.blocks
    codes = {w.code for w in doc.warnings}
    assert WarningCode.IMAGE_ONLY_PAGE in codes
    assert any(w.page == 1 for w in doc.warnings)


# --- Dispatcher and shared guarantees ---------------------------------------


def test_unsupported_format_raises(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("not a QRE", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        load_document(path)


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_document(tmp_path / "absent.docx")


@pytest.mark.parametrize("path", corpus.development_corpus(), ids=lambda p: p.name)
def test_every_development_document_ingests(path: Path):
    """Whole-corpus smoke test: 15 documents, both formats."""
    doc = load_document(path)
    assert doc.blocks or doc.tables, f"{path.name} yielded nothing"
    assert doc.metadata.sha256 and len(doc.metadata.sha256) == 64


@pytest.mark.parametrize("path", corpus.development_corpus(), ids=lambda p: p.name)
def test_every_element_carries_provenance(path: Path):
    """Section 15: an element whose source cannot be traced cannot be reviewed."""
    doc = load_document(path)
    for block in doc.blocks:
        assert block.location.document == path.name
        assert block.location.order_index >= 0
    for table in doc.tables:
        assert table.location.table_index is not None
        for r, row in enumerate(table.rows):
            for c, cell in enumerate(row):
                assert cell.location.row == r and cell.location.column == c


def test_ingestion_is_deterministic(sample_docx: Path):
    """Section 50: same bytes in, same structure out."""
    assert load_document(sample_docx).model_dump_json() == (
        load_document(sample_docx).model_dump_json()
    )
