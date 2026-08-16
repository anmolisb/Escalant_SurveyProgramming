"""Tests for the normalized document model itself."""

from __future__ import annotations

from src.agents.qre_interpretation.ingestion import (
    Block,
    BlockKind,
    DocumentFormat,
    DocumentMetadata,
    NormalizedDocument,
    SourceLocation,
    Table,
)


def _doc() -> NormalizedDocument:
    """A document whose table sits between two paragraphs."""
    meta = DocumentMetadata(
        filename="x.docx",
        sha256="0" * 64,
        format=DocumentFormat.DOCX,
        adapter="test",
        adapter_version="0.0.0",
    )
    blocks = [
        Block(
            text="before",
            kind=BlockKind.PARAGRAPH,
            location=SourceLocation(document="x.docx", order_index=0),
        ),
        Block(
            text="after",
            kind=BlockKind.PARAGRAPH,
            location=SourceLocation(document="x.docx", order_index=2),
        ),
    ]
    tables = [
        Table(
            n_rows=0,
            n_columns=0,
            rows=[],
            location=SourceLocation(document="x.docx", order_index=1, table_index=0),
        )
    ]
    return NormalizedDocument(metadata=meta, blocks=blocks, tables=tables)


def test_ordered_items_interleaves_blocks_and_tables():
    items = _doc().ordered_items()
    assert [i.location.order_index for i in items] == [0, 1, 2]
    assert isinstance(items[1], Table), "the table must stay between the paragraphs"


def test_page_is_optional_so_docx_never_fabricates_one():
    location = SourceLocation(document="x.docx", order_index=0)
    assert location.page is None


def test_model_has_no_survey_concepts():
    """Ingestion records structure, not meaning (CLAUDE.md Sections 7.1, 19).

    If a field named for a survey concept ever appears here, interpretation has
    leaked into ingestion and the Part 1 / Part 2 boundary has moved.
    """
    forbidden = {"question", "qid", "option", "code", "routing", "condition", "answer"}
    for model in (Block, Table, NormalizedDocument, SourceLocation):
        fields = set(model.model_fields)
        assert not (fields & forbidden), f"{model.__name__} leaks survey semantics"
