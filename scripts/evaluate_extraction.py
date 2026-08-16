"""Score the QRE Reader against whatever ground truth exists.

Runs over every filled worksheet in data/ground_truth/Synthetic/ and reports the
Section 38 Part 1 metrics, errors first. Documents without ground truth are
listed as unmeasured rather than silently omitted - an evaluation that hides how
much of the corpus it did not cover overstates itself.

Usage:
    python scripts/evaluate_extraction.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agents.qre_interpretation.extraction import read_file  # noqa: E402
from src.evaluation import corpus  # noqa: E402
from src.evaluation.ground_truth import (  # noqa: E402
    available_ground_truth,
    load_worksheet,
)
from src.evaluation.scoring import CorpusScore, score_document  # noqa: E402


def main() -> int:
    worksheets = available_ground_truth()
    if not worksheets:
        print(
            "No ground truth found in data/ground_truth/Synthetic/.\n\n"
            "Create blank worksheets with:\n"
            "    python scripts/make_ground_truth_worksheets.py\n\n"
            "Until they are filled in by a human, the reader's accuracy is "
            "unmeasured. It is not zero and it is not high - it is unknown, and\n"
            "no claim about it is defensible (CLAUDE.md Section 38)."
        )
        return 1

    by_name = {p.name: p for p in corpus.development_corpus()}
    result = CorpusScore()
    unreadable: list[str] = []
    measured: set[str] = set()

    for worksheet in worksheets:
        try:
            truth = load_worksheet(worksheet)
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            unreadable.append(f"{worksheet.name}: {error}")
            continue

        if not truth.questions:
            unreadable.append(f"{worksheet.name}: no rows filled in yet")
            continue

        document = by_name.get(truth.source_document)
        if document is None:
            unreadable.append(
                f"{worksheet.name}: names a document not in the development "
                f"corpus ({truth.source_document})"
            )
            continue

        result.documents.append(score_document(read_file(document), truth))
        measured.add(truth.source_document)

    if result.documents:
        print(result.report())

    unmeasured = sorted(set(by_name) - measured)
    if unmeasured:
        print(f"\nUNMEASURED ({len(unmeasured)} of {len(by_name)} documents):")
        for name in unmeasured:
            print(f"  {name}")

    if unreadable:
        print("\nWORKSHEETS THAT COULD NOT BE SCORED:")
        for problem in unreadable:
            print(f"  {problem}")

    return 0 if result.documents else 1


if __name__ == "__main__":
    raise SystemExit(main())
