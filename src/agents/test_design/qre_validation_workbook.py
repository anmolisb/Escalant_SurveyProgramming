"""A flat, filterable list of test cases. One row per test.

Only rows that are an actual test appear here: something Agent 4 has to run.
Rows with no test id are left out, because a reviewer working through this
sheet wants a numbered list of runs, not a mix of runs and notes.

The two kinds of row that are excluded are still produced by the pipeline and
still recorded, just elsewhere:

  Direct checks   question exists, right type, right options, right compulsory
                  setting. Verified by comparing the built survey against the
                  questionnaire, so no run is involved. They live in
                  agent3_conformance.json.
  No run needed   a question with no conditional display, no answer rule of its
                  own, and no routing rule depending on it. Nothing a
                  respondent could do would reveal a fault, so there is nothing
                  to run. Recorded in agent3_targets.json.

Set TESTS_ONLY to False to bring both back into the sheet as extra rows.


No banners, no merged cells, no colour coding. Question context is repeated on
every row rather than carried by a heading, so the sheet can be sorted and
filtered without falling apart, and so any single row makes sense read on its
own.

Rows are ordered by the questionnaire's own question order, so reading top to
bottom is the same walk as reading the QRE.

The "Row type" column separates three things a reviewer needs to tell apart:
  Test          something Agent 4 has to run, because a respondent must act
  Direct check  verified by comparing the QRE to the built survey, no run needed
  Not tested    a behaviour we could not test, with the reason
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from .a_implementation import ImplementationSnapshot
from .models import COVERED, CoverageTarget, VerifiedScenario
from .spec import CanonicalSpec

# Only emit rows that are a test. See the module docstring for where the other
# two kinds of check are recorded.
TESTS_ONLY = True

COLUMNS = [
    ("Test no.", 8),
    ("Question", 10),
    ("QRE line (search for this in the Word file)", 58),
    ("Row type", 13),
    ("Test ID", 15),
    ("What this test is for", 50),
    ("Setup: answers needed only to reach this question", 40),
    ("What the bot does", 44),
    ("Expected result", 62),
    ("Kind of behaviour", 24),
    ("Runnable", 10),
]

# The QRE line already contains the question wording, so a separate wording
# column just repeated it. Dropped.

HEADER = Font(name="Calibri", size=11, bold=True)
CELL = Font(name="Calibri", size=11)
TOPWRAP = Alignment(vertical="top", wrap_text=True)
TOP = Alignment(vertical="top")

KIND = {
    "D1": "Shows / hides correctly",
    "D2": "Survey ends in the right place",
    "D3": "Answer rule accepts or rejects",
    "D4": "Blank answer is blocked",
    "D5": "Options carried forward",
    "D6": "Wording carried forward",
    "D7": "Shuffled options",
    "D8": "Quota accepts or turns away",
    "D9": "Two behaviours together",
}

POL = {
    "shown": "should appear",
    "hidden": "should NOT appear",
    "skip_fired": "the jump should happen",
    "skip_not_fired": "the jump should not happen",
    "reachable": "should be reachable",
    "satisfied": "a valid answer should be accepted",
    "violated": "an invalid answer should be rejected",
    "enforced": "leaving it blank should be blocked",
    "not_enforced": "leaving it blank should be allowed",
    "restricted": "the option list should be narrowed",
    "rendered": "the earlier answer should appear in the wording",
    "advances": "answering it should move the respondent on",
    "presents_all_items": "every option should appear exactly once",
    "completeness": "every option should appear exactly once",
    "order_varies": "the order should differ between respondents",
    "anchors_held": "the pinned options should stay in place",
    "available": "a respondent should be accepted",
    "full": "a respondent should be turned away",
    "combined": "both should hold at once",
}

WHY_NOT = {
    "QUOTA_SIZE_UNDEFINED":
        "The QRE gives quota targets as percentages but never a total sample "
        "size, so we cannot work out when a quota is full. Client to confirm.",
    "RANDOMIZATION_ANCHOR_UNDEFINED":
        "The QRE says to shuffle but never says which options stay pinned, so "
        "there is no definite order to check. Client to confirm.",
    "BOUND_REACHED":
        "The condition involves arithmetic, or compares one question's answer "
        "against another's. We stop rather than guess. Needs a maths solver.",
    "INFEASIBLE":
        "Proven impossible: triggering it would need an option to be both "
        "selected and not selected. Nothing to fix.",
    "UNVERIFIABLE":
        "Nothing a respondent could see would demonstrate it. You cannot prove "
        "the absence of an error message. Nothing to fix.",
    "UNRESOLVED_DECISION": "Waiting on a project decision the QRE left open.",
    "UNSUPPORTED": "The survey tool cannot express this.",
    "NOT_IN_IMPLEMENTATION":
        "Specified in the QRE but missing from the built survey.",
}

SUB_ORDER = {
    ("D1", "advances"): 0,
    ("D1", "shown"): 1, ("D1", "hidden"): 2,
    ("D1", "skip_fired"): 3, ("D1", "skip_not_fired"): 4,
    ("D3", "satisfied"): 5, ("D3", "violated"): 6,
    ("D4", "enforced"): 7, ("D4", "not_enforced"): 7,
    ("D5", "restricted"): 8, ("D6", "rendered"): 9,
    ("D7", "presents_all_items"): 10,
    ("D8", "available"): 11, ("D8", "full"): 12,
    ("D9", "combined"): 13, ("D2", "reachable"): 14,
}

TYPE_NAME = {"L": "single choice", "M": "multi select", "T": "free text",
             "S": "free text", "F": "matrix", "K": "constant sum"}

CHECK = {
    "field_present": "{q} IS shown on the page",
    "field_absent": "{q} is NOT shown on the page",
    "question_visible": "{q} IS shown on the page",
    "question_absent": "{q} is NOT shown on the page",
    "respondent_continues": "the respondent carries on into the survey rather "
                            "than being screened out or finished",
    "not_on_end_page": "the respondent carries on into the survey rather than "
                       "being screened out or finished",
    "next_question_is": "the next question shown is {v}",
    "next_field_present": "the next question shown is {v}",
    "page_advances": "the survey ACCEPTS the answer and moves to the next page",
    "answer_accepted": "the survey ACCEPTS the answer and moves to the next page",
    "page_does_not_advance": "the survey REFUSES to move on; the same page "
                             "reappears",
    "answer_rejected": "the survey REFUSES to move on; the same page reappears",
    "error_shown_on_question": "an error message is shown against {q}",
    "survey_completed": "the respondent reaches the normal thank-you page",
    "group_suppressed": "none of the main-section questions appear at all",
    "end_page_message": "the final page shows: {v}",
    "end_page_message_non_discriminating":
        "the final page shows: {v}   [note: other screen-outs show identical "
        "wording, so this proves a screen-out happened, not which one]",
    "not_sent_to_quota_full": "the respondent is allowed to continue, not sent "
                              "to the quota-full ending",
    "question_text_contains": "{q}'s wording includes the words: {v}",
    "options_rendered_equals": "{q} offers exactly these options and no others: {v}",
    "rendered_option_count": "{q} shows exactly {v} options, none missing and "
                             "none repeated",
    "rendered_option_labels": "the options shown at {q} are exactly: {v}",
    "rendered_order_varies": "the order the options appear in at {q} is NOT "
                             "identical on every run",
    "not_sent_to_quota_full": "the respondent is allowed to continue, not sent "
                              "to the quota-full ending",
}


def _rule_in_words(q) -> str:
    """The QRE's validation rule, spelled out rather than named."""
    v = q.validation.raw
    parts = []
    if v.get("min_selections") is not None:
        n = v["min_selections"]
        parts.append(f"at least {n} option{'s' if n != 1 else ''} must be selected")
    if v.get("min_length") is not None:
        parts.append(f"the answer must be at least {v['min_length']} characters")
    if v.get("max_length") is not None:
        parts.append(f"the answer must be at most {v['max_length']} characters")
    if v.get("min_value") is not None:
        parts.append(f"the number must be at least {v['min_value']}")
    if v.get("max_value") is not None:
        parts.append(f"the number must be at most {v['max_value']}")
    if v.get("sum_to") is not None:
        parts.append(f"the numbers entered must add up to exactly {v['sum_to']}")
    if v.get("require_each_row"):
        parts.append("every row must be answered")
    if v.get("exclusive_option_label") or v.get("exclusive_option_id"):
        label = v.get("exclusive_option_label") or v.get("exclusive_option_id")
        parts.append(f"\u201c{label}\u201d cannot be chosen alongside anything else")
    return "; ".join(parts) or ", ".join(q.validation.constraints)


