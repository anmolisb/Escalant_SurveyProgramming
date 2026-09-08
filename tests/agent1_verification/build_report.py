"""Build the Excel verification report from comparison.json.

Five sheets, ordered the way a reader needs them: the verdict first, then the
breakdown, then the evidence, then only the failures, then the method.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORRECT, MISSED, EXTRA, MISMATCH, DECLINED = (
    "correct", "missed", "extra", "mismatch", "declined")

INK = "1F2933"
HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10, name="Calibri")
TITLE_FONT = Font(bold=True, size=15, color=INK, name="Calibri")
SUB_FONT = Font(size=10, color="5A6472", italic=True, name="Calibri")
BODY = Font(size=10, name="Calibri")
MONO = Font(size=9, name="Consolas")

FILLS = {
    CORRECT:  PatternFill("solid", fgColor="E3F2E7"),
    MISSED:   PatternFill("solid", fgColor="FBE0DC"),
    MISMATCH: PatternFill("solid", fgColor="FDF0D9"),
    EXTRA:    PatternFill("solid", fgColor="FBE0DC"),
    DECLINED: PatternFill("solid", fgColor="E6ECF5"),
}
FONTS = {
    CORRECT:  Font(size=10, color="1E5B32", bold=True, name="Calibri"),
    MISSED:   Font(size=10, color="97291A", bold=True, name="Calibri"),
    MISMATCH: Font(size=10, color="8A5A08", bold=True, name="Calibri"),
    EXTRA:    Font(size=10, color="97291A", bold=True, name="Calibri"),
    DECLINED: Font(size=10, color="2C4A7C", bold=True, name="Calibri"),
}
THIN = Side(style="thin", color="D5DAE1")
EDGE = Border(bottom=THIN, right=THIN)


def header(ws, labels, r=1):
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row=r, column=i, value=label)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(vertical="center", horizontal="left", wrap_text=True)
    ws.row_dimensions[r].height = 26
    ws.freeze_panes = ws.cell(row=r + 1, column=1)


def widths(ws, *pairs):
    for col, w in pairs:
        ws.column_dimensions[get_column_letter(col)].width = w


def manual_review_items(stem: str) -> list[dict]:
    """Everything for this document that a person still has to judge.

    Three sources, because the pipeline declines to decide in three different
    places and a reviewer needs them in one list:

      Stage 7 evaluation   a test derived from the QRE that could not be given
                           an answer without a person
      Stage 7 confirmation an interpretation decision the QRE never states
      Stage 9 graph        a graph behaviour with no independent oracle to
                           check it against

    None of these is a failure. Each is the pipeline saying it will not guess.
    The QRE's own words are carried along so the sheet can be reviewed without
    opening the source document.
    """
    out = ROOT / "out" / stem
    items: list[dict] = []

    def load(name):
        path = out / name
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return d.get("content", d) if isinstance(d, dict) else d

    ev = load("agent1_evaluation_results.json") or {}
    for t in (ev.get("results") or []):
        if t.get("status") != "UNVERIFIED":
            continue
        items.append({
            "stage": "Stage 7 — evaluation",
            "id": t.get("test_id", ""),
            "category": t.get("category", ""),
            "item": t.get("canonical_reference", "") or t.get("rule_or_question", ""),
            "question": t.get("expected", ""),
            "why": t.get("explanation", ""),
            "evidence": t.get("evidence", ""),
            "criticality": t.get("criticality", ""),
        })

    va = load("part2_validation.json") or {}
    for c in (va.get("confirmation_required") or []):
        affected = c.get("affected")
        if isinstance(affected, list):
            affected = ", ".join(str(a) for a in affected)
        items.append({
            "stage": "Stage 7 — confirmation",
            "id": ", ".join(c.get("decision_ids") or []),
            "category": "decision the QRE never states",
            "item": affected or "",
            "question": c.get("issue", ""),
            "why": c.get("why_it_matters", ""),
            "evidence": c.get("changes_downstream", ""),
            "criticality": c.get("status", ""),
        })

    gv = load("part2_graph_validation.json") or {}
    for t in (gv.get("behavioural_test_results") or []):
        if t.get("status") != "UNVERIFIED":
            continue
        items.append({
            "stage": "Stage 9 — graph behaviour",
            "id": t.get("test_id", ""),
            "category": t.get("category", ""),
            "item": t.get("rule_or_question", ""),
            "question": t.get("expected", ""),
            "why": t.get("explanation", ""),
            "evidence": t.get("evidence", ""),
            "criticality": "",
        })
    return items


def pipeline_status(stem: str) -> dict:
    """What the pipeline itself concluded, separate from the extraction check.

    Extraction coverage and pipeline readiness are different questions and a
    document can pass one while failing the other - M02 and M04 extract
    perfectly and still fail graph validation. Reporting only coverage would
    hide that.
    """
    out = ROOT / "out" / stem
    status = {"graph": "", "blockers": [], "tests": "", "approval": ""}
    gv = out / "part2_graph_validation.json"
    if gv.exists():
        d = json.loads(gv.read_text(encoding="utf-8"))
        d = d.get("content", d) if isinstance(d, dict) else d
        status["graph"] = d.get("validation_status", "")
        status["blockers"] = d.get("blockers") or []
        counts = d.get("test_counts") or {}
        if counts:
            status["tests"] = (f"{counts.get('PASS',0)}/{counts.get('total',0)} pass"
                               + (f", {counts['UNVERIFIED']} unverified"
                                  if counts.get("UNVERIFIED") else ""))
    gate = out / "agent1_stage9_gate.json"
    if gate.exists():
        d = json.loads(gate.read_text(encoding="utf-8"))
        d = d.get("content", d) if isinstance(d, dict) else d
        status["approval"] = d.get("status", "")
    return status


def stem_for(document: str) -> str:
    return document.replace(".docx", "")


def main() -> int:
    rows = json.loads((HERE / "comparison.json").read_text(encoding="utf-8"))
    docs = sorted({r["document"] for r in rows})

    wb = Workbook()

    # ---------------- 1. Summary ----------------
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "Agent 1 — QRE Extraction Verification"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = (f"Canonical output checked against ground truth read independently "
                f"from each source document · {date.today():%d %B %Y}")
    ws["A2"].font = SUB_FONT
    ws.merge_cells("A1:H1"); ws.merge_cells("A2:H2")

    header(ws, ["Document", "Tier", "Checks scored", "Correct", "Missed",
                "Mismatch", "Invented", "Coverage", "Extraction",
                "Graph validation", "Behavioural tests"], r=4)
    ws.freeze_panes = "A5"

    r = 5
    totals = defaultdict(int)
    for doc in docs:
        d = [x for x in rows if x["document"] == doc]
        c = {k: sum(1 for x in d if x["outcome"] == k)
             for k in (CORRECT, MISSED, MISMATCH, EXTRA, DECLINED)}
        scored = c[CORRECT] + c[MISSED] + c[MISMATCH] + c[EXTRA]
        pct = c[CORRECT] / scored if scored else 0
        for k, v in c.items():
            totals[k] += v
        verdict = "PASS" if pct == 1 else ("REVIEW" if pct >= .95 else "FAIL")
        stem = stem_for(doc)
        ps = pipeline_status(stem)
        tier = {"S": "Simple", "M": "Medium", "C": "Complex", "Z": "Adversarial"}.get(
            stem[0], "")
        values = [stem, tier, scored, c[CORRECT], c[MISSED], c[MISMATCH], c[EXTRA],
                  pct, verdict, ps["graph"] or "-", ps["tests"] or "-"]
        for i, v in enumerate(values, start=1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.font, cell.border = BODY, EDGE
            if i == 8:
                cell.number_format = "0.0%"
            if i == 9:
                cell.fill = FILLS[CORRECT] if verdict == "PASS" else FILLS[MISSED]
                cell.font = FONTS[CORRECT] if verdict == "PASS" else FONTS[MISSED]
            if i == 10:
                ok = str(v).startswith("READY")
                cell.fill = FILLS[CORRECT] if ok else FILLS[MISSED]
                cell.font = FONTS[CORRECT] if ok else FONTS[MISSED]
        r += 1

    scored = totals[CORRECT] + totals[MISSED] + totals[MISMATCH] + totals[EXTRA]
    tot = ["ALL DOCUMENTS", "", scored, totals[CORRECT], totals[MISSED],
           totals[MISMATCH], totals[EXTRA],
           totals[CORRECT] / scored if scored else 0,
           "PASS" if totals[CORRECT] == scored else "REVIEW", "", ""]
    for i, v in enumerate(tot, start=1):
        cell = ws.cell(row=r, column=i, value=v)
        cell.font = Font(size=10, bold=True, color=INK, name="Calibri")
        cell.border = Border(top=Side(style="medium", color="1F3A5F"))
        if i == 8:
            cell.number_format = "0.0%"
    widths(ws, (1, 38), (2, 13), (3, 13), (4, 10), (5, 9), (6, 11), (7, 10),
           (8, 11), (9, 12), (10, 18), (11, 22))

    note_row = r + 2
    ws.cell(row=note_row, column=1,
            value=("Coverage measures extraction only: does the specification contain "
                   "everything the document states and nothing more. Graph validation is a "
                   "separate question — a document can extract perfectly and still fail it, "
                   "and two do. See the Pipeline findings sheet.")).font = SUB_FONT

    # ---------------- 2. Coverage by section ----------------
    ws = wb.create_sheet("Coverage by section")
    ws["A1"] = "Coverage by section"; ws["A1"].font = TITLE_FONT
    ws["A2"] = "Where a document loses coverage, rather than one blended number."
    ws["A2"].font = SUB_FONT
    header(ws, ["Document", "Section", "Checks", "Correct", "Missed",
                "Mismatch", "Invented", "Declined", "Coverage"], r=4)
    ws.freeze_panes = "A5"
    r = 5
    for doc in docs:
        for section in sorted({x["section"] for x in rows if x["document"] == doc}):
            d = [x for x in rows if x["document"] == doc and x["section"] == section]
            c = {k: sum(1 for x in d if x["outcome"] == k)
                 for k in (CORRECT, MISSED, MISMATCH, EXTRA, DECLINED)}
            sc = c[CORRECT] + c[MISSED] + c[MISMATCH] + c[EXTRA]
            vals = [doc.replace(".docx", ""), section, sc, c[CORRECT], c[MISSED],
                    c[MISMATCH], c[EXTRA], c[DECLINED], (c[CORRECT] / sc) if sc else 0]
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.font, cell.border = BODY, EDGE
                if i == 9:
                    cell.number_format = "0.0%"
                    if sc and c[CORRECT] == sc:
                        cell.fill, cell.font = FILLS[CORRECT], FONTS[CORRECT]
                    elif sc:
                        cell.fill, cell.font = FILLS[MISSED], FONTS[MISSED]
            r += 1
    widths(ws, (1, 40), (2, 24), (3, 9), (4, 9), (5, 9), (6, 11), (7, 10), (8, 10), (9, 11))

    # ---------------- 3. Evidence ----------------
    ws = wb.create_sheet("Field-level evidence")
    ws["A1"] = "Every check performed"; ws["A1"].font = TITLE_FONT
    ws["A2"] = ("Left: what the source document states. Right: what the canonical "
                "specification contains.")
    ws["A2"].font = SUB_FONT
    header(ws, ["Document", "Section", "Item", "Field",
                "Expected (from document)", "Found (in specification)",
                "Outcome", "Note"], r=4)
    ws.freeze_panes = "A5"
    for i, x in enumerate(rows, start=5):
        vals = [x["document"].replace(".docx", ""), x["section"], x["item"], x["field"],
                str(x["expected"])[:300], str(x["found"])[:300], x["outcome"], x["note"]]
        for j, v in enumerate(vals, start=1):
            cell = ws.cell(row=i, column=j, value=v)
            cell.font, cell.border = (MONO if j in (5, 6) else BODY), EDGE
            cell.alignment = Alignment(vertical="top", wrap_text=(j in (5, 6, 8)))
            if j == 7:
                cell.fill, cell.font = FILLS[x["outcome"]], FONTS[x["outcome"]]
    ws.auto_filter.ref = f"A4:H{4 + len(rows)}"
    widths(ws, (1, 34), (2, 20), (3, 14), (4, 18), (5, 46), (6, 46), (7, 12), (8, 40))

    # ---------------- 4. Discrepancies ----------------
    bad = [x for x in rows if x["outcome"] in (MISSED, MISMATCH, EXTRA)]
    ws = wb.create_sheet("Discrepancies")
    ws["A1"] = f"Discrepancies — {len(bad)} found"; ws["A1"].font = TITLE_FONT
    ws["A2"] = ("Only the failures. Empty means the specification matched the document "
                "on every scored check.")
    ws["A2"].font = SUB_FONT
    header(ws, ["Document", "Section", "Item", "Field", "Expected", "Found",
                "Outcome", "What it means"], r=4)
    ws.freeze_panes = "A5"
    MEANING = {
        MISSED: "In the document, absent from the specification — information lost.",
        MISMATCH: "Present in both but the value differs — information altered.",
        EXTRA: "In the specification, not in the document — information invented.",
    }
    for i, x in enumerate(bad, start=5):
        vals = [x["document"].replace(".docx", ""), x["section"], x["item"], x["field"],
                str(x["expected"])[:300], str(x["found"])[:300], x["outcome"],
                x["note"] or MEANING.get(x["outcome"], "")]
        for j, v in enumerate(vals, start=1):
            cell = ws.cell(row=i, column=j, value=v)
            cell.font, cell.border = (MONO if j in (5, 6) else BODY), EDGE
            cell.alignment = Alignment(vertical="top", wrap_text=(j in (5, 6, 8)))
            if j == 7:
                cell.fill, cell.font = FILLS[x["outcome"]], FONTS[x["outcome"]]
    if not bad:
        c = ws.cell(row=5, column=1, value="No discrepancies found.")
        c.font = FONTS[CORRECT]
    widths(ws, (1, 34), (2, 20), (3, 14), (4, 18), (5, 46), (6, 46), (7, 12), (8, 52))

    # ---------------- 5. Pipeline findings ----------------
    ws = wb.create_sheet("Pipeline findings")
    ws["A1"] = "What the pipeline reported about itself"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = ("A separate question from extraction coverage. These are defects the "
                "pipeline's own validation layers found in their own output.")
    ws["A2"].font = SUB_FONT
    header(ws, ["Document", "Graph validation", "Behavioural tests",
                "Category", "Check", "Finding"], r=4)
    ws.freeze_panes = "A5"
    r = 5
    any_blocker = False
    for doc in docs:
        stem = stem_for(doc)
        ps = pipeline_status(stem)
        if not ps["blockers"]:
            vals = [stem, ps["graph"] or "-", ps["tests"] or "-", "", "",
                    "No blocking finding."]
        else:
            any_blocker = True
            vals = None
        if vals:
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.font, cell.border = BODY, EDGE
                cell.alignment = Alignment(vertical="top", wrap_text=(i == 6))
                if i == 2:
                    ok = str(v).startswith("READY")
                    cell.fill = FILLS[CORRECT] if ok else FILLS[MISSED]
                    cell.font = FONTS[CORRECT] if ok else FONTS[MISSED]
            r += 1
            continue
        for b in ps["blockers"]:
            vals = [stem, ps["graph"] or "-", ps["tests"] or "-",
                    b.get("category", ""), b.get("check", ""), b.get("finding", "")]
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.font, cell.border = BODY, EDGE
                cell.alignment = Alignment(vertical="top", wrap_text=(i == 6))
                if i == 2:
                    cell.fill, cell.font = FILLS[MISSED], FONTS[MISSED]
                if i == 6:
                    cell.font = MONO
            r += 1
    widths(ws, (1, 38), (2, 18), (3, 24), (4, 26), (5, 26), (6, 80))
    if any_blocker:
        note = ws.cell(row=r + 2, column=1, value=(
            "A blocking finding here means the graph does not faithfully represent the "
            "specification it was built from. Extraction can still be perfect: these two "
            "documents extract at 100% and fail here, which is the graph validation layer "
            "doing the job it exists for."))
        note.font = SUB_FONT

    # ---------------- Manual review ----------------
    ws = wb.create_sheet("Manual review")
    ws["A1"] = "Items awaiting a person"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = ("Not failures. Each is a point where the pipeline declined to decide "
                "rather than guess. Sign off in the two right-hand columns.")
    ws["A2"].font = SUB_FONT
    header(ws, ["Document", "Stage", "Test", "Category", "Applies to",
                "What needs deciding", "Why it could not be checked automatically",
                "Evidence from the QRE", "Reviewer verdict", "Reviewer note"], r=4)
    ws.freeze_panes = "C5"

    review_fill = PatternFill("solid", fgColor="FFF8E1")
    r = 5
    per_doc = {}
    for doc in docs:
        stem = stem_for(doc)
        items = manual_review_items(stem)
        per_doc[stem] = len(items)
        for it in items:
            vals = [stem, it["stage"], it["id"], it["category"], it["item"],
                    it["question"], it["why"], str(it["evidence"])[:400], "", ""]
            for i, v in enumerate(vals, start=1):
                cell = ws.cell(row=r, column=i, value=v)
                cell.font, cell.border = BODY, EDGE
                cell.alignment = Alignment(vertical="top", wrap_text=(i in (6, 7, 8, 10)))
                if i == 8:
                    cell.font = MONO
                if i in (9, 10):
                    cell.fill = review_fill
            r += 1
    if r == 5:
        ws.cell(row=5, column=1, value="Nothing awaiting review.").font = FONTS[CORRECT]
    ws.auto_filter.ref = f"A4:J{max(r - 1, 5)}"
    widths(ws, (1, 34), (2, 22), (3, 8), (4, 26), (5, 22), (6, 44), (7, 52),
           (8, 40), (9, 16), (10, 34))

    # ---------------- Review load per document ----------------
    ws2 = wb["Summary"]
    col = 12
    c = ws2.cell(row=4, column=col, value="Awaiting review")
    c.fill, c.font = HEAD_FILL, HEAD_FONT
    c.alignment = Alignment(vertical="center", horizontal="left", wrap_text=True)
    rr = 5
    for doc in docs:
        n = per_doc.get(stem_for(doc), 0)
        cell = ws2.cell(row=rr, column=col, value=n)
        cell.font, cell.border = BODY, EDGE
        if n:
            cell.fill = review_fill
        rr += 1
    ws2.column_dimensions[get_column_letter(col)].width = 16

    # ---------------- Method ----------------
    ws = wb.create_sheet("Method")
    ws["A1"] = "How this was verified"; ws["A1"].font = TITLE_FONT
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 104
    method = [
        ("Question asked",
         "Does the canonical specification contain everything the source document states, "
         "and nothing the document does not state?"),
        ("Ground truth",
         "Read directly from each .docx with python-docx. The extractor "
         "(tests/agent1_verification/ground_truth.py) imports no pipeline code. If it shared a parser "
         "with the system under test, agreement would follow from the shared code rather "
         "than being evidence that either reading is correct."),
        ("Two documents read by hand",
         "Z01 and Z02 defeat automated header matching honestly - Z01 heads its id column "
         "'Marker' and its options column 'Permitted replies'; Z02 shuffles column order "
         "and heads its routing table Ref / Test / Then / Go to. Widening the vocabulary "
         "until these passed would have been fitting the checker to the answer, so ground "
         "truth for both was transcribed by a person and is marked 'hand-authored' in the "
         "file. Thirteen documents are automated, two are manual; the method is recorded "
         "per document rather than presented as uniform."),
        ("An error found in this checker",
         "The first hand transcription of Z02 omitted question M1's answer scale, and the "
         "comparison duly reported three options as invented by the pipeline. The pipeline "
         "had extracted them correctly; the ground truth was wrong. It was corrected and "
         "the run repeated. Recorded here because a verification report that never finds "
         "its own errors has not been examined closely enough."),
        ("Compared in both directions",
         "Document to specification detects information LOST. Specification to document "
         "detects information INVENTED. Totals alone would pass a run that dropped one "
         "question and fabricated another."),
        ("Granularity",
         "Per item and per field, not per section. A question present but missing two of "
         "its five answer options is a partial failure; a count-only check would pass it."),
        ("What is scored",
         "Question id, wording, type, every answer option, every matrix row, every display "
         "condition, every routing rule with its condition, action and destination, every "
         "acceptance scenario, completion message, study statement and QA instruction."),
        ("Declined by design",
         "Where the pipeline deliberately refuses — a condition it cannot read without "
         "guessing — the item is recorded as 'declined', not 'missed', and excluded from "
         "coverage. Refusing is the specified behaviour: a wrong condition routes real "
         "respondents down the wrong path, an unread one only asks a person to look. The "
         "verbatim text is retained in every such case."),
        ("Normalisation",
         "Whitespace, smart quotes and dashes are normalised before comparison, and a "
         "leading answer code is stripped so '1 = Yes' matches 'Yes'. These are storage "
         "differences, not extraction defects."),
        ("Checker validated",
         "Confirmed by negative control: a question, a rule and several options were "
         "deliberately removed from one specification, a wording was corrupted and a "
         "fabricated question inserted. The check detected all five and coverage fell from "
         "100% to 94.7%. A checker that cannot fail proves nothing."),
        ("Extraction vs readiness",
         "Two separate questions, reported separately. Coverage asks whether the "
         "specification matches the document. Graph validation asks whether the graph "
         "built from that specification represents it faithfully. M02 and M04 score 100% "
         "coverage and fail graph validation - see Pipeline findings."),
        ("Known limitation",
         "Each tier shares one structure. Every S document has 10 questions and 4 rules; "
         "every M document 19 and 9; every C document 31 and 20. Thirteen documents "
         "therefore exercise three distinct layouts, not thirteen. Coverage of document "
         "STRUCTURE is narrower than the document count suggests."),
        ("Manual review sheet",
         "Lists every item the pipeline declined to decide, from three places: a test "
         "derived from the QRE that has no answer without a person, an interpretation "
         "decision the QRE never states, and a graph behaviour with no independent oracle. "
         "None is a failure - each is the pipeline refusing to guess. The QRE's own words "
         "are carried into the sheet so it can be reviewed without opening the source "
         "documents, and the two right-hand columns are for sign-off."),
        ("Reproduce",
         "python3 tests/agent1_verification/ground_truth.py  ->  python3 tests/agent1_verification/compare.py  ->  "
         "python3 tests/agent1_verification/build_report.py"),
    ]
    r = 3
    for label, text in method:
        a = ws.cell(row=r, column=1, value=label)
        a.font = Font(bold=True, size=10, color=INK, name="Calibri")
        a.alignment = Alignment(vertical="top")
        b = ws.cell(row=r, column=2, value=text)
        b.font, b.alignment = BODY, Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = max(30, 13 * (len(text) // 95 + 1))
        r += 2

    out = HERE / "Agent1_Extraction_Verification.xlsx"
    wb.save(out)
    print("written:", out)
    print(f"{len(rows)} checks · {len(docs)} documents · {len(bad)} discrepancies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
