"""Human-facing outputs.

Reviewers should never have to read JSON to sign off a test. Two artifacts:

  agent3_review.md    the coverage story, the gaps, and their reasons
  agent3_review.xlsx  every generated test, one row per step, for line-by-line
                      sign-off before anything is released to Agent 4

The workbook is a review surface, not a model: no formulas, so nothing to
recalculate and nothing that can silently drift from the JSON it came from.
"""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "Arial"
HEAD_FILL = PatternFill("solid", fgColor="10403E")     # deep petrol teal
HEAD_FONT = Font(name=FONT, size=10, bold=True, color="FFFFFF")
BODY = Font(name=FONT, size=10)
MONO = Font(name="Consolas", size=9)
WARN = Font(name=FONT, size=10, color="9C2B00", bold=True)
OK = Font(name=FONT, size=10, color="1E6B3A")
THIN = Side(style="thin", color="D9D9D9")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _sheet(wb, title, headers, widths):
    ws = wb.create_sheet(title) if wb.sheetnames != ["Sheet"] else wb.active
    ws.title = title
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.fill, c.font, c.border = HEAD_FILL, HEAD_FONT, BOX
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 28
    return ws


def _row(ws, values, fonts=None):
    r = ws.max_row + 1
    for i, v in enumerate(values, start=1):
        c = ws.cell(row=r, column=i,
                    value=(v if isinstance(v, (int, float, str)) or v is None
                           else json.dumps(v, default=str)))
        c.font = (fonts or {}).get(i, BODY)
        c.border = BOX
        c.alignment = Alignment(vertical="top", wrap_text=True)
    return r