def _proves(spec: CanonicalSpec, t: CoverageTarget) -> str:
    pol = POL.get(t.polarity, t.polarity)
    if t.dimension == "D1" and t.polarity == "advances":
        return (f"Prove the survey flows correctly at {t.subject}: answer it "
                f"normally and the respondent should move on to whatever the "
                f"questionnaire says comes next, not stop or jump elsewhere")
    if t.dimension == "D1" and t.polarity in ("shown", "hidden"):
        q = spec.question(t.subject)
        cond = q.guard.render() if (q and q.guard) else ""
        if t.polarity == "shown":
            return (f"Prove {t.subject} DOES appear when its condition is met. "
                    f"The QRE says show it if: {cond}")
        return (f"Prove {t.subject} does NOT appear when its condition is not "
                f"met. The QRE says show it if: {cond}")
    if t.dimension == "D1":
        rid = t.subject.split(":")[0]
        rule = spec.rule(rid)
        cond = rule.when.render() if (rule and rule.when) else ""
        return (f"Rule {rid}: {pol}. Jump to "
                f"{rule.destination_id if rule else '?'} when {cond}")
    if t.dimension == "D2":
        ending, _, named_rule = t.subject.partition("<-")
        d = spec.disposition(ending)
        if d and d.kind == "complete" and not named_rule:
            return ("Prove the survey finishes normally for a respondent who "
                    "answers everything and triggers no screen-out")
        rule = spec.rule(named_rule) if named_rule else None
        cond = rule.when.render() if (rule and rule.when) else ""
        where = rule.evaluation_point if rule else None
        msg = (d.message or "")[:70] if d else ""
        siblings = [r.id for r in spec.rules
                    if r.destination_id == ending and r.id != named_rule]
        extra = (f" Note that {', '.join(siblings)} also lead to {ending}; each "
                 f"route has its own test, so a failure here points at "
                 f"{named_rule} specifically." if siblings else "")
        return (f"Prove {named_rule or 'the routing'} sends the respondent to "
                f"{ending}: when {cond}, checked at {where}. They should then "
                f"see \u201c{msg}\u201d.{extra}")
    if t.dimension == "D3":
        q = spec.question(t.subject)
        if q is not None:
            rule = _rule_in_words(q)
            if t.polarity == "satisfied":
                return (f"Prove {t.subject} ACCEPTS an answer that obeys its "
                        f"rule. The QRE's rule is: {rule}")
            return (f"Prove {t.subject} REJECTS an answer that breaks its rule. "
                    f"The QRE's rule is: {rule}")
        rule = spec.rule(t.subject)
        cond = rule.when.render() if (rule and rule.when) else ""
        verb = ("does NOT fire" if t.polarity == "satisfied" else "DOES fire")
        return f"Prove reject rule {t.subject} {verb}. The rule is: {cond}"
    if t.dimension == "D4":
        if t.polarity == "not_enforced":
            return (f"Prove {t.subject} lets the respondent through with no "
                    f"answer, because the questionnaire marks it optional")
        q = spec.question(t.subject)
        kind = q.kind if q else "?"
        return (f"Prove {t.subject} refuses to let the respondent past when it "
                f"is left blank. The questionnaire marks it compulsory, and it "
                f"is a {kind} question")
    if t.dimension in ("D5", "D6"):
        src, dst = t.subject.split("->")
        what = "option list" if t.dimension == "D5" else "wording"
        return f"{dst}'s {what} comes from {src}'s answer: {pol}"
    if t.dimension == "D7":
        if t.polarity == "completeness":
            q = spec.question(t.subject)
            n = len(q.options) if q else 0
            return (f"Prove {t.subject} still shows all {n} of its options when "
                    f"shuffled, with none dropped and none duplicated")
        if t.polarity == "order_varies":
            return (f"Prove {t.subject} is actually shuffled: the option order "
                    f"must differ between respondents. If it never changes, "
                    f"shuffling was not switched on")
        return (f"Prove {t.subject} keeps its pinned options in place while the "
                f"rest shuffle")
    if t.dimension == "D8":
        quota_id, cell_oid = t.subject.split(":")
        quota = next((x for x in spec.quotas if x.id == quota_id), None)
        cell = next((c for c in (quota.cells if quota else [])
                     if c.option_id == cell_oid), None)
        label = cell.option_label if cell else cell_oid
        if t.polarity == "available":
            return (f"Prove quota {quota_id} lets a {label!r} respondent through "
                    f"while that group is still below its target")
        n = cell.target_count if cell else "?"
        return (f"Prove quota {quota_id} turns a {label!r} respondent away once "
                f"that group has reached its target of {n}")
    if t.dimension == "D9":
        a, b = t.subject.split("+")
        return f"{b} shown by its condition while also depending on {a}: {pol}"
    return t.claim


