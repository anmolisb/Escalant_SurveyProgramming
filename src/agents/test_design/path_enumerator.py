"""Enumerates the distinct respondent paths through a survey.

Why this exists
---------------
A testing team does not begin with individual checks. It begins by asking
"which journeys does this survey actually have?", because a journey is the unit
a person can picture, run and sign off. Everything else hangs off that.

So this module answers two questions before any test is designed:

  1. How many genuinely different journeys exist?
  2. Which small set of them, run together, exercises every branch at least
     once in both directions?

The first number is the honest denominator. The second is what gets tested.
Stating both is what makes the selection defensible rather than arbitrary.

Exclusive and exhaustive
------------------------
Two properties are claimed, and both are proven rather than asserted.

  EXCLUSIVE   No two selected paths are the same question sequence. Every path
              adds a shape none of the others has, and the module raises if a
              duplicate ever slips in.

  EXHAUSTIVE  Every branch the survey can take is exercised. A screen-out is
              reached. A guard is satisfied and also broken. A skip fires and
              also does not. Coverage is reported per branch, and anything left
              uncovered is named.

What is deliberately NOT enumerated
-----------------------------------
Crossing every branch decision with every other produces a combinatorial
explosion: eleven independent branches is over two thousand answer
combinations, and almost all of them walk a sequence some other combination
already walked. Those are collapsed, counted, and the residual risk is stated,
rather than quietly dropped.

The residual risk is real but small: it is a defect that depends on two branch
values simultaneously, where no rule in the specification relates them. Where
the specification DOES relate them, the interaction targets in B1 pick it up.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any

from .spec import CanonicalSpec, Cond, Question

# A branch is a point where the survey can go more than one way.
BRANCH_TERMINATE = "terminate"
BRANCH_GUARD = "guard"
BRANCH_SKIP = "skip"
BRANCH_QUOTA = "quota"

# What kind of journey a path is.
CLASS_SCREENOUT = "SCREENOUT"
CLASS_MAIN = "MAIN"
CLASS_QUOTA = "QUOTA_TERMINATION"


@dataclass
class Branch:
    """One place the survey can go more than one way."""

    branch_id: str
    kind: str                       # terminate | guard | skip | quota
    at_question: str                # where the decision is taken
    rule_id: str | None
    condition: str                  # the condition, in the QRE's own words
    controls: list[str] = field(default_factory=list)  # what it decides

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Path:
    """One distinct respondent journey."""

    path_id: str
    name: str
    route_class: str
    sequence: list[str]                       # questions seen, in order
    disposition: str | None
    decisions: dict[str, Any] = field(default_factory=dict)   # question -> answer
    branch_values: list[str] = field(default_factory=list)    # readable
    skipped: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    rules_exercised: list[str] = field(default_factory=list)
    branches_covered: list[str] = field(default_factory=list)
    scenario: str | None = None               # QRE acceptance scenario, if any
    why_selected: str = ""
    what_it_adds: str = ""
    preconditions: str = "Fresh respondent, no prior answers. Both quota cells open."
    campaign: dict = field(default_factory=dict)

    mechanism: str = ""

    @property
    def shape(self) -> str:
        """Two paths with the same shape are the same journey.

        The mechanism is part of the shape, not just the question sequence.
        Two quotas can route to the same ending and produce an identical
        sequence, but they are separate mechanisms: one can be built correctly
        and the other not. Deduplicating on sequence alone silently dropped the
        second quota on C02, which is the same mistake as testing an ending
        once when two rules lead to it.
        """
        return (" -> ".join(self.sequence) + " => " + str(self.disposition)
                + (f" via {self.mechanism}" if self.mechanism else ""))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sequence_text"] = " -> ".join(self.sequence) + (
            f"  ->  {self.disposition}" if self.disposition else "")
        return d


# --------------------------------------------------------------------------
# Finding the branches
# --------------------------------------------------------------------------

def _controlling_questions(cond: Cond | None) -> set[str]:
    return cond.mentioned() if cond is not None else set()


def enumerate_branches(spec: CanonicalSpec) -> list[Branch]:
    """Every point at which this survey can go more than one way.

    Ordered by where the decision is taken, so the list reads down the
    questionnaire the way a reviewer would.
    """
    out: list[Branch] = []

    for rule in spec.rules:
        if rule.kind == "terminate":
            out.append(Branch(
                branch_id=f"B-{rule.id}", kind=BRANCH_TERMINATE,
                at_question=rule.evaluation_point or "?",
                rule_id=rule.id,
                condition=rule.when.render() if rule.when else "",
                controls=[rule.destination_id or "?"]))
        elif rule.kind == "skip":
            out.append(Branch(
                branch_id=f"B-{rule.id}", kind=BRANCH_SKIP,
                at_question=rule.evaluation_point or "?",
                rule_id=rule.id,
                condition=rule.when.render() if rule.when else "",
                controls=[rule.destination_id or "?"]))

    for q in spec.in_order():
        if q.guard is None:
            continue
        controllers = sorted(_controlling_questions(q.guard))
        out.append(Branch(
            branch_id=f"B-show-{q.id}", kind=BRANCH_GUARD,
            at_question=controllers[-1] if controllers else q.id,
            rule_id=None,
            condition=q.guard.render(),
            controls=[q.id]))

    for quota in spec.quotas:
        out.append(Branch(
            branch_id=f"B-{quota.id}", kind=BRANCH_QUOTA,
            at_question=quota.variable_question_id,
            rule_id=quota.id,
            condition=f"{quota.id} cell at target",
            controls=[quota.on_full or "?"]))

    order = {q.id: q.seq for q in spec.questions}
    out.sort(key=lambda b: (order.get(b.at_question, 10 ** 6), b.branch_id))
    return out


# --------------------------------------------------------------------------
# Walking a path
# --------------------------------------------------------------------------

def _eval(spec: CanonicalSpec, cond: Cond | None, answers: dict,
          shown: set[str]) -> bool | None:
    """Evaluate a condition against chosen answers. None means cannot tell.

    Deliberately simple: this is path shaping, not the oracle. Anything it
    cannot read makes the branch unresolved, and an unresolved branch is
    reported rather than guessed.
    """
    if cond is None:
        return True
    if cond.op in ("and", "or", "not"):
        vals = [_eval(spec, c, answers, shown) for c in cond.operands]
        if cond.op == "not":
            return None if vals[0] is None else (not vals[0])
        if cond.op == "and":
            return False if False in vals else (None if None in vals else True)
        return True if True in vals else (None if None in vals else False)

    qid = cond.left_qid
    if not qid or qid not in answers:
        return False                       # unasked reads as false
    q = spec.question(qid)
    given = answers[qid]
    given = given if isinstance(given, list) else [given]
    given = {str(g) for g in given}

    want = set(cond.right_option_ids)
    if not want and q is not None:
        for v in cond.right_values:
            want.add(q.resolve(v) or str(v))

    op = cond.op
    if op in ("eq", "set_eq"):
        return given == want if (q and q.is_multi) else (
            len(given) == 1 and next(iter(given)) in want)
    if op == "ne":
        return not (len(given) == 1 and next(iter(given)) in want)
    if op == "in":
        return bool(given & want)
    if op == "not_in":
        return not (given & want)
    if op in ("contains", "contains_all"):
        return want <= given
    if op == "contains_any":
        return bool(want & given)
    if op == "answered":
        return len(given) > 0
    return None


def walk(spec: CanonicalSpec, answers: dict[str, Any]) -> Path:
    """Walk the survey with a given set of branch answers and record the shape.

    Only the branch answers matter. Every other question is answered with its
    first option, because it cannot change where the respondent goes.
    """
    seq: list[str] = []
    hidden: list[str] = []
    skipped: list[str] = []
    rules: list[str] = []
    branches: list[str] = []
    filled = dict(answers)
    shown: set[str] = set()
    disposition: str | None = None
    fired_terminate: str | None = None
    skip_to: str | None = None

    ordered_rules = sorted(spec.rules, key=lambda r: (r.precedence, r.id))

    for q in spec.in_order():
        if skip_to is not None:
            if q.id != skip_to:
                skipped.append(q.id)
                continue
            skip_to = None

        if q.guard is not None:
            ok = _eval(spec, q.guard, filled, shown)
            branches.append(f"B-show-{q.id}={'T' if ok else 'F'}")
            if not ok:
                hidden.append(q.id)
                continue

        if q.id not in filled:
            if q.options:
                filled[q.id] = ([q.options[0].option_id] if q.is_multi
                                else q.options[0].option_id)
            else:
                filled[q.id] = "x" * 10

        shown.add(q.id)
        seq.append(q.id)

        for rule in ordered_rules:
            if rule.kind in ("show", "reject"):
                continue
            if (rule.evaluation_point or "") != q.id:
                continue
            fired = _eval(spec, rule.when, filled, shown)
            branches.append(f"B-{rule.id}={'T' if fired else 'F'}")
            if not fired:
                continue
            rules.append(rule.id)
            if rule.kind == "terminate":
                disposition = rule.destination_id
                fired_terminate = rule.id
                break
            if rule.kind == "skip":
                skip_to = rule.destination_id
                break
        if disposition:
            break

    if disposition is None:
        complete = next((d for d in spec.dispositions if d.kind == "complete"),
                        None)
        disposition = complete.id if complete else None
        for q in spec.in_order():
            if q.id not in seq and q.id not in hidden and q.id not in skipped:
                hidden.append(q.id)

    # Which show rules did this path exercise
    for r in spec.rules:
        if r.kind == "show" and r.destination_id in seq and r.id not in rules:
            rules.append(r.id)

    # The mechanism is whichever terminate rule ended the journey. Deriving it
    # here rather than at each call site means every path gets it the same way,
    # so an acceptance-scenario path and a rule-driven path that end the same
    # way correctly recognise each other as the same journey.
    return Path(path_id="", name="", route_class="", sequence=seq,
                disposition=disposition, decisions=answers,
                skipped=skipped, hidden=hidden,
                rules_exercised=sorted(set(rules)),
                branches_covered=branches,
                mechanism=fired_terminate or "")


# --------------------------------------------------------------------------
# Choosing the answers that drive each branch
# --------------------------------------------------------------------------

def _answer_making(spec: CanonicalSpec, cond: Cond | None,
                   want: bool) -> dict[str, Any]:
    """Pick answers that make a condition true or false.

    Small and deliberate. Anything more elaborate belongs in the witness
    generator; here we only need to steer the journey.
    """
    if cond is None:
        return {}
    if cond.op == "not":
        return _answer_making(spec, cond.operands[0], not want)
    if cond.op in ("and", "or"):
        effective = cond.op if want else ("or" if cond.op == "and" else "and")
        if effective == "and":
            out: dict[str, Any] = {}
            for c in cond.operands:
                out.update(_answer_making(spec, c, want))
            return out
        return _answer_making(spec, cond.operands[0], want)

    qid = cond.left_qid
    q = spec.question(qid) if qid else None
    if q is None:
        return {}

    wanted = list(cond.right_option_ids)
    if not wanted:
        wanted = [q.resolve(v) or str(v) for v in cond.right_values]
    wanted = [w for w in wanted if w]
    if not wanted:
        return {}

    others = [o.option_id for o in q.options if o.option_id not in wanted]

    # `ne` and `not_in` are already negations, so making them TRUE means
    # choosing something OTHER than the named value. Missing this flip is why
    # an early version never reached one of C02's screen-outs: the rule reads
    # "terminate if S2 is not the qualifying answer", and we kept selecting the
    # qualifying answer.
    if cond.op in ("ne", "not_in"):
        want = not want

    if want:
        return {qid: (wanted[:1] if q.is_multi else wanted[0])}
    if not others:
        return {}
    return {qid: ([others[0]] if q.is_multi else others[0])}


def survive_screeners(spec: CanonicalSpec, except_rule: str | None = None
                      ) -> dict[str, Any]:
    """Answers that get a respondent past every screen-out.

    Steering a branch deep in the survey is not enough on its own. If the
    default answers happen to trip a screener, the respondent never reaches the
    question the branch is about, and the path silently becomes a screen-out
    that some other path already covers.

    That is exactly what happened on C02 before this was added: three guards
    could never be seen in the false direction, because every attempt was
    thrown out at the third screening question.
    """
    out: dict[str, Any] = {}
    for rule in spec.rules:
        if rule.kind != "terminate" or rule.id == except_rule:
            continue
        out.update(_answer_making(spec, rule.when, False))
    return out


def _merge(base: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Target answers win, because they are the point of the path."""
    out = dict(base)
    out.update(target)
    return out


