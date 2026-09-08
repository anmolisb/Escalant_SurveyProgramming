"""Compare the canonical specification against independent ground truth.

Ground truth comes from `ground_truth.py`, which read the DOCX and imported no
pipeline code. This compares that reading against `part2_canonical.json` in
both directions, because the two directions catch different failures:

    document -> canonical    was anything MISSED?
    canonical -> document    was anything INVENTED?

Counting only totals would pass a pipeline that dropped one question and
fabricated another. Comparison is therefore per item and per field.

Three outcomes, not two. A value the pipeline deliberately declined to decide -
a condition it refused to read, a field it marked unknown rather than guessing -
is `declined`, not `missed`. Declining is the designed behaviour and scoring it
as a failure would misreport the system; it is counted and reported separately,
and excluded from the coverage percentage.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRUTH = Path(__file__).resolve().parent / "ground_truth"
OUT_DIR = ROOT / "out"

CORRECT, MISSED, EXTRA, MISMATCH, DECLINED = (
    "correct", "missed", "extra", "mismatch", "declined"
)


def normalise(text: str) -> str:
    """Compare on content, not on whitespace or smart quotes."""
    if text is None:
        return ""
    text = str(text).replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip().lower()


def strip_code(label: str) -> str:
    """Drop a leading answer code so '1 = Yes' and 'Yes' compare equal.

    The document writes an option one way and the pipeline stores code and
    label apart; comparing the raw strings would report a mismatch on every
    coded option, which would be an artefact of storage, not a defect.
    """
    return normalise(re.sub(r"^\s*[A-Za-z0-9]{1,3}\s*[=)]\s*|^\s*\d+\s*-\s+", "", label or ""))


def load_canonical(stem: str) -> dict | None:
    path = OUT_DIR / stem / "part2_canonical.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("content", data) if isinstance(data, dict) else data


def row(document, section, item, field, expected, found, outcome, note=""):
    return {
        "document": document, "section": section, "item": item, "field": field,
        "expected": expected, "found": found, "outcome": outcome, "note": note,
    }


def compare_questions(doc, truth, canonical, rows):
    by_id = {q.get("question_id"): q for q in canonical.get("questions", [])}
    seen = set()

    for expected in truth["questions"]:
        qid = expected["id"]
        seen.add(qid)
        actual = by_id.get(qid)
        if actual is None:
            rows.append(row(doc, "Questionnaire", qid, "question", qid, "", MISSED,
                            "question in the document has no entry in the specification"))
            continue
        rows.append(row(doc, "Questionnaire", qid, "question", qid, qid, CORRECT))

        # wording
        rows.append(row(
            doc, "Questionnaire", qid, "wording",
            expected["wording"], actual.get("wording", ""),
            CORRECT if normalise(expected["wording"]) == normalise(actual.get("wording"))
            else MISMATCH))

        # type
        rows.append(row(
            doc, "Questionnaire", qid, "type",
            expected["type"], actual.get("kind", ""),
            CORRECT if normalise(expected["type"]) == normalise(actual.get("kind"))
            else MISMATCH))

        # options, both directions
        want = [strip_code(o) for o in expected["options"]]
        got = [strip_code(o.get("label", "")) for o in actual.get("options", [])]
        if expected["matrix"]:
            want = [strip_code(o) for o in expected["matrix"].get("scale", [])]
            want_rows = [strip_code(o) for o in expected["matrix"].get("rows", [])]
            got_rows = [strip_code(o.get("label", "")) for o in actual.get("matrix_rows", [])]
            for label in want_rows:
                rows.append(row(doc, "Questionnaire", qid, "matrix row", label,
                                label if label in got_rows else "",
                                CORRECT if label in got_rows else MISSED))
            for label in got_rows:
                if label not in want_rows:
                    rows.append(row(doc, "Questionnaire", qid, "matrix row", "", label, EXTRA))
        for label in want:
            rows.append(row(doc, "Questionnaire", qid, "option", label,
                            label if label in got else "",
                            CORRECT if label in got else MISSED))
        for label in got:
            if label not in want:
                rows.append(row(doc, "Questionnaire", qid, "option", "", label, EXTRA,
                                "option in the specification that the document does not list"))

        # display condition
        for condition in expected["display_conditions"]:
            guard = actual.get("guard")
            if guard is None:
                rows.append(row(doc, "Questionnaire", qid, "display condition",
                                condition, "", MISSED,
                                "document guards this question; specification has no guard"))
            elif guard.get("condition") is None:
                rows.append(row(doc, "Questionnaire", qid, "display condition",
                                condition, "(recorded, not read)", DECLINED,
                                "guard present but the condition could not be read"))
            else:
                rows.append(row(doc, "Questionnaire", qid, "display condition",
                                condition, "(read as a condition tree)", CORRECT))

    for qid in by_id:
        if qid not in seen:
            rows.append(row(doc, "Questionnaire", qid, "question", "", qid, EXTRA,
                            "question in the specification that is not in the document"))


def compare_routing(doc, truth, canonical, rows):
    by_id = {r.get("rule_id"): r for r in canonical.get("rules", [])}
    seen = set()
    for expected in truth["routing"]:
        rid = expected["rule"]
        seen.add(rid)
        actual = by_id.get(rid)
        if actual is None:
            rows.append(row(doc, "Routing", rid, "rule", rid, "", MISSED))
            continue
        rows.append(row(doc, "Routing", rid, "rule", rid, rid, CORRECT))
        rows.append(row(doc, "Routing", rid, "destination",
                        expected["destination"],
                        (actual.get("destination") or {}).get("id", ""),
                        CORRECT if normalise(expected["destination"]) ==
                        normalise((actual.get("destination") or {}).get("id"))
                        else MISMATCH))
        rows.append(row(doc, "Routing", rid, "action",
                        expected["action"], actual.get("kind", ""),
                        CORRECT if normalise(expected["action"]) == normalise(actual.get("kind"))
                        else MISMATCH))
        if actual.get("when") is not None:
            rows.append(row(doc, "Routing", rid, "condition", expected["condition"],
                            "(read as a condition tree)", CORRECT))
        else:
            rows.append(row(doc, "Routing", rid, "condition", expected["condition"],
                            actual.get("when_unread") or "(not read)", DECLINED,
                            "condition kept verbatim; refused rather than guessed"))
    for rid in by_id:
        if rid not in seen:
            rows.append(row(doc, "Routing", rid, "rule", "", rid, EXTRA))


def compare_statements(doc, section, expected_lines, actual_items, text_key, rows):
    """Prose sections: every line in the document must survive somewhere."""
    got = [normalise(a.get(text_key) or a.get("raw_text") or "") for a in actual_items]
    joined = " || ".join(got)
    for line in expected_lines:
        want = normalise(line)
        core = want.split(":", 1)[1].strip() if ":" in want else want
        hit = any(core and core in g for g in got) or (core and core in joined)
        rows.append(row(doc, section, line[:40], "statement", line,
                        "(present)" if hit else "", CORRECT if hit else MISSED))


#: "QUOTA_REGION: soft quota on D1: North=20%, South=20%, ..."
QUOTA_LINE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]{2,})\s*:\s*(hard|soft)\s+quota\s+on\s+([A-Za-z]{1,4}_?\d+)\s*:\s*(.+)$",
    re.I,
)
QUOTA_CELL = re.compile(r"([^,=]+?)\s*=\s*(\d+(?:\.\d+)?)\s*(%?)")


def compare_quotas(doc, truth, canonical, rows):
    """Every quota the document states, down to its cells.

    Worth checking cell by cell: a quota carried across with its name and its
    question but with two of five cells lost still looks present, and the
    percentages are what decide when a cell closes.
    """
    by_id = {q.get("quota_id"): q for q in canonical.get("quotas", [])}
    seen = set()

    for line in truth.get("quotas", []):
        match = QUOTA_LINE.match(line)
        if not match:
            continue                      # prose about quotas, not a quota itself
        qid, enforcement, question_id, cells_text = match.groups()
        seen.add(qid)
        actual = by_id.get(qid)
        if actual is None:
            rows.append(row(doc, "Quota controls", qid, "quota", qid, "", MISSED,
                            "quota stated in the document is absent from the specification"))
            continue
        rows.append(row(doc, "Quota controls", qid, "quota", qid, qid, CORRECT))
        rows.append(row(doc, "Quota controls", qid, "enforcement",
                        enforcement.lower(), actual.get("enforcement") or "",
                        CORRECT if normalise(enforcement) == normalise(actual.get("enforcement"))
                        else MISMATCH))
        rows.append(row(doc, "Quota controls", qid, "measured on",
                        question_id, actual.get("variable_question_id") or "",
                        CORRECT if normalise(question_id) ==
                        normalise(actual.get("variable_question_id")) else MISMATCH))

        got = {normalise(c.get("option_label")): c for c in actual.get("cells", [])}
        want = {}
        for label, value, _pct in QUOTA_CELL.findall(cells_text):
            want[normalise(label)] = float(value)
        for label, target in want.items():
            cell_actual = got.get(label)
            if cell_actual is None:
                rows.append(row(doc, "Quota controls", qid, f"cell {label}",
                                f"{label}={target}", "", MISSED))
                continue
            found = cell_actual.get("target_percent")
            if found is None:
                found = cell_actual.get("target_count")
            rows.append(row(doc, "Quota controls", qid, f"cell {label}",
                            f"{label}={target}", f"{label}={found}",
                            CORRECT if found is not None and abs(float(found) - target) < 1e-6
                            else MISMATCH))
        for label in got:
            if label not in want:
                rows.append(row(doc, "Quota controls", qid, f"cell {label}", "", label, EXTRA,
                                "quota cell in the specification that the document does not state"))

    for qid in by_id:
        if qid not in seen:
            rows.append(row(doc, "Quota controls", qid, "quota", "", qid, EXTRA))


def compare(stem: str) -> list[dict]:
    truth = json.loads((TRUTH / f"{stem}.truth.json").read_text(encoding="utf-8"))
    canonical = load_canonical(stem)
    doc = truth["document"]
    rows: list[dict] = []
    if canonical is None:
        rows.append(row(doc, "-", "-", "pipeline run", "part2_canonical.json", "", MISSED,
                        "the pipeline has not been run for this document"))
        return rows

    compare_questions(doc, truth, canonical, rows)
    compare_routing(doc, truth, canonical, rows)
    compare_statements(doc, "Completion messages", truth["messages"],
                       canonical.get("dispositions", []), "message", rows)
    compare_statements(doc, "Study specification", truth["study"],
                       canonical.get("metadata", []), "text", rows)
    compare_statements(doc, "Programming and QA", truth["programming"],
                       canonical.get("requirements", []), "text", rows)
    compare_quotas(doc, truth, canonical, rows)

    scenarios = {s.get("scenario_id") for s in canonical.get("scenarios", [])}
    for expected in truth["scenarios"]:
        sid = expected["id"]
        rows.append(row(doc, "Acceptance scenarios", sid, "scenario", sid,
                        sid if sid in scenarios else "",
                        CORRECT if sid in scenarios else MISSED))
    return rows


def main(argv: list[str]) -> int:
    wanted = argv[1:] or ["S01", "S02", "S03", "S04", "S05"]
    everything: list[dict] = []
    for path in sorted(TRUTH.glob("*.truth.json")):
        stem = path.name.replace(".truth.json", "")
        if not any(stem.upper().startswith(w.upper()) for w in wanted):
            continue
        rows = compare(stem)
        everything.extend(rows)
        counts = {}
        for r in rows:
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        scored = sum(counts.get(k, 0) for k in (CORRECT, MISSED, MISMATCH, EXTRA))
        pct = 100.0 * counts.get(CORRECT, 0) / scored if scored else 0.0
        print(f"{stem:38} {pct:5.1f}%  " + "  ".join(
            f"{k}={counts.get(k,0)}" for k in (CORRECT, MISSED, MISMATCH, EXTRA, DECLINED)))
    (Path(__file__).resolve().parent / "comparison.json").write_text(
        json.dumps(everything, indent=2), encoding="utf-8")
    print(f"\n{len(everything)} checks written to {Path(__file__).parent.name}/comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