def _answer(spec: CanonicalSpec, qid: str, value) -> str:
    q = spec.question(qid)
    if value is None or value == "" or value == [] or value == {}:
        if q is not None and q.options:
            return "leave unanswered (do not pick any option)"
        return "leave unanswered (type nothing)"
    if isinstance(value, dict):
        parts = []
        for k, v in list(value.items())[:3]:
            ko = q.option_by_id(str(k)) if q else None
            vo = q.option_by_id(str(v)) if q else None
            parts.append(f"{(ko.label if ko else k)}={(vo.label if vo else v)}")
        return "; ".join(parts) + ("..." if len(value) > 3 else "")
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            o = q.option_by_id(str(v)) if q else None
            out.append(o.label if o else str(v))
        return " + ".join(out)
    o = q.option_by_id(str(value)) if q else None
    return o.label if o else str(value)


# A presence check carries its polarity in `expected`, so the wording has to
# follow it. Rendering the positive phrasing for a negative expectation is how
# the earlier version came to say "Q6 IS shown" on a test proving Q6 is hidden.
NEGATED = {
    "field_present": "field_absent",
    "question_visible": "question_absent",
}


def _checks(assertions: list[dict]) -> str:
    out = []
    for a in assertions:
        kind = str(a.get("kind", ""))
        exp = a.get("expected")
        if exp is False and kind in NEGATED:
            kind = NEGATED[kind]
        tpl = CHECK.get(kind, kind.replace("_", " "))
        target = str(a.get("target") or a.get("canonical") or "")
        val = "" if exp in (True, False, None) else (
            ", ".join(str(x) for x in exp) if isinstance(exp, list) else str(exp))
        out.append(tpl.replace("{q}", target).replace("{v}", val))
    return "\n".join(f"{i}. {x}" for i, x in enumerate(out, 1))


