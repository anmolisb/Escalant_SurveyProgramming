"""Fixture corpus access, and the holdout gate.

The corpus is split by role (decision 0002): ``fixtures/qre-samples/`` is for
development, ``fixtures/holdout/`` is not read while building the reader. The
holdout is the only instrument in the project that measures whether the reader
learned general document-processing concepts or merely the documents it was
built against - the risk Sections 9, 10 and 61 guard against by intent, and
which nothing else actually measures.

A rule that lives only in a document gets broken by accident. This module makes
the development corpus trivial to reach and the holdout deliberately awkward:

- ``development_corpus()`` just works.
- ``holdout_corpus()`` refuses unless the caller passes a written reason AND
  sets ESCALENT_ALLOW_HOLDOUT=1 in the environment. Two independent, conscious
  acts - neither reachable by autocompleting a function name.
- Every unlocked access is appended to a ledger under ``data/runs/``, so the
  "burned holdout" condition in decision 0002 has an audit trail rather than a
  memory of who looked at what.
- ``verify_holdout_integrity()`` checks the files against a recorded manifest,
  so substitution or quiet editing is detectable.

None of this stops someone opening the file in Word. That is not the goal. The
goal is that accidental use is impossible and deliberate use leaves a record.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures"
DEVELOPMENT_DIR = FIXTURES_DIR / "qre-samples"
HOLDOUT_DIR = FIXTURES_DIR / "holdout"
MANIFEST_PATH = HOLDOUT_DIR / "MANIFEST.sha256"
ACCESS_LEDGER = REPO_ROOT / "data" / "runs" / "holdout_access.jsonl"

UNLOCK_ENV_VAR = "ESCALENT_ALLOW_HOLDOUT"
SUPPORTED_SUFFIXES = {".docx", ".pdf"}

# Set only while hashing holdout files for the integrity check. The test-suite
# read guard consults this so that verifying the holdout does not count as
# reading it - hashing bytes reveals nothing about content.
_integrity_read_in_progress = False


class HoldoutAccessError(RuntimeError):
    """Raised when the holdout is reached for without unlocking it."""


def _corpus_files(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def development_corpus() -> list[Path]:
    """The QREs to build and iterate against."""
    return _corpus_files(DEVELOPMENT_DIR)


def is_holdout_path(path: str | os.PathLike) -> bool:
    """True if a path points inside the holdout directory."""
    try:
        resolved = Path(os.fspath(path)).resolve()
    except (TypeError, ValueError, OSError):
        return False
    return resolved.is_relative_to(HOLDOUT_DIR.resolve())


@contextmanager
def integrity_read() -> Iterator[None]:
    """Mark a block as a sanctioned bytes-only read of holdout files."""
    global _integrity_read_in_progress
    previous = _integrity_read_in_progress
    _integrity_read_in_progress = True
    try:
        yield
    finally:
        _integrity_read_in_progress = previous


def integrity_read_in_progress() -> bool:
    return _integrity_read_in_progress


def holdout_corpus(*, reason: str) -> list[Path]:
    """The held-out QREs. Refuses unless deliberately unlocked.

    Args:
        reason: why the holdout is being opened. Recorded in the ledger.
            Required, and required to be meaningful - this is the sentence a
            reviewer reads when asking whether the holdout is still valid.

    Raises:
        HoldoutAccessError: if the reason is missing or the environment
            variable is not set.
    """
    if not reason or not reason.strip():
        raise HoldoutAccessError(
            "holdout_corpus() requires a written reason. The holdout measures "
            "whether the reader generalizes; opening it without stating why is "
            "how that measurement quietly stops being true."
        )

    if os.environ.get(UNLOCK_ENV_VAR) != "1":
        raise HoldoutAccessError(
            f"The holdout is locked. Set {UNLOCK_ENV_VAR}=1 to open it.\n"
            "Do not do this to debug an extraction failure. Per decision 0002, "
            "using the holdout to fix a specific document burns it, and it must "
            "then be replaced with a fresh selection.\n"
            "Use development_corpus() instead."
        )

    files = _corpus_files(HOLDOUT_DIR)
    _record_access(reason, files)
    return files


def _record_access(reason: str, files: list[Path]) -> None:
    """Append an unlocked holdout access to the ledger."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason.strip(),
        "files": [f.name for f in files],
    }
    try:
        ACCESS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with ACCESS_LEDGER.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        # A ledger that cannot be written must not block a legitimate,
        # already-authorized read. The access still happened; losing the record
        # is worse than nothing but better than a hard failure here.
        pass


def compute_holdout_hashes() -> dict[str, str]:
    """SHA-256 of each holdout file, by filename."""
    hashes: dict[str, str] = {}
    with integrity_read():
        for path in _corpus_files(HOLDOUT_DIR):
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def read_manifest() -> dict[str, str]:
    """The recorded hashes, parsed from ``MANIFEST.sha256``.

    The manifest lives inside the holdout directory but is not holdout content -
    it is a list of digests. Reading it is a sanctioned integrity operation, so
    it runs under the same exemption as hashing.
    """
    if not MANIFEST_PATH.is_file():
        return {}
    manifest: dict[str, str] = {}
    with integrity_read():
        text = MANIFEST_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if digest and name:
            manifest[name.strip()] = digest.strip()
    return manifest


def verify_holdout_integrity() -> list[str]:
    """Compare holdout files against the manifest.

    Returns:
        Human-readable problems. Empty means the holdout is intact.
    """
    recorded = read_manifest()
    if not recorded:
        return ["No holdout manifest found; integrity cannot be verified."]

    actual = compute_holdout_hashes()
    problems: list[str] = []

    for name, digest in sorted(recorded.items()):
        if name not in actual:
            problems.append(f"{name}: recorded in the manifest but missing.")
        elif actual[name] != digest:
            problems.append(f"{name}: contents changed since the manifest was written.")

    for name in sorted(set(actual) - set(recorded)):
        problems.append(f"{name}: present in the holdout but not in the manifest.")

    return problems
