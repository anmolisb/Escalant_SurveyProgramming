"""Tests for the holdout controls (decision 0002).

These test the enforcement itself. If they pass, the holdout cannot be reached
by accident; if they regress, the project loses its only measurement of whether
the reader generalizes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.evaluation import corpus
from src.evaluation.corpus import HoldoutAccessError
from tests.conftest import HoldoutReadError


# --- Layer a: default-deny API ---------------------------------------------


def test_holdout_is_locked_without_the_environment_variable(monkeypatch):
    monkeypatch.delenv(corpus.UNLOCK_ENV_VAR, raising=False)
    with pytest.raises(HoldoutAccessError, match="locked"):
        corpus.holdout_corpus(reason="measuring extraction performance")


def test_holdout_requires_a_reason_even_when_unlocked(monkeypatch):
    monkeypatch.setenv(corpus.UNLOCK_ENV_VAR, "1")
    with pytest.raises(HoldoutAccessError, match="reason"):
        corpus.holdout_corpus(reason="   ")


def test_unlocking_needs_both_factors(monkeypatch):
    """Neither factor alone opens it."""
    monkeypatch.setenv(corpus.UNLOCK_ENV_VAR, "1")
    with pytest.raises(HoldoutAccessError):
        corpus.holdout_corpus(reason="")

    monkeypatch.setenv(corpus.UNLOCK_ENV_VAR, "0")
    with pytest.raises(HoldoutAccessError):
        corpus.holdout_corpus(reason="a genuine reason")


def test_development_corpus_excludes_every_holdout_file():
    dev = corpus.development_corpus()
    assert len(dev) == 15
    assert not any(corpus.is_holdout_path(p) for p in dev)


def test_development_corpus_contains_both_formats():
    """Ingestion must not quietly become DOCX-only."""
    suffixes = {p.suffix.lower() for p in corpus.development_corpus()}
    assert {".docx", ".pdf"} <= suffixes


# --- Layer b: test-suite read guard ----------------------------------------


def test_guard_blocks_opening_a_holdout_file():
    target = corpus.HOLDOUT_DIR / "C03_b2b_saas_decision_journey.docx"
    with pytest.raises(HoldoutReadError):
        target.open("rb")


def test_guard_blocks_builtin_open_too():
    target = corpus.HOLDOUT_DIR / "M04_hotel_stay_experience.docx"
    with pytest.raises(HoldoutReadError):
        open(target, "rb")  # noqa: SIM115


def test_guard_blocks_ingestion_of_a_holdout_document():
    """The realistic accident: a loop over fixtures/ that widened by one folder."""
    from src.agents.qre_interpretation.ingestion import load_document

    target = corpus.HOLDOUT_DIR / "QRE_2_Moderate_Cloud_Storage_Concept_Test.pdf"
    with pytest.raises(HoldoutReadError):
        load_document(target)


def test_guard_leaves_development_files_alone(sample_docx: Path):
    with sample_docx.open("rb") as handle:
        assert handle.read(4) == b"PK\x03\x04", "a .docx is a zip"


def test_guard_does_not_break_ordinary_file_io(tmp_path: Path):
    path = tmp_path / "scratch.txt"
    path.write_text("fine", encoding="utf-8")
    assert path.read_text(encoding="utf-8") == "fine"


# --- Layer c: integrity manifest -------------------------------------------


def test_holdout_matches_its_manifest():
    """Detects substitution or quiet editing of the held-out documents."""
    assert corpus.verify_holdout_integrity() == []


def test_manifest_covers_every_holdout_file():
    recorded = corpus.read_manifest()
    assert len(recorded) == 3
    assert all(len(digest) == 64 for digest in recorded.values())


def test_hashing_is_exempt_from_the_read_guard():
    """Reading bytes to compare a digest reveals nothing about content."""
    assert len(corpus.compute_holdout_hashes()) == 3


# --- Layer d: access ledger -------------------------------------------------


def test_unlocked_access_is_recorded(monkeypatch, tmp_path: Path):
    ledger = tmp_path / "holdout_access.jsonl"
    monkeypatch.setattr(corpus, "ACCESS_LEDGER", ledger)
    monkeypatch.setenv(corpus.UNLOCK_ENV_VAR, "1")

    corpus.holdout_corpus(reason="stage 8 evaluation run")

    import json

    entry = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert entry["reason"] == "stage 8 evaluation run"
    assert len(entry["files"]) == 3
    assert entry["timestamp"]


def test_ledger_failure_does_not_block_authorized_access(monkeypatch, tmp_path: Path):
    """Losing the record is bad; failing an approved read is worse."""
    monkeypatch.setattr(corpus, "ACCESS_LEDGER", tmp_path / "nope" / "x.jsonl")
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setenv(corpus.UNLOCK_ENV_VAR, "1")

    assert len(corpus.holdout_corpus(reason="ledger failure path")) == 3
