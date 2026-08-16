"""Document ingestion for Agent 1.

Turns a QRE file into a NormalizedDocument. DOCX and PDF are separate ingestion
problems with separate adapters (CLAUDE.md Section 11); this package is the one
entry point over both, so callers never choose a library.

Ingestion records what a document contains and where. It does not decide what
any of it means - no question, option, code or route is recognised here
(Sections 7.1 and 19).
"""

from __future__ import annotations

from pathlib import Path

from .docx_reader import read_docx
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
from .pdf_reader import read_pdf

__all__ = [
    "Block",
    "BlockKind",
    "Cell",
    "DocumentFormat",
    "DocumentMetadata",
    "IngestionWarning",
    "NormalizedDocument",
    "SourceLocation",
    "Table",
    "UnsupportedFormatError",
    "WarningCode",
    "load_document",
    "read_docx",
    "read_pdf",
]


class UnsupportedFormatError(ValueError):
    """Raised for a file extension no adapter handles.

    Failing here is deliberate. Section 8 restricts inputs to DOCX and PDF, and
    a silently skipped file is indistinguishable from a document with nothing
    in it.
    """


_READERS = {".docx": read_docx, ".pdf": read_pdf}


def load_document(path: str | Path) -> NormalizedDocument:
    """Ingest a QRE document, dispatching on file extension."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No such document: {path}")

    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        supported = ", ".join(sorted(_READERS))
        raise UnsupportedFormatError(
            f"Cannot ingest '{path.name}': {path.suffix or 'no extension'} "
            f"is not a supported format. Supported: {supported}."
        )
    return reader(path)