def write_workbook(out_dir: Path, summary: dict, coverage: dict,
                   targets: list[dict], witnesses: list[dict],
                   scenarios: list[dict], tests: list[dict],
                   conformance: dict | None = None,
                   exec_report: dict | None = None,
                   exec_tests: list[dict] | None = None) -> Path:
    wb = Workbook()

    # --- Coverage vector -------------------------------------------------
    ws = _sheet(wb, "Coverage", ["Dimension", "What it measures", "Enumerated",
                                 "Covered", "Uncovered", "Logical %",
                                 "Enumeration status", "Uncovered reasons"],
                [12, 34, 12, 10, 11, 10, 20, 46])
    for code, d in sorted(coverage["coverage_vector"].items()):
        _row(ws, [code, d["name"], d["enumerated"], d["covered"], d["uncovered"],
                  d["logical_coverage_pct"], d["enumeration_status"],
                  ", ".join(f"{k}={v}" for k, v in d["reasons"].items()) or "-"],
             fonts={6: (OK if d["logical_coverage_pct"] == 100 else WARN)})
    _row(ws, [])
    _row(ws, ["FLOOR", coverage["single_figure"]["label"],
              "", "", "", coverage["single_figure"]["value_pct"],
              coverage["single_figure"]["dimension"], ""], fonts={6: WARN})
    _row(ws, ["EXECUTABLE", "Tests Agent 4 could actually run", "", "", "",
              coverage["executable_coverage_pct"], "BLOCKED",
              coverage["executable_coverage_note"]], fonts={6: WARN})

    # --- Test cases, one row per step ------------------------------------
    ws = _sheet(wb, "Test cases", ["Test ID", "Dim", "Title", "Step",
                                   "Question", "Kind", "Action", "Traces to",
                                   "Provisional semantics"],
                [16, 6, 44, 6, 11, 13, 40, 16, 24])
    for t in tests:
        for st in t["steps"]:
            _row(ws, [t["test_id"], t["dimension"], t["title"], st.get("step"),
                      st.get("question_id", ""), st.get("question_kind", ""),
                      str(st.get("value", "")), ", ".join(t["traces_to"]),
                      ", ".join(t["provisional_semantics"]) or "-"],
                 fonts={7: MONO,
                        9: (WARN if t["provisional_semantics"] else BODY)})

    # --- Assertions -------------------------------------------------------
    ws = _sheet(wb, "Assertions", ["Test ID", "Dim", "Assertion kind",
                                   "Target", "Expected", "Detail"],
                [16, 6, 26, 12, 40, 52])
    for t in tests:
        for a in t["assertions"]:
            _row(ws, [t["test_id"], t["dimension"], a.get("kind"),
                      a.get("target", ""), a.get("expected"),
                      a.get("detail", "")], fonts={5: MONO})

    # --- Uncovered ledger -------------------------------------------------
    ws = _sheet(wb, "Uncovered", ["Target ID", "Dim", "Subject", "Polarity",
                                  "Claim", "Reason", "Evidence"],
                [16, 6, 22, 16, 44, 26, 58])
    by_t = {t["target_id"]: t for t in targets}
    by_w = {w["target_id"]: w for w in witnesses}
    for sc in scenarios:
        if sc["status"] == "COVERED":
            continue
        t = by_t[sc["target_id"]]
        w = by_w.get(sc["target_id"], {})
        _row(ws, [t["target_id"], t["dimension"], t["subject"], t["polarity"],
                  t["claim"], sc["reason"] or "", w.get("evidence", "")],
             fonts={6: WARN})

    # --- Executable tests (Block C) ---------------------------------------
    if exec_tests:
        ws = _sheet(wb, "Executable steps",
                    ["Test ID", "Dim", "Title", "Step", "Action", "Field",
                     "SGQA", "Value", "Kind", "Instruction"],
                    [16, 6, 40, 6, 13, 18, 22, 12, 12, 44])
        for t in exec_tests:
            for st in t["steps"]:
                _row(ws, [t["test_id"], t["dimension"], t["title"], st["step"],
                          st["action"], st.get("field_name") or "",
                          st.get("sgqa") or "", st.get("value"),
                          st.get("value_kind") or "", st.get("human", "")],
                     fonts={6: MONO, 7: MONO, 8: MONO})

        ws = _sheet(wb, "Executable assertions",
                    ["Test ID", "Dim", "Assertion", "Field", "SGQA",
                     "Expected", "Why"],
                    [16, 6, 26, 18, 22, 40, 54])
        for t in exec_tests:
            for a in t["assertions"]:
                _row(ws, [t["test_id"], t["dimension"], a["kind"],
                          a.get("field_name") or "", a.get("sgqa") or "",
                          a.get("expected"), a.get("detail", "")],
                     fonts={4: MONO, 5: MONO, 6: MONO})

    # --- Conformance (Block A) --------------------------------------------
    if conformance:
        ws = _sheet(wb, "Conformance",
                    ["Finding", "Severity", "Subject", "Detail"],
                    [30, 12, 26, 82])
        for f in conformance["findings"]:
            _row(ws, [f["kind"], f["severity"], f["subject"], f["detail"]],
                 fonts={2: (WARN if f["severity"] == "BLOCKING" else BODY)})

    # --- Compilation refusals ---------------------------------------------
    if exec_report and exec_report.get("refusals"):
        ws = _sheet(wb, "Not executable",
                    ["Target ID", "Dim", "Title", "Reason", "What is missing"],
                    [16, 6, 44, 20, 70])
        for r in exec_report["refusals"]:
            _row(ws, [r["target_id"], r["dimension"], r["title"], r["reason"],
                      "; ".join(r["missing"])], fonts={4: WARN})

    # --- Sign-off ---------------------------------------------------------
    ws = _sheet(wb, "Sign-off", ["Item", "Value", "Reviewer note"],
                [40, 60, 40])
    for k, v in summary.items():
        if k == "coverage_vector":
            continue
        _row(ws, [k, v, ""])
    _row(ws, ["", "", ""])
    _row(ws, ["Reviewer name", "", "fill in"])
    _row(ws, ["Date", "", "fill in"])
    _row(ws, ["Decision", "", "APPROVE / REJECT / APPROVE WITH NOTES"])

    path = out_dir / "agent3_review.xlsx"
    wb.save(path)
    return path