def _static(spec: CanonicalSpec, q, snap, findings) -> tuple[str, str]:
    if snap is None:
        return ("Not yet checked: no built survey supplied to compare against.",
                "Not checked")
    built = snap.questions.get(q.id)
    if built is None:
        return ("This question is in the QRE but was NOT found in the built "
                "survey.", "PROBLEM")
    bits = [f"present in the built survey",
            f"type is {TYPE_NAME.get(built.type, built.type)}, matching the "
            f"QRE's '{q.kind}'"]
    if q.options:
        bits.append(f"all {len(q.options)} answer options found and matched to "
                    f"the survey's own codes")
    if q.matrix_rows:
        bits.append(f"all {len(q.matrix_rows)} rows found")
    bits.append("marked compulsory, as the QRE requires" if built.mandatory
                else "marked optional, as the QRE requires")
    problem = False
    if q.guard is not None:
        if built.relevance in ("1", ""):
            bits.append("PROBLEM: the QRE gives this question a show-condition "
                        "but the built survey shows it always")
            problem = True
        else:
            bits.append("a show-condition is programmed on it")
    for f in findings.get(q.id, []):
        if f["kind"] in ("TYPE_MISMATCH", "MANDATORY_MISMATCH",
                         "OPTION_NOT_BOUND", "GUARD_NOT_BUILT",
                         "RANDOMIZATION_NOT_BUILT"):
            bits.append(f"PROBLEM: {f['detail']}")
            problem = True
    return "; ".join(bits) + ".", ("PROBLEM" if problem else "Checked")


