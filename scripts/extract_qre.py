"""Run the QRE Reader over the development corpus and write the IR as JSON.

Extraction quality cannot be judged from test results alone - tests confirm
invariants hold, not that the reader understood the document. This writes the IR
somewhere a person can read it, and prints a summary showing what was extracted
and what was left unresolved.

Usage:
    python scripts/extract_qre.py                 # whole development corpus
    python scripts/extract_qre.py path/to.docx    # one document

Output goes to data/outputs/qre_interpretation/ (gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agents.qre_interpretation.extraction import read_file  # noqa: E402
from src.common.schemas.qre_extraction import (  # noqa: E402
    InstructionKind,
    QREExtractionIR,
)
from src.evaluation import corpus  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "data" / "outputs" / "qre_interpretation"


def summarize(ir: QREExtractionIR) -> str:
    kinds = {}
    for instruction in ir.instructions:
        kinds[instruction.kind.value] = kinds.get(instruction.kind.value, 0) + 1
    unclassified = kinds.pop(InstructionKind.UNCLASSIFIED.value, 0)

    flagged = sum(1 for u in ir.unparsed_content if u.requires_review)
    parts = [
        f"{len(ir.sections):>3} sections",
        f"{len(ir.questions):>4} questions",
        f"{len(ir.instructions):>4} instructions",
        f"{len(ir.unparsed_content):>4} unparsed ({flagged} flagged)",
        f"{len(ir.review_queue):>3} review items",
    ]
    detail = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items()))
    if unclassified:
        detail += f", unclassified={unclassified}"
    return " | ".join(parts) + ("\n      " + detail if detail else "")


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]] or corpus.development_corpus()

    for path in paths:
        if corpus.is_holdout_path(path):
            # The script refuses rather than relying on the operator to notice.
            print(f"REFUSED  {path.name}: this is a holdout document (decision 0002).")
            continue

        ir = read_file(path)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        destination = OUTPUT_DIR / f"{path.stem}.ir.json"
        destination.write_text(
            ir.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
        )

        print(f"{path.name}")
        print(f"      {summarize(ir)}")

    print(f"\nWrote IR JSON to {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
