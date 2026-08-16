"""Reading and writing hand-coded ground-truth worksheets.

CSV in, validated models out. The loader is strict about structure and silent
about content: it will reject a malformed file, but it never corrects, fills or
second-guesses what a human wrote. A loader that tidies ground truth is editing
the measuring instrument.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.common.schemas.ground_truth import (
    INSTRUCTION_SEPARATOR,
    OPTION_SEPARATOR,
    CodingPass,
    GroundTruthDocument,
    GroundTruthOption,
    GroundTruthQuestion,
)
from src.evaluation.corpus import REPO_ROOT

GROUND_TRUTH_DIR = REPO_ROOT / "data" / "ground_truth" / "Synthetic"

# Header lines carry the document identity. They are comments so that the file
# still opens cleanly as a spreadsheet, and so that identity travels with the
# data rather than living only in the filename.
META_PREFIX = "#"
COLUMNS = [
    "qid",
    "question_text",
    "question_type",
    "options",
    "option_codes",
    "instructions",
    "section",
    "notes",
]


class GroundTruthFormatError(ValueError):
    """Raised when a worksheet cannot be read as ground truth."""


def worksheet_path(document_name: str) -> Path:
    return GROUND_TRUTH_DIR / f"{Path(document_name).stem}.gt.csv"


def write_worksheet(
    document_name: str, sha256: str, path: Path | None = None
) -> Path:
    """Write a BLANK worksheet for a document.

    Deliberately empty. Decision 0003: pre-filling the reader's answers would
    turn derivation into verification, and a reviewer shown a plausible answer
    agrees with it. The blank grid is the whole point, not an unfinished
    feature.
    """
    path = path or worksheet_path(document_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"{META_PREFIX} source_document: {document_name}\n")
        handle.write(f"{META_PREFIX} source_sha256: {sha256}\n")
        handle.write(f"{META_PREFIX} coded_by: \n")
        handle.write(f"{META_PREFIX} coding_pass: first\n")
        handle.write(
            f"{META_PREFIX} Fill one row per question the QRE asks. "
            f"Separate options with '{OPTION_SEPARATOR}' and instructions with "
            f"'{INSTRUCTION_SEPARATOR}'. Leave a field blank if the QRE does not "
            "state it - do not infer. Blank is a finding.\n"
        )
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
    return path


def _split(value: str, separator: str) -> list[str]:
    return [part.strip() for part in (value or "").split(separator) if part.strip()]


def load_worksheet(path: Path) -> GroundTruthDocument:
    """Load and validate a filled worksheet."""
    text = path.read_text(encoding="utf-8-sig")
    meta: dict[str, str] = {}
    data_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith(META_PREFIX):
            key, _, value = line[len(META_PREFIX) :].partition(":")
            key = key.strip()
            if key in {"source_document", "source_sha256", "coded_by", "coding_pass"}:
                meta[key] = value.strip()
        else:
            data_lines.append(line)

    missing = {"source_document", "source_sha256"} - set(meta)
    if missing:
        raise GroundTruthFormatError(
            f"{path.name}: missing header field(s) {sorted(missing)}."
        )
    if not meta.get("coded_by"):
        raise GroundTruthFormatError(
            f"{path.name}: 'coded_by' is empty. Ground truth must record who "
            "produced it - independence cannot be audited otherwise "
            "(decision 0003)."
        )

    rows = list(csv.DictReader(data_lines))
    if rows and set(COLUMNS) - set(rows[0].keys()):
        raise GroundTruthFormatError(
            f"{path.name}: expected columns {COLUMNS}, got {list(rows[0].keys())}."
        )

    questions: list[GroundTruthQuestion] = []
    for number, row in enumerate(rows, start=2):
        qid = (row.get("qid") or "").strip()
        if not qid:
            continue  # Blank rows are unfilled worksheet space, not questions.

        labels = _split(row.get("options", ""), OPTION_SEPARATOR)
        codes = _split(row.get("option_codes", ""), OPTION_SEPARATOR)
        if codes and len(codes) != len(labels):
            raise GroundTruthFormatError(
                f"{path.name} row {number} ({qid}): {len(labels)} options but "
                f"{len(codes)} codes. Leave option_codes blank if the QRE gives "
                "no codes; do not pad it."
            )

        questions.append(
            GroundTruthQuestion(
                qid=qid,
                text=(row.get("question_text") or "").strip() or None,
                question_type=(row.get("question_type") or "").strip() or None,
                options=[
                    GroundTruthOption(
                        label=label, code=codes[i] if codes else None
                    )
                    for i, label in enumerate(labels)
                ],
                instructions=_split(
                    row.get("instructions", ""), INSTRUCTION_SEPARATOR
                ),
                section=(row.get("section") or "").strip() or None,
                notes=(row.get("notes") or "").strip() or None,
            )
        )

    duplicates = [q for q in {x.qid for x in questions} if
                  sum(1 for y in questions if y.qid == q) > 1]
    if duplicates:
        raise GroundTruthFormatError(
            f"{path.name}: duplicate question ids {sorted(duplicates)}."
        )

    return GroundTruthDocument(
        source_document=meta["source_document"],
        source_sha256=meta["source_sha256"],
        coded_by=meta["coded_by"],
        coding_pass=CodingPass(meta.get("coding_pass") or "first"),
        questions=questions,
    )


def available_ground_truth() -> list[Path]:
    """Filled worksheets present in the repository."""
    if not GROUND_TRUTH_DIR.is_dir():
        return []
    return sorted(GROUND_TRUTH_DIR.glob("*.gt.csv"))
