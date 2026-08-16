"""DOCX ingestion adapter.

Reads a Word document into a NormalizedDocument, preserving document order,
table structure and heading information.

The ordering trap: python-docx exposes ``document.paragraphs`` and
``document.tables`` as two independent sequences, so reading them separately
loses the interleaving between them entirely - every table ends up after every
paragraph. This module walks the body's XML children instead, which is the only
way to recover true document order.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from .normalized_document import (
    Block,
    BlockKind,
    Cell,
    DocumentFormat,
    DocumentMetadata,
    IngestionWarning,
    NormalizedDocument,
    SourceLocation,
    Table,
    WarningCode,
)

ADAPTER = "docx_reader"
ADAPTER_VERSION = "0.1.0"

_HEADING_LEVEL = re.compile(r"heading\s*(\d+)", re.IGNORECASE)


def _classify(style_name: str) -> tuple[BlockKind, int | None]:
    """Map a Word paragraph style to a block kind.

    Style is treated as a signal, never a requirement. Section 9 forbids relying
    on document conventions being present, so a document that uses no heading
    styles still ingests - its blocks are simply paragraphs, and section
    structure is left for a later stage to work out rather than guessed here.
    """
    name = (style_name or "").strip()

    match = _HEADING_LEVEL.search(name)
    if match:
        return BlockKind.HEADING, int(match.group(1))
    if name.lower().startswith(("list", "bullet")):
        return BlockKind.LIST_ITEM, None
    return BlockKind.PARAGRAPH, None


def _read_table(
    table: DocxTable, document_name: str, order_index: int, table_index: int
) -> Table:
    rows: list[list[Cell]] = []
    for r, row in enumerate(table.rows):
        cells: list[Cell] = []
        for c, cell in enumerate(row.cells):
            cells.append(
                Cell(
                    text=cell.text.strip(),
                    location=SourceLocation(
                        document=document_name,
                        order_index=order_index,
                        table_index=table_index,
                        row=r,
                        column=c,
                    ),
                )
            )
        rows.append(cells)

    return Table(
        n_rows=len(rows),
        n_columns=max((len(r) for r in rows), default=0),
        rows=rows,
        location=SourceLocation(
            document=document_name,
            order_index=order_index,
            table_index=table_index,
        ),
    )


def read_docx(path: str | Path) -> NormalizedDocument:
    """Ingest a .docx file into a NormalizedDocument."""
    path = Path(path)
    document_name = path.name
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    document = docx.Document(str(path))

    blocks: list[Block] = []
    tables: list[Table] = []
    warnings: list[IngestionWarning] = []

    order_index = 0
    table_index = 0

    # Walking the body's children is what preserves paragraph/table interleaving.
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = DocxParagraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue  # Blank paragraphs are layout, not content.

            kind, level = _classify(paragraph.style.name if paragraph.style else "")
            blocks.append(
                Block(
                    text=text,
                    kind=kind,
                    heading_level=level,
                    location=SourceLocation(
                        document=document_name, order_index=order_index
                    ),
                )
            )
            order_index += 1

        elif child.tag == qn("w:tbl"):
            table = _read_table(
                DocxTable(child, document), document_name, order_index, table_index
            )
            if all(not cell.text for row in table.rows for cell in row):
                warnings.append(
                    IngestionWarning(
                        code=WarningCode.EMPTY_TABLE,
                        message=f"Table {table_index} extracted with no cell text.",
                    )
                )
            tables.append(table)
            order_index += 1
            table_index += 1

    if not blocks and not tables:
        warnings.append(
            IngestionWarning(
                code=WarningCode.NO_TEXT_EXTRACTED,
                message="No text or tables were recovered from this document.",
            )
        )

    return NormalizedDocument(
        metadata=DocumentMetadata(
            filename=document_name,
            sha256=sha256,
            format=DocumentFormat.DOCX,
            adapter=ADAPTER,
            adapter_version=ADAPTER_VERSION,
            page_count=None,  # DOCX does not store pagination.
        ),
        blocks=blocks,
        tables=tables,
        warnings=warnings,
    )