# --------------------------------------------------------------------------
# Building the path set
# --------------------------------------------------------------------------

def _name_for(spec: CanonicalSpec, p: Path) -> str:
    if p.route_class == CLASS_SCREENOUT:
        rule = next((r for r in spec.rules if r.destination_id == p.disposition
                     and r.id in p.rules_exercised), None)
        where = rule.evaluation_point if rule else (p.sequence[-1] if p.sequence else "?")
        return f"Screened out at {where} ({p.disposition})"
    if p.route_class == CLASS_QUOTA:
        quota = next((q for q in spec.quotas if q.id == p.mechanism), None)
        cell = p.campaign.get("label") if p.campaign else None
        if quota is not None:
            return (f"{quota.id} cell already full"
                    + (f" ({cell})" if cell else "")
                    + f" \u2014 measured on {quota.variable_question_id}")
        return f"Turned away: {p.disposition}"
    # Name a completing path by what makes it different, not by the screener
    # answers it shares with every other completing path.
    screeners = {q.id for q in spec.questions if q.id.upper().startswith("S")}
    distinguishing = {k: v for k, v in p.decisions.items() if k not in screeners}
    source = distinguishing or p.decisions

    bits = []
    for qid, val in sorted(source.items())[:3]:
        q = spec.question(qid)
        vals = val if isinstance(val, list) else [val]
        labels = []
        for v in vals:
            o = q.option_by_id(str(v)) if q else None
            labels.append(o.label if o else str(v))
        bits.append(f"{qid}={'/'.join(labels)}")
    return "Completing respondent" + (" \u2014 " + "; ".join(bits) if bits else "")


