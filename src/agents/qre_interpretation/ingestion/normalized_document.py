"""Normalized document representation.

The common structure both the DOCX and PDF adapters produce, so that the QRE
Reader works against one shape rather than two libraries (CLAUDE.md Section 11).

PROVISIONAL. This is Agent 1 internal, not a cross-agent contract - only
QREExtractionIR and the Canonical Survey Specification are frozen (Section 26).
It is expected to change in Stage 3 once both adapters have exercised it.

Two properties are deliberate rather than incidental:

Nothing here describes a survey. There is no field for a question, an option,
a code or a route. This layer records what the document contains and where it
sits; deciding what any of it means belongs to extraction and interpretation
(Sections 7.1 and 19). The absence of those fields is the enforcement.

Everything carries a location. Provenance is not decoration in this project -
Section 15 requires that we can always answer where in the QRE a piece of
information came from, and a rule whose evidence cannot be traced cannot be
reviewed. A block without a resolvable location is a defect, not a gap.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocumentFormat(str, Enum):
    """Source format of an ingested document."""

    DOCX = "docx"
    PDF = "pdf"


class BlockKind(str, Enum):
    """What kind of text unit a block is, as observed in the document."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"


class WarningCode(str, Enum):
    """Machine-readable ingestion problems.

    These exist so that a document which cannot be read completely fails
    visibly rather than producing confident-looking empty output
    (Sections 8 and 40).
    """

    IMAGE_ONLY_PAGE = "image_only_page"
    NO_TEXT_EXTRACTED = "no_text_extracted"
    EMPTY_TABLE = "empty_table"


class SourceLocation(BaseModel):
    """Where a piece of content sits in its source document.

    ``page`` is optional because DOCX has no reliable page numbering - pagination
    is decided by the renderer, not stored in the file. Section 11 asks for the
    page "where available", and inventing one would fabricate provenance.

    ``order_index`` is a single sequence shared by blocks and tables, so a table
    that appears between two paragraphs stays between them. Position carries
    meaning in a QRE: an instruction below a question usually belongs to it.
    """

    document: str
    order_index: int
    page: int | None = None
    table_index: int | None = None
    row: int | None = None
    column: int | None = None


class Block(BaseModel):
    """A single run of text - a paragraph, heading, or list item."""

    text: str
    kind: BlockKind
    heading_level: int | None = None
    location: SourceLocation


class Cell(BaseModel):
    """One table cell, located by table index plus row and column."""

    text: str
    location: SourceLocation


class Table(BaseModel):
    """A table, preserved as a grid rather than flattened to text.

    QREs carry response options and codes in tables. Flattening one to a text
    blob loses the row-to-column relationship that makes a code mean anything,
    which is failure modes 3, 4 and 7 in Section 39.
    """

    n_rows: int
    n_columns: int
    rows: list[list[Cell]]
    location: SourceLocation


class IngestionWarning(BaseModel):
    """A problem encountered while reading, surfaced rather than swallowed."""

    code: WarningCode
    message: str
    page: int | None = None


class DocumentMetadata(BaseModel):
    """Identity and provenance of the source file and the adapter that read it.

    ``sha256`` identifies the exact bytes ingested, which Section 50 requires for
    reproducibility: a run is only reproducible if we know which document it
    read, not merely which filename.
    """

    filename: str
    sha256: str
    format: DocumentFormat
    adapter: str
    adapter_version: str
    page_count: int | None = None


class NormalizedDocument(BaseModel):
    """A document reduced to located text, tables, and any reading problems."""

    metadata: DocumentMetadata
    blocks: list[Block] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    warnings: list[IngestionWarning] = Field(default_factory=list)

    def ordered_items(self) -> list[Block | Table]:
        """Blocks and tables merged back into document order."""
        items: list[Block | Table] = [*self.blocks, *self.tables]
        return sorted(items, key=lambda i: i.location.order_index)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)