def write_markdown(out_dir: Path, summary: dict, coverage: dict,
                   semantics: dict, replay: dict, b1: dict,
                   tests: list[dict], scenarios: list[dict],
                   targets: list[dict], conformance: dict | None = None,
                   exec_report: dict | None = None,
                   exec_tests: list[dict] | None = None) -> Path:
    cv = coverage["coverage_vector"]
    L = []
    A = L.append

    A(f"# Agent 3 test design report - {summary['survey_id']}")
    A("")
    A(f"Agent 3 v0.1. Blocks B1 to B4 implemented and run. "
      f"Blocks A and C are blocked on Agent 2's build manifest; D, E and F are "
      f"pending design.")
    A("")

    A("## Headline")
    A("")
    A(f"- **{summary['targets']} coverage targets** enumerated across nine dimensions")
    A(f"- **{summary['covered']} logically covered**, each with an independently "
      f"predicted outcome")
    A(f"- **{summary['logical_tests']} logical test cases** generated, with steps "
      f"and assertions")
    A(f"- **0 executable tests** - Block C cannot bind a canonical id to a "
      f"LimeSurvey field without Agent 2's build manifest")
    A(f"- **Coverage floor {summary['coverage_floor_pct']}%** "
      f"({summary['coverage_floor_dimension']}). Reported as a floor, never a sum "
      f"or an average")
    A(f"- **Specification replay: {summary['specification_replay']}** against the "
      f"QRE's own acceptance scenarios")
    A("")

    A("## Coverage vector")
    A("")
    A("Nine dimensions, reported side by side. They count different kinds of "
      "unit, so a total would be meaningless.")
    A("")
    A("| Dim | Measures | Enumerated | Covered | Logical % | Status | Why not covered |")
    A("|---|---|---|---|---|---|---|")
    for code, d in sorted(cv.items()):
        reasons = ", ".join(f"`{k}` x{v}" for k, v in d["reasons"].items()) or "-"
        A(f"| {code} | {d['name']} | {d['enumerated']} | {d['covered']} | "
          f"{d['logical_coverage_pct']}% | {d['enumeration_status']} | {reasons} |")
    A("")
    A(f"**Floor: {coverage['single_figure']['value_pct']}% "
      f"({coverage['single_figure']['dimension']}).** "
      f"{coverage['single_figure']['label']}")
    A("")
    A(f"**Executable coverage: {coverage['executable_coverage_pct']}%.** "
      f"{coverage['executable_coverage_note']}")
    A("")

    A("## Survey-wide semantics")
    A("")
    A("B3's interpreter cannot run without these. They are read from Agent 1's "
      "`semantics` block and decision register, never hardcoded, so a change of "
      "ruling regenerates the tests instead of requiring a rewrite.")
    A("")
    A("| Reading | Value | Origin | Status | Blocking | Agent 1 decision |")
    A("|---|---|---|---|---|---|")
    for k, v in semantics.items():
        A(f"| {k} | `{v['value']}` | {v['origin']} | {v['status']} | "
          f"{'yes' if v['blocking'] else 'no'} | "
          f"{v['decision_id'] or '-'} |")
    A("")
    prov = summary.get("semantics_provisional") or []
    if prov:
        tagged = sum(1 for t in tests if t["provisional_semantics"])
        A(f"{len(prov)} reading(s) still provisional. **{tagged} of "
          f"{len(tests)} generated tests lean on at least one of them** and are "
          f"tagged accordingly, so a change of ruling shows exactly which tests "
          f"must be regenerated.")
        A("")

    A("## Specification replay")
    A("")
    A("Agent 1's own acceptance scenarios walked through B3. If B3 disagreed "
      "with a scenario the QRE author wrote, either B3 is wrong or the QRE "
      "contradicts itself.")
    A("")
    A(f"**{replay['agreed']} agree, {replay['disagreed']} disagree, "
      f"{replay['unresolved']} unresolved, of {replay['total']}.**")
    A("")
    A("| Scenario | Purpose | Outcome | Problem |")
    A("|---|---|---|---|")
    for r in replay["results"]:
        probs = "; ".join(
            f"{c['kind']} {c.get('target','')}: {c['actual']}"
            for c in r["problem_checks"]) or "-"
        A(f"| {r['scenario_id']} | {r['purpose']} | {r['outcome']} | {probs} |")
    A("")
    A(f"_{replay['note']}_")
    A("")

    A("## Sample generated tests")
    A("")
    for t in tests[:3]:
        A(f"### `{t['test_id']}` - {t['title']}")
        A("")
        A(f"Dimension {t['dimension']}. Traces to {', '.join(t['traces_to']) or 'n/a'}.")
        A("")
        if t.get("setup"):
            A("Setup, to reach the question under test:")
            A("")
            for st in t["setup"]:
                A(f"- `{st['question_id']}` = `{st.get('value')}`")
            A("")
        A(f"Action: {t.get('action_text', '')}")
        A("")
        A("Then check:")
        A("")
        for a in t["assertions"]:
            tgt = f" `{a['target']}`" if a.get("target") else ""
            A(f"- **{a['kind']}**{tgt} = `{a.get('expected')}`")
            if a.get("detail"):
                A(f"  - {a['detail']}")
        A("")

    A("## Uncovered targets")
    A("")
    A("No target is ever silently dropped. Each carries one specific reason.")
    A("")
    by_t = {t["target_id"]: t for t in targets}
    grouped: dict[str, list] = {}
    for sc in scenarios:
        if sc["status"] == "COVERED":
            continue
        grouped.setdefault(sc["reason"] or "UNKNOWN", []).append(
            by_t[sc["target_id"]])
    for reason, items in sorted(grouped.items()):
        A(f"**`{reason}`** - {len(items)} target(s)")
        A("")
        for t in items[:12]:
            A(f"- {t['dimension']} {t['subject']} / {t['polarity']}")
        if len(items) > 12:
            A(f"- ... and {len(items) - 12} more")
        A("")

    if conformance:
        A("## Block A - implementation conformance")
        A("")
        A(f"Derived from the emitted `.lss` (sha `{conformance['lss_sha256'][:12]}`), "
          f"not from a self-reported manifest.")
        A("")
        A(f"- Questions specified: {conformance['questions_specified']}")
        A(f"- Questions built: {conformance['questions_built']}")
        A(f"- Options bound to a physical identifier: {conformance['options_bound']}")
        A(f"- Verdict: **{conformance['verdict']}** "
          f"({conformance['blocking_count']} blocking)")
        A("")
        groups: dict[str, list] = {}
        for f in conformance["findings"]:
            groups.setdefault(f["kind"], []).append(f)
        A("| Finding | Severity | Count | Subjects |")
        A("|---|---|---|---|")
        for kind, items in sorted(groups.items()):
            subs = ", ".join(i["subject"] for i in items[:6])
            if len(items) > 6:
                subs += f", +{len(items) - 6} more"
            A(f"| {kind} | {items[0]['severity']} | {len(items)} | {subs} |")
        A("")
        for kind, items in sorted(groups.items()):
            if items[0]["severity"] == "BLOCKING" or kind.startswith("TERMINATION"):
                A(f"**{kind}** - {items[0]['detail']}")
                A("")

    if exec_report:
        A("## Block C - executable compilation")
        A("")
        A(f"- Logically covered: {exec_report['logically_covered']}")
        A(f"- **Compiled to executable tests: {exec_report['compiled_executable']}**")
        A(f"- Refused rather than guessed: {exec_report['refused']}")
        A(f"- Executable coverage: **{exec_report['executable_coverage_pct']}%**")
        A("")
        if exec_report.get("refusals"):
            byr: dict[str, list] = {}
            for r in exec_report["refusals"]:
                byr.setdefault(r["reason"], []).append(r)
            A("| Refusal reason | Count | Example |")
            A("|---|---|---|")
            for reason, items in sorted(byr.items()):
                A(f"| `{reason}` | {len(items)} | {items[0]['missing'][0][:110]} |")
            A("")

    if exec_tests:
        A("## Sample executable test")
        A("")
        t = exec_tests[0]
        A(f"### `{t['test_id']}` - {t['title']}")
        A("")
        A(f"Survey id {t['sid']}. Dimension {t['dimension']}. "
          f"Traces to {', '.join(t['traces_to']) or 'n/a'}.")
        A("")
        A("| Step | Action | Field | SGQA | Value |")
        A("|---|---|---|---|---|")
        for st in t["steps"]:
            A(f"| {st['step']} | {st.get('action', '')} | "
              f"`{st.get('field_name') or ''}` | `{st.get('sgqa') or ''}` | "
              f"`{st.get('value') if st.get('value') is not None else ''}` |")
        A("")
        A("Assertions:")
        A("")
        for a in t["assertions"]:
            fn = f" on `{a['field_name']}`" if a.get("field_name") else ""
            A(f"- **{a['kind']}**{fn} = `{a['expected']}`")
            if a.get("detail"):
                A(f"  - {a['detail']}")
        A("")

    A("## What v0.1 does not do")
    A("")
    A("- **Block A** (implementation conformance): not implemented. Needs "
      "Agent 2's build manifest.")
    A("- **Block C** (executable compilation): logical half only. The physical "
      "half needs the manifest.")
    A("- **Blocks D, E, F**: pending design.")
    A("- **Z3**: not wired. Arithmetic and question-to-question conditions are "
      "reported `BOUND_REACHED`, never guessed.")
    A("- **B4's blind spot**: it compares, it does not re-derive. Two "
      "independently-wrong components that agree would pass. Mitigated by B2/B3 "
      "structural independence, not by a check in B4.")
    A("")

    path = out_dir / "agent3_review.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