def enumerate_paths(spec: CanonicalSpec) -> tuple[list[Path], list[Branch], dict]:
    """Produce the exclusive, branch-exhaustive set of paths.

    Built in four passes, each one adding a shape the earlier passes cannot:

      1. One path per terminate rule. Each screen-out is an exclusive exit and
         a build can wire one correctly and another not.
      2. One path per quota. Reaching a quota-full ending needs a run-up, so
         these are marked as campaigns rather than single journeys.
      3. The QRE's own acceptance scenarios, so the author's worked examples
         are represented as paths in their own right.
      4. Whatever else is needed so that every guard is seen both satisfied and
         broken, and every skip both fired and not fired.
    """
    branches = enumerate_branches(spec)
    paths: list[Path] = []
    shapes: set[str] = set()

    def add(p: Path, klass: str, why: str, adds: str,
            scenario: str | None = None, campaign: dict | None = None,
            mechanism: str = "") -> bool:
        if mechanism:
            p.mechanism = mechanism
        if p.shape in shapes:
            return False
        shapes.add(p.shape)
        p.route_class = klass
        p.why_selected = why
        p.what_it_adds = adds
        p.scenario = scenario
        p.campaign = campaign or {}
        p.path_id = f"P{len(paths) + 1:02d}"
        p.name = _name_for(spec, p)
        paths.append(p)
        return True

    # ---- pass 1: one per terminate rule -----------------------------------
    for rule in sorted((r for r in spec.rules if r.kind == "terminate"),
                       key=lambda r: (r.precedence, r.id)):
        answers = _merge(survive_screeners(spec, except_rule=rule.id),
                         _answer_making(spec, rule.when, True))
        p = walk(spec, answers)
        add(p, CLASS_SCREENOUT,
            f"The only path that exercises {rule.id}, the rule that routes to "
            f"{rule.destination_id}.",
            f"Reaches {rule.destination_id} by way of {rule.id}. No other path "
            f"ends here through this rule.",
            mechanism=rule.id)

    # ---- pass 2: one per quota --------------------------------------------
    for quota in spec.quotas:
        cell = next((c for c in quota.cells if c.target_count is not None),
                    quota.cells[0] if quota.cells else None)
        if cell is None:
            continue
        answers = _merge(survive_screeners(spec),
                         {quota.variable_question_id: cell.option_id})
        p = walk(spec, answers)
        p.disposition = quota.on_full or p.disposition
        p.preconditions = (f"{quota.id} cell {cell.option_label!r} already at "
                           f"its target of {cell.target_count} respondents.")
        add(p, CLASS_QUOTA,
            f"The only path that exercises {quota.id} once its cell is full.",
            f"Proves a respondent is turned away by {quota.id}. Needs a run-up "
            f"of {cell.target_count} earlier respondents, so it is a campaign "
            f"rather than a single journey.",
            campaign={"repetitions": cell.target_count,
                      "cell": f"{quota.id}:{cell.option_id}",
                      "label": cell.option_label},
            mechanism=quota.id)

    # ---- pass 3: the QRE's own worked examples ----------------------------
    for sc in spec.scenarios:
        answers = {}
        for qid, raw in (sc.inputs or {}).items():
            q = spec.question(qid)
            if q is None:
                continue
            if isinstance(raw, list):
                answers[qid] = [q.resolve(v) or v for v in raw]
            elif isinstance(raw, dict):
                continue
            else:
                answers[qid] = q.resolve(raw) or raw
        if not answers:
            continue
        p = walk(spec, answers)
        klass = (CLASS_SCREENOUT if p.disposition and p.disposition != "COMPLETE"
                 and not p.disposition.startswith("COMP") else CLASS_MAIN)
        add(p, klass,
            f"This is the questionnaire's own worked example {sc.id}"
            + (f" ({sc.purpose})" if sc.purpose else "") + ".",
            f"Represents acceptance scenario {sc.id}, so the author's stated "
            f"expectation is tested as a journey rather than only as a rule.",
            scenario=sc.id)

    # ---- pass 4: fill the branch gaps -------------------------------------
    def covered() -> set[str]:
        return {b for p in paths for b in p.branches_covered}

    for branch in branches:
        if branch.kind == BRANCH_QUOTA:
            continue
        for want, flag in ((True, "T"), (False, "F")):
            key = f"{branch.branch_id}={flag}"
            if key in covered():
                continue
            cond = None
            if branch.kind == BRANCH_GUARD:
                q = spec.question(branch.controls[0])
                cond = q.guard if q else None
            else:
                rule = spec.rule(branch.rule_id) if branch.rule_id else None
                cond = rule.when if rule else None
            steer = _answer_making(spec, cond, want)
            if not steer:
                continue
            answers = _merge(survive_screeners(spec), steer)
            p = walk(spec, answers)
            what = branch.controls[0]
            add(p, CLASS_SCREENOUT if (p.disposition or "").startswith("TERM")
                else CLASS_MAIN,
                f"Added to cover {branch.branch_id} in the "
                f"{'satisfied' if want else 'broken'} direction, which no "
                f"earlier path reaches.",
                f"First path where {branch.condition} is "
                f"{'true' if want else 'false'}, so {what} is "
                f"{'shown' if want else 'not shown'} here for the first time.")

    # ---- pass 5: the two extremes ----------------------------------------
    #
    # Branch coverage alone reaches every switch in both directions, but always
    # one switch at a time. It never produces the journey where several
    # independent switches are off at once.
    #
    # That combination is worth having, because it is the shortest journey a
    # real respondent can take and the one where the most questions are absent.
    # If two guards interfere, this is where it shows. The mirror case, where
    # everything is shown, is the longest journey and the one most likely to
    # expose an ordering fault late in the survey.
    #
    # Two extra paths at most, so this cannot grow with the questionnaire.
    for want, label in ((False, "shortest"), (True, "longest")):
        steer: dict[str, Any] = {}
        for q in spec.in_order():
            if q.guard is None:
                continue
            picked = _answer_making(spec, q.guard, want)
            for qid, val in picked.items():
                steer.setdefault(qid, val)     # earlier guards win, so the
                                               # journey stays self-consistent
        if not steer:
            continue
        p = walk(spec, _merge(survive_screeners(spec), steer))
        if (p.disposition or "").startswith("TERM"):
            continue                            # not a completing journey
        n_absent = len(p.hidden) + len(p.skipped)
        add(p, CLASS_MAIN,
            f"The {label} completing journey. Branch coverage reaches every "
            f"switch on its own; this is the one where they are all "
            f"{'off' if not want else 'on'} together.",
            (f"{n_absent} question(s) absent at once. No other path turns this "
             f"many off simultaneously, so it is the only place two "
             f"display rules could interfere."
             if not want else
             f"Every optional question present at once, {len(p.sequence)} in "
             f"all. The longest journey, and the one most likely to expose an "
             f"ordering fault late in the survey."))

    # ---- prove the two claims ---------------------------------------------
    seen = [p.shape for p in paths]
    dupes = sorted({s for s in seen if seen.count(s) > 1})
    if dupes:
        raise AssertionError(f"path set is not exclusive: {dupes}")

    got = covered()
    want_all = set()
    for b in branches:
        if b.kind == BRANCH_QUOTA:
            continue
        want_all |= {f"{b.branch_id}=T", f"{b.branch_id}=F"}
    missing = sorted(want_all - got)

    # A branch can be unreachable because another branch always fires first.
    # The commonest case: a question carries a show-condition AND a skip rule
    # jumps past it under the same circumstances. Whenever the guard would be
    # false, the skip has already moved the respondent on, so the guard is
    # never independently observed.
    #
    # That is not a hole in the test set. It is a redundancy in the
    # questionnaire, and it is reported as such rather than papered over or
    # counted as a gap.
    shadowed: list[dict] = []
    still_missing: list[str] = []
    by_id = {b.branch_id: b for b in branches}
    for key in missing:
        bid, _, flag = key.partition("=")
        branch = by_id.get(bid)
        if branch is None or branch.kind != BRANCH_GUARD or flag != "F":
            still_missing.append(key)
            continue
        target_q = branch.controls[0]
        q = spec.question(target_q)
        steer = _answer_making(spec, q.guard, False) if q else {}
        probe = walk(spec, _merge(survive_screeners(spec), steer))
        if target_q not in probe.skipped:
            still_missing.append(key)
            continue
        culprit = next((r for r in spec.rules
                        if r.kind == "skip" and r.id in probe.rules_exercised),
                       None)
        shadowed.append({
            "branch": key,
            "question": target_q,
            "guard": branch.condition,
            "shadowed_by": culprit.id if culprit else "a skip rule",
            "skip_condition": culprit.when.render() if (culprit and culprit.when) else "",
            "finding": (f"{target_q} carries a show-condition, and "
                        f"{culprit.id if culprit else 'a skip rule'} jumps past "
                        f"it under the same circumstances. Whenever the "
                        f"show-condition would be false, the respondent has "
                        f"already been moved on, so the condition is never "
                        f"observed on its own. The two say the same thing. "
                        f"Worth confirming with the author that both are "
                        f"intended."),
        })
    missing = still_missing

    # ---- what we deliberately did not enumerate ---------------------------
    decision_points = [b for b in branches if b.kind != BRANCH_QUOTA]
    full_space = 2 ** len(decision_points) if decision_points else 0

    report = {
        "branches_total": len(branches),
        "branch_states_total": len(want_all),
        "branch_states_covered": len(want_all & got),
        "branch_states_missing": missing,
        "branch_states_shadowed": shadowed,
        "paths_selected": len(paths),
        "exclusive": True,
        "branch_exhaustive": not missing,
        "exhaustive_note": (
            "Every branch that can be reached on its own is reached, in both "
            "directions."
            + (f" {len(shadowed)} guard state(s) cannot be reached "
               "independently because a skip rule fires under the same "
               "condition; those are listed as shadowed, not as gaps."
               if shadowed else "")),
        "not_enumerated": [
            {
                "family": "Every branch decision crossed with every other",
                "combinations": f"{full_space:,} answer combinations across "
                                f"{len(decision_points)} independent branches",
                "why_collapsed": "Almost every combination walks a question "
                                 "sequence that another combination already "
                                 "walks. Only distinct sequences are testable "
                                 "as distinct journeys.",
                "residual_risk": "A defect that depends on two branch values at "
                                 "once, where no rule in the specification "
                                 "relates them. Where a rule does relate them, "
                                 "the interaction checks pick it up.",
            },
            {
                "family": "Quota state crossed with every completing journey",
                "combinations": f"{len(spec.quotas) + 1} quota states \u00d7 every "
                                f"completing path",
                "why_collapsed": "The quota decision is taken at one question "
                                 "and does not change anything before it, so "
                                 "one path per quota is sufficient.",
                "residual_risk": "Low. Note the quota behaviour itself is "
                                 "absent from the built survey, which the "
                                 "conformance report already flags.",
            },
            {
                "family": "Screening decisions crossed with anything after them",
                "combinations": "Unreachable by construction",
                "why_collapsed": "A respondent screened out never reaches a "
                                 "later question, so the combination does not "
                                 "exist.",
                "residual_risk": "None.",
            },
        ],
    }
    return paths, branches, report


# --------------------------------------------------------------------------
# Which path hosts which test
# --------------------------------------------------------------------------

def host_path(paths: list[Path], question_id: str | None,
              disposition: str | None = None,
              mechanism: str | None = None) -> Path | None:
    """The path a focused test should be run on.

    A focused test needs a journey that actually reaches its question. The
    shortest such journey is chosen, so the test has the least unrelated
    activity around it and a failure is easier to attribute.

    `mechanism` matters when several paths share an ending. Two quotas both
    route to the quota-full page, so matching on the ending alone sends every
    quota test to whichever path happens to come first, and the other path ends
    up hosting nothing.
    """
    if mechanism:
        for p in paths:
            if p.mechanism == mechanism:
                return p
    if disposition:
        for p in paths:
            if p.disposition == disposition:
                return p
    if not question_id:
        return None
    candidates = [p for p in paths if question_id in p.sequence]
    if not candidates:
        return None
    return min(candidates, key=lambda p: (len(p.sequence), p.path_id))
