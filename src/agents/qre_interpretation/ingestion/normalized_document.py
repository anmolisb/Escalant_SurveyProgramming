"""Normalized Document Representation — the Step 1 output contract.

Step 1 of Agent 1 Part 1 turns a raw document into this object. Per the step
table, the output is a "structured document object — ordered paragraphs (with
style/formatting metadata) + tables (as row/column grids)".

Design rules this module obeys (CLAUDE.md):
  §11  preserve paragraph order, table structure, headings, source text,
       document position, and basic formatting metadata
  §15  every block carries a source reference so any later claim can be
       traced back to a position in the document
  §7.1 capture what the document says, not what it means — there is
       deliberately no `section`, `question_id` or `condition` field here

Consumed by Step 2 (dynamic section detection), which slices these ordered
blocks into named sections. Step 2 owns that classification, not this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Formats Step 1 can ingest. Only DOCX is in current scope; PDF is a separate
# ingestion problem (CLAUDE.md §11) and is not implemented.
SOURCE_FORMAT_DOCX = "docx"


@dataclass(frozen=True)
class SourceReference:
    """Provenance for one element: where it came from in the source document.

    Answers CLAUDE.md §15's required question — "where did this information
    come from in the QRE?" — at the granularity Step 1 can honestly supply.

    Attributes:
        document:    source file name, e.g. "S01_campus_cafeteria_experience.docx".
        order_index: 0-based position of the block in document body order.
        text:        source text, populated ONLY when the referenced text is not
                     already on the owning object. A block's own `text`/`rows`
                     field is its source text, so blocks leave this None rather
                     than storing the same string twice. Later steps that
                     extract a fragment out of a block (a single cell, part of a
                     paragraph) do populate it, since there the quoted text
                     genuinely differs from the object holding the reference.
    """

    document: str
    order_index: int
    text: str | None = None


@dataclass(frozen=True)
class NormalizedParagraph:
    """One paragraph, with the formatting metadata later steps rely on.

    Attributes:
        order_index:  position in document body order (shared sequence with tables).
        text:         paragraph text, exactly as extracted. Empty paragraphs are
                      kept, since dropping them would silently alter document
                      structure (CLAUDE.md §16).
        style_name:   Word style name, e.g. "Heading 1", "List Bullet", "Normal".
                      Step 2 uses this for structural heading detection.
        is_bold:      True if any run in the paragraph carries direct bold
                      formatting. Step 3 uses this for "Label: value" detection,
                      matching the spec's stated `run.bold` mechanism.
                      Ceiling: reports run-level bold only — bold inherited from
                      a style (a Heading, say) reads as False. That is the
                      documented behaviour, not a bug: this field is an
                      `extracted` fact per CLAUDE.md §14, and resolving
                      style-inherited formatting would make it `derived`.
        source_reference: provenance for this paragraph.
    """

    order_index: int
    text: str
    style_name: str
    is_bold: bool
    source_reference: SourceReference

    # Discriminator for serialization and for consumers that would rather switch
    # on a value than an isinstance check. Not settable — derived from the type.
    kind: str = field(default="paragraph", init=False)


@dataclass(frozen=True)
class NormalizedTable:
    """One table, kept as a row/column grid rather than flattened to text.

    Preserving the grid is the point of this class: the sample QRE carries its
    questionnaire and its routing rules as tables, and flattening them to a
    string would destroy the row/column meaning that Steps 4 and 6 need.

    Attributes:
        order_index: position in document body order (shared sequence with paragraphs).
        rows:        list of rows, each a list of cell texts. Rectangular for
                     ordinary tables.
                     Ceiling: python-docx surfaces a merged cell once per grid
                     position it spans, so a horizontally merged cell appears as
                     the same text repeated across those columns. Step 4 must
                     therefore not treat repeated adjacent cell text as
                     duplicate data.
        source_reference: provenance for this table.
    """

    order_index: int
    rows: list[list[str]]
    source_reference: SourceReference

    kind: str = field(default="table", init=False)

    @property
    def header_row(self) -> list[str]:
        """First row, or empty list for a table with no rows.

        Convenience for logs and review UIs. Derived from `rows`, never stored —
        `rows` stays the single source of truth for table content.
        """
        return self.rows[0] if self.rows else []


# A document body is a single ordered sequence of these two block types.
DocumentBlock = NormalizedParagraph | NormalizedTable


@dataclass(frozen=True)
class NormalizedDocument:
    """Step 1's output: one document, as an ordered sequence of typed blocks.

    Attributes:
        document_name: source file name.
        source_format: which adapter produced this object. Present so later
                       steps never have to infer it; currently always
                       SOURCE_FORMAT_DOCX.
        blocks:        paragraphs and tables interleaved in true document body
                       order. Order matters — an instruction paragraph sitting
                       above a table is context for that table.
    """

    document_name: str
    source_format: str
    blocks: list[DocumentBlock]

    @property
    def paragraphs(self) -> list[NormalizedParagraph]:
        """Paragraph blocks only, in document order."""
        return [b for b in self.blocks if isinstance(b, NormalizedParagraph)]

    @property
    def tables(self) -> list[NormalizedTable]:
        """Table blocks only, in document order."""
        return [b for b in self.blocks if isinstance(b, NormalizedTable)]