def _no_test_note(spec: CanonicalSpec, q) -> str:
    driving = [f"{r.id} ({r.kind} to {r.destination_id or '?'})"
               for r in spec.rules
               if r.when is not None and q.id in r.when.mentioned()]
    guards = [o.id for o in spec.questions
              if o.guard is not None and q.id in o.guard.mentioned()]
    if driving or guards:
        bits = []
        if driving:
            bits.append("its answer drives " + ", ".join(sorted(set(driving))))
        if guards:
            bits.append("it controls whether " + ", ".join(sorted(guards))
                        + " appears")
        return ("No run of its own. " + "; and ".join(bits)
                + ". Those behaviours are tested at the question where the rule "
                  "takes effect, so look there. This question is still answered "
                  "during those runs.")
    return ("No run needed. Always shown, no answer rule of its own, and no "
            "routing rule depends on its answer, so there is nothing a "
            "respondent could do that would reveal a mistake here. Everything "
            "that CAN be wrong is covered by the direct check row.")


def _anchor(spec: CanonicalSpec, t: CoverageTarget) -> tuple[int, str]:
    def seq_of(qid):
        q = spec.question(qid)
        return (q.seq, q.id) if q else None
    far = (10 ** 6, "")

    # "advances", "shown" and "hidden" all name a question directly.
    if t.dimension == "D1" and t.polarity in ("advances", "shown", "hidden"):
        return seq_of(t.subject) or far
    if t.dimension == "D1":                        # a skip rule
        rule = spec.rule(t.subject.split(":")[0])
        if rule and rule.evaluation_point:
            return seq_of(rule.evaluation_point) or far
    if t.dimension == "D2":
        ending, _, named_rule = t.subject.partition("<-")
        if named_rule:
            rule = spec.rule(named_rule)
            if rule and rule.evaluation_point:
                return seq_of(rule.evaluation_point) or far
        for r in sorted((r for r in spec.rules if r.destination_id == ending),
                        key=lambda r: (r.precedence, r.id)):
            if r.evaluation_point:
                got = seq_of(r.evaluation_point)
                if got:
                    return got
        for quota in spec.quotas:
            if quota.on_full == ending and quota.variable_question_id:
                got = seq_of(quota.variable_question_id)
                if got:
                    return got
        return far
    if t.dimension == "D3":
        got = seq_of(t.subject)
        if got:
            return got
        rule = spec.rule(t.subject)
        if rule and rule.evaluation_point:
            return seq_of(rule.evaluation_point) or far
        return far
    if t.dimension == "D4":
        return seq_of(t.subject) or far
    if t.dimension in ("D5", "D6"):
        return seq_of(t.subject.split("->")[-1]) or far
    if t.dimension == "D7":
        return seq_of(t.subject) or far
    if t.dimension == "D8":
        quota = next((x for x in spec.quotas
                      if x.id == t.subject.split(":")[0]), None)
        if quota and quota.variable_question_id:
            return seq_of(quota.variable_question_id) or far
        return far
    if t.dimension == "D9":
        return seq_of(t.subject.split("+")[-1]) or far
    return far


