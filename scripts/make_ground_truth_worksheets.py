"""Create blank ground-truth worksheets for the development corpus.

The worksheets are EMPTY by design. They carry the document's identity and the
column headers; every expected value is left for a human to derive by reading
the QRE (decision 0003).

Pre-filling the reader's answers would make the task far quicker and the result
worthless: a reviewer shown a plausible answer verifies it, while a reviewer
shown a blank field works it out. Only the second produces evidence independent
of the thing being measured.

Existing worksheets are never overwritten - hand-coded work is not regenerable.

Usage:
    python scripts/make_ground_truth_worksheets.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agents.qre_interpretation.ingestion import load_document  # noqa: E402
from src.evaluation import corpus  # noqa: E402
from src.evaluation.ground_truth import (  # noqa: E402
    GROUND_TRUTH_DIR,
    worksheet_path,
    write_worksheet,
)


def main() -> int:
    created, skipped = [], []

    for path in corpus.development_corpus():
        destination = worksheet_path(path.name)
        if destination.exists():
            skipped.append(destination.name)
            continue

        # Only the file's identity is read here, never its interpretation.
        document = load_document(path)
        write_worksheet(path.name, document.metadata.sha256, destination)
        created.append(destination.name)

    for name in created:
        print(f"created  {name}")
    for name in skipped:
        print(f"kept     {name} (already exists, not overwritten)")

    print(f"\nWorksheets in {GROUND_TRUTH_DIR.relative_to(REPO_ROOT)}")
    print(
        "\nFill one row per question the QRE asks. Leave a field blank where the\n"
        "QRE does not state it - a blank is a finding, not an omission. Put your\n"
        "name in the 'coded_by' header line; the loader rejects files without it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
