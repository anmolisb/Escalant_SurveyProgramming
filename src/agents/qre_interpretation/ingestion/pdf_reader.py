"""PDF ingestion adapter.

Reads a PDF into a NormalizedDocument using pdfplumber (decision 0001),
preserving page numbers, table structure and reading order within each page.

Two behaviours worth knowing about:

Image-only pages are detected, not silently skipped. Section 8 requires that a
scanned page be surfaced rather than producing empty output that looks like a
successful read of an empty page. A page with no characters is directly
observable, so the check is a fact rather than an inference.

Table text is not duplicated into blocks. pdfplumber's page text includes the
text inside tables, so emitting both would double-count every response option.
Lines falling inside a detected table's vertical span are left to the table.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pdfplumber

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

ADAPTER = "pdf_reader"
ADAPTER_VERSION = "0.1.0"


def _line_is_inside_table(line: dict, table_bboxes: list[tuple]) -> bool:
    """True if a text line sits within a detected table's vertical span."""
    top = line.get("top")
    bottom = line.get("bottom", top)
    if top is None:
        return False
    for x0, ttop, x1, tbottom in table_bboxes:
        if top >= ttop - 1 and bottom <= tbottom + 1:
            return True
    return False


def _read_tables(
    page, document_name: str, page_number: int, order_index: int, table_index: int
) -> tuple[list[Table], list[IngestionWarning], int, int]:
    tables: list[Table] = []
    warnings: list[IngestionWarning] = []

    for found in page.find_tables():
        extracted = found.extract()
        rows: list[list[Cell]] = []
        for r, row in enumerate(extracted):
            cells: list[Cell] = []
            for c, value in enumerate(row):
                cells.append(
                    Cell(
                        # pdfplumber yields None for a cell it could not read;
                        # that is absence, not an empty string, but at this
                        # layer both normalize to "" with the grid preserved.
                        text=(value or "").strip(),
                        location=SourceLocation(
                            document=document_name,
                            order_index=order_index,
                            page=page_number,
                            table_index=table_index,
                            row=r,
                            column=c,
                        ),
                    )
                )
            rows.append(cells)

        table = Table(
            n_rows=len(rows),
            n_columns=max((len(r) for r in rows), default=0),
            rows=rows,
            location=SourceLocation(
                document=document_name,
                order_index=order_index,
                page=page_number,
                table_index=table_index,
            ),
        )
        if all(not cell.text for row in table.rows for cell in row):
            warnings.append(
                IngestionWarning(
                    code=WarningCode.EMPTY_TABLE,
                    message=f"Table {table_index} on page {page_number} "
                    "was detected but extracted no cell text.",
                    page=page_number,
                )
            )
        tables.append(table)
        order_index += 1
        table_index += 1

    return tables, warnings, order_index, table_index


def read_pdf(path: str | Path) -> NormalizedDocument:
    """Ingest a .pdf file into a NormalizedDocument."""
    path = Path(path)
    document_name = path.name
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    blocks: list[Block] = []
    tables: list[Table] = []
    warnings: list[IngestionWarning] = []

    order_index = 0
    table_index = 0

    with pdfplumber.open(str(path)) as pdf:
        page_count = len(pdf.pages)

        for page_number, page in enumerate(pdf.pages, start=1):
            if not page.chars:
                # No characters at all: scanned image, or a genuinely blank
                # page. Either way the caller must be told, per Section 8.
                warnings.append(
                    IngestionWarning(
                        code=WarningCode.IMAGE_ONLY_PAGE,
                        message=f"Page {page_number} contains no extractable text. "
                        "It may be a scanned image; OCR is not performed.",
                        page=page_number,
                    )
                )
                continue

            found_tables = page.find_tables()
            table_bboxes = [t.bbox for t in found_tables]

            for line in page.extract_text_lines():
                text = (line.get("text") or "").strip()
                if not text or _line_is_inside_table(line, table_bboxes):
                    continue
                blocks.append(
                    Block(
                        # Heading inference is deliberately not attempted here.
                        # A PDF does not record that a line is a heading; only
                        # that it is larger or bolder. Guessing would invent
                        # structure the document does not state (Section 30).
                        text=text,
                        kind=BlockKind.PARAGRAPH,
                        location=SourceLocation(
                            document=document_name,
                            order_index=order_index,
                            page=page_number,
                        ),
                    )
                )
                order_index += 1

            page_tables, page_warnings, order_index, table_index = _read_tables(
                page, document_name, page_number, order_index, table_index
            )
            tables.extend(page_tables)
            warnings.extend(page_warnings)

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
            format=DocumentFormat.PDF,
            adapter=ADAPTER,
            adapter_version=ADAPTER_VERSION,
            page_count=page_count,
        ),
        blocks=blocks,
        tables=tables,
        warnings=warnings,
    )
