"""Independent ground truth, read from the DOCX and nothing else.

This is one half of a two-reading comparison, so it deliberately imports no
pipeline code. Nothing from `src/` appears here: if this shared a parser with
the thing it checks, agreement between the two would be a property of the
shared code rather than evidence that either is right (CLAUDE.md §33).

It reads the document the way a person would - find the tables, read the header
row, take the cells - and records what a correct extraction must contain. It
makes no judgement about what any of it means.

    python3 tests/agent1_verification/ground_truth.py            # all S documents
    python3 tests/agent1_verification/ground_truth.py S03 S04    # named ones
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "qre-samples"
OUT = Path(__file__).resolve().parent / "ground_truth"
MANUAL = Path(__file__).resolve().parent / "manual_truth"

#: A header cell naming this role. Matched loosely because the header is the
#: document's wording, not ours - but never by substring, which is how "no"
#: once matched "Scripter notes".
ROLES = {
    "questionnaire": {
        "id": ("id", "qid", "code", "no", "number", "ref"),
        "wording": ("wording", "question", "instruction", "text", "stem"),
        "type": ("type", "format", "kind"),
        "options": ("options", "scale", "answer", "codeframe", "choices"),
        "display": ("display", "validation", "condition", "base", "logic"),
    },
    "routing": {
        "id": ("rule", "id", "ref", "no"),
        "condition": ("condition", "when", "if", "logic"),
        "action": ("action", "do", "effect"),
        "destination": ("destination", "target", "goto", "then"),
    },
    "scenarios": {
        "id": ("id", "ref", "no", "case", "test"),
        "purpose": ("purpose", "description", "scenario", "objective"),
        "inputs": ("inputs", "input", "given"),
        "outcome": ("outcome", "expected", "result"),
    },
}

#: Which table is which, decided by the header row alone.
SIGNATURES = {
    "questionnaire": ("id", "wording", "type"),
    "routing": ("id", "condition", "action"),
    "scenarios": ("id", "purpose", "outcome"),
}


def words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def role_of(header: str, roles: dict) -> str | None:
    """Which role this header cell serves, by whole-word match only."""
    cell = words(header)
    for role, names in roles.items():
        if any(n in cell for n in names):
            return role
    return None


def classify(header_cells: list[str]) -> tuple[str, dict] | tuple[None, None]:
    """Name the table from its header row, without knowing the document."""
    for kind, required in SIGNATURES.items():
        roles = ROLES[kind]
        mapping = {}
        for index, cell in enumerate(header_cells):
            role = role_of(cell, roles)
            if role and role not in mapping:
                mapping[role] = index
        if all(r in mapping for r in required):
            return kind, mapping
    return None, None


def cell(row, mapping: dict, role: str) -> str:
    index = mapping.get(role)
    if index is None or index >= len(row.cells):
        return ""
    return row.cells[index].text.strip()


def split_options(text: str) -> list[str]:
    """The answers a question offers, as the document lists them.

    Separator is whichever of ';' or ',' the cell actually uses. Any leading
    code is kept with the label, because this records what is written, not a
    reading of it.
    """
    if not text or text.strip() in {"", "-", "—", "–", "n/a", "NA"}:
        return []
    if re.match(r"^\s*(rows?|scale|cols?|columns?)\s*:", text, re.I):
        return []          # a matrix; its parts are counted separately below
    separator = ";" if ";" in text else ","
    return [p.strip() for p in text.split(separator) if p.strip()]


def matrix_parts(text: str) -> dict:
    parts = {}
    for line in re.split(r"\n|\|\|", text or ""):
        match = re.match(r"^\s*(rows?|scale|cols?|columns?)\s*:\s*(.*)$", line, re.I)
        if match:
            key = "rows" if match.group(1).lower().startswith("row") else "scale"
            parts[key] = [p.strip() for p in re.split(r"[;,]", match.group(2)) if p.strip()]
    return parts


def display_conditions(text: str) -> list[str]:
    """Every 'Show if:' line in a display cell, condition text only."""
    found = []
    for line in (text or "").split("\n"):
        match = re.match(r"^\s*show\s+if\s*:\s*(.+?)\s*$", line, re.I)
        if match:
            found.append(match.group(1))
    return found


def prose_after(doc: Document, heading_words: tuple[str, ...]) -> list[str]:
    """Non-empty paragraphs under a heading, up to the next heading."""
    lines, capturing = [], False
    for para in doc.paragraphs:
        text = para.text.strip()
        is_heading = para.style.name.startswith("Heading")
        if is_heading:
            head = words(text)
            capturing = any(w in head for w in heading_words)
            continue
        if capturing and text:
            lines.append(text)
    return lines


def read(path: Path) -> dict:
    doc = Document(path)
    truth = {
        "document": path.name,
        "questions": [],
        "routing": [],
        "scenarios": [],
        "messages": prose_after(doc, ("completion", "messages")),
        "study": prose_after(doc, ("study", "specification")),
        "programming": prose_after(doc, ("programming", "qa")),
        "quotas": prose_after(doc, ("quota", "quotas")),
    }

    for table in doc.tables:
        header = [c.text.strip() for c in table.rows[0].cells]
        kind, mapping = classify(header)
        if kind is None:
            continue
        for row in table.rows[1:]:
            if not any(c.text.strip() for c in row.cells):
                continue
            if kind == "questionnaire":
                options_cell = cell(row, mapping, "options")
                display_cell = cell(row, mapping, "display")
                truth["questions"].append({
                    "id": cell(row, mapping, "id"),
                    "wording": cell(row, mapping, "wording"),
                    "type": cell(row, mapping, "type"),
                    "options": split_options(options_cell),
                    "matrix": matrix_parts(options_cell),
                    "display_conditions": display_conditions(display_cell),
                    "display_cell": display_cell,
                })
            elif kind == "routing":
                truth["routing"].append({
                    "rule": cell(row, mapping, "id"),
                    "condition": cell(row, mapping, "condition"),
                    "action": cell(row, mapping, "action"),
                    "destination": cell(row, mapping, "destination"),
                })
            elif kind == "scenarios":
                truth["scenarios"].append({
                    "id": cell(row, mapping, "id"),
                    "purpose": cell(row, mapping, "purpose"),
                    "inputs": cell(row, mapping, "inputs"),
                    "outcome": cell(row, mapping, "outcome"),
                })
    return truth


def main(argv: list[str]) -> int:
    wanted = [a.upper() for a in argv[1:]] or ["S01", "S02", "S03", "S04", "S05"]
    OUT.mkdir(parents=True, exist_ok=True)
    for path in sorted(FIXTURES.glob("*.docx")):
        if path.name.startswith("~$"):
            continue
        if not any(path.name.upper().startswith(w) for w in wanted):
            continue
        override = MANUAL / f"{path.stem}.truth.json"
        if override.exists():
            # Some documents defeat header matching honestly - a column headed
            # "Marker" is an id to a person and to nothing else. Rather than
            # widening the vocabulary until the fixture passes, which is fitting
            # the checker to the answer, ground truth for those is read by hand
            # and carried through unchanged. Which method was used is recorded
            # in the file and reported.
            truth = json.loads(override.read_text(encoding="utf-8"))
        else:
            truth = read(path)
            truth["method"] = "automated"
        target = OUT / f"{path.stem}.truth.json"
        target.write_text(json.dumps(truth, indent=2), encoding="utf-8")
        print(
            f"{path.stem:38} questions={len(truth['questions']):3} "
            f"rules={len(truth['routing']):3} scenarios={len(truth['scenarios']):3} "
            f"messages={len(truth['messages']):3} study={len(truth['study']):3} "
            f"qa={len(truth['programming']):3}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