def build(out_path: Path, spec: CanonicalSpec, targets: list[CoverageTarget],
          scenarios: list[VerifiedScenario], logical_tests: list[dict],
          exec_tests: list[dict], snap: ImplementationSnapshot | None,
          summary: dict, conformance: dict | None = None) -> Path:

    findings: dict[str, list[dict]] = {}
    for f in ((conformance or {}).get("findings") or []):
        for subj in str(f.get("subject", "")).split(","):
            findings.setdefault(subj.strip().split("/")[0], []).append(f)

    sc_by = {s.target_id: s for s in scenarios}
    log_by = {t["target_id"]: t for t in logical_tests}
    exe_by = {t["target_id"]: t for t in exec_tests}

    grouped: dict[tuple[int, str], list[CoverageTarget]] = {}
    for t in targets:
        grouped.setdefault(_anchor(spec, t), []).append(t)
    for k in grouped:
        grouped[k].sort(key=lambda x: (SUB_ORDER.get((x.dimension, x.polarity), 99),
                                       x.subject))

    wb = Workbook()
    ws = wb.active
    ws.title = "Test cases"

    for i, (name, width) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=1, column=i, value=name)
        c.font = HEADER
        c.alignment = Alignment(vertical="bottom", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}1"

    order = 0

    def add(qid, qre_line, row_type, test_id, purpose, setup, action,
            expected, kind, runnable):
        nonlocal order
        if TESTS_ONLY and row_type != "Test":
            return
        r = ws.max_row + 1
        vals = [order if row_type == "Test" else None, qid, qre_line, row_type,
                test_id, purpose, setup, action, expected, kind, runnable]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.font = CELL
            c.alignment = TOPWRAP if i in (3, 6, 7, 8, 9) else TOP

    # Two claims can reduce to the identical run. The clearest example is a
    # multi-select whose QRE rule is "at least 1 selection": breaking that rule
    # and leaving the question blank are the same action with the same expected
    # result. Hiding one would lose a claim; presenting both without comment
    # looks like padding. So the second is flagged as equivalent.
    seen_runs: dict[tuple, str] = {}

    handled = set()
    for q in spec.in_order():
        key = (q.seq, q.id)
        handled.add(key)
        ref = q.source_reference or {}
        line = str(ref.get("text") or "")

        text, verdict = _static(spec, q, snap, findings)
        add(q.id, line, "Direct check", "",
            "Confirm the question was built at all, with the right type, the "
            "right options and the right compulsory setting",
            "none needed", "nothing; this is read straight off the built survey",
            text, "Read the built survey and compare", verdict)

        items = grouped.get(key, [])
        if not items:
            add(q.id, line, "No run needed", "", _no_test_note(spec, q),
                "", "", "", "", "n/a")
            continue

        for t in items:
            lt = log_by.get(t.target_id)
            sc = sc_by.get(t.target_id)
            purpose = _proves(spec, t)
            if lt is None or sc is None or sc.status != COVERED:
                reason = sc.reason if sc else None
                add(q.id, line, "Not tested", "", purpose, "", "",
                    WHY_NOT.get(reason, str(reason)),
                    KIND.get(t.dimension, t.dimension), "No")
                continue
            order += 1
            ex = exe_by.get(t.target_id)
            setup = "\n".join(
                f"{i}. {st['question_id']} = "
                f"{_answer(spec, st['question_id'], st.get('value'))}"
                for i, st in enumerate(lt.get("setup") or [], 1)) or "none"
            action = lt.get("action_text", "")

            # A behaviour that needs more than one respondent carries its
            # run-up recipe. Putting it in the setup column keeps it impossible
            # to miss: without the run-up the test simply cannot pass.
            camp = lt.get("campaign") or {}
            if camp.get("repetitions") and camp.get("cell"):
                setup = (f"FIRST send {camp['repetitions']} respondents who "
                         f"answer {camp.get('label')!r} at this question, so the "
                         f"group reaches its target. THEN, as respondent number "
                         f"{camp['repetitions'] + 1}:\n" + setup)
            elif camp.get("repetitions") and camp.get("compare"):
                setup = (f"Run this same path {camp['repetitions']} times and "
                         f"record the option order each time, then compare "
                         f"them.\n" + setup)
            expected = _checks(ex["assertions"] if ex else lt["assertions"])

            signature = (q.id, setup, action, expected)
            twin = seen_runs.get(signature)
            if twin:
                purpose += (f"  [Same actions as {twin} on this question: the "
                            f"questionnaire's answer rule and its compulsory "
                            f"setting come down to the same thing here. Both "
                            f"are kept because they are separate claims, but "
                            f"one run satisfies both.]")
            else:
                seen_runs[signature] = lt["test_id"]

            add(q.id, line, "Test", lt["test_id"], purpose, setup, action,
                expected, KIND.get(t.dimension, t.dimension),
                "Yes" if ex else "Not yet")

    for key in sorted(k for k in grouped if k not in handled):
        for t in grouped[key]:
            lt = log_by.get(t.target_id)
            sc = sc_by.get(t.target_id)
            proves = _proves(spec, t)
            if lt is None or sc is None or sc.status != COVERED:
                reason = sc.reason if sc else None
                add("whole survey", "", "Not tested", "", proves, "", "",
                    WHY_NOT.get(reason, str(reason)),
                    KIND.get(t.dimension, t.dimension), "No")
                continue
            order += 1
            ex = exe_by.get(t.target_id)
            setup = "\n".join(
                f"{i}. {st['question_id']} = "
                f"{_answer(spec, st['question_id'], st.get('value'))}"
                for i, st in enumerate(lt.get("setup") or [], 1)) or "none"
            add("whole survey", "", "Test", lt["test_id"], proves, setup,
                lt.get("action_text", ""),
                _checks(ex["assertions"] if ex else lt["assertions"]),
                KIND.get(t.dimension, t.dimension),
                "Yes" if ex else "Not yet")

    wb.save(out_path)
    return out_path
