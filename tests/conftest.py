"""Shared test configuration, and the holdout read guard.

The guard patches file opening for the duration of every test and raises if
anything resolves to a path inside ``fixtures/holdout/``. It is a backstop
behind the default-deny API in ``src.evaluation.corpus``: that module stops a
caller asking for the holdout deliberately, while this stops a test reaching it
by accident - through a glob over ``fixtures/``, a hard-coded path, or a helper
that widened its search without anyone noticing.

Hashing for the integrity check is exempt, because reading bytes to compare a
digest reveals nothing about content.
"""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path

import pytest

from src.evaluation import corpus


class HoldoutReadError(AssertionError):
    """Raised when a test opens a file inside the holdout directory."""


def _refuse(path) -> None:
    raise HoldoutReadError(
        f"A test tried to open a holdout file: {path}\n\n"
        "fixtures/holdout/ is not read during development (decision 0002). It "
        "is the only measurement of whether the reader generalizes beyond the "
        "documents it was built against.\n"
        "Use src.evaluation.corpus.development_corpus() instead."
    )


@pytest.fixture(autouse=True)
def _guard_holdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a file inside fixtures/holdout/."""
    real_builtin_open = builtins.open
    real_path_open = Path.open

    def guarded_open(file, *args, **kwargs):
        # An int is a file descriptor, not a path; nothing to check.
        if not isinstance(file, int) and not corpus.integrity_read_in_progress():
            if corpus.is_holdout_path(file):
                _refuse(file)
        return real_builtin_open(file, *args, **kwargs)

    def guarded_path_open(self: Path, *args, **kwargs):
        if not corpus.integrity_read_in_progress() and corpus.is_holdout_path(self):
            _refuse(self)
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)


@pytest.fixture
def development_files() -> list[Path]:
    """The development corpus, as paths."""
    return corpus.development_corpus()


@pytest.fixture
def sample_docx() -> Path:
    """One representative DOCX from the development corpus."""
    files = [p for p in corpus.development_corpus() if p.suffix == ".docx"]
    assert files, "No DOCX fixtures found in the development corpus."
    return files[0]


@pytest.fixture
def sample_pdf() -> Path:
    """One representative PDF from the development corpus."""
    files = [p for p in corpus.development_corpus() if p.suffix == ".pdf"]
    assert files, "No PDF fixtures found in the development corpus."
    return files[0]


@pytest.fixture
def image_only_pdf(tmp_path: Path) -> Path:
    """A minimal, valid PDF with one page and no text operators.

    Hand-built rather than generated, because the corpus contains no scanned
    document and adding a PDF writer purely to produce a test fixture would mean
    installing a dependency the application never uses.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    startxref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % startxref

    path = tmp_path / "scanned_only.pdf"
    path.write_bytes(bytes(out))
    return path
