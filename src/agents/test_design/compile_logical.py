"""Turns a verified scenario into a test a person can read and a bot can run.

Two rules drive everything here, and both came from reading the earlier output
and finding it unusable:

1. **A test stops at the question it is about.** A test proving that Q4 accepts
   a valid answer has no business walking on to Q7. The earlier questions are
   needed only to reach Q4, and everything after Q4 is irrelevant to the claim.
   So the journey is truncated at the focus question, and the answers before it
   are labelled setup rather than presented as part of the test.

2. **Assertions are derived from the claim, not scraped from the journey.**
   Previously every observable fact about the predicted run was collected and
   loosely filtered, which produced checks like "Q4's wording contains Very
   poor" on a test about Q4's minimum-selection rule. Now each kind of claim
   states exactly what must be observed to prove it, and nothing else.
"""

from __future__ import annotations

from typing import Any

from .models import LogicalTestCase, VerifiedScenario, CoverageTarget, COVERED, stable_id
from .spec import CanonicalSpec, Question


# --------------------------------------------------------------------------
# Where the test's attention is
# --------------------------------------------------------------------------

def focus_question(spec: CanonicalSpec, target: CoverageTarget) -> Question | None:
    """The question the claim is about. None means the claim spans the survey.

    Everything before it is setup. Everything after it is irrelevant, except
    for an ending claim, which by definition needs the run to finish.
    """
    d, subject = target.dimension, target.subject

    if d == "D2":
        return None                                   # needs the full journey
    if d == "D1" and target.polarity in ("shown", "hidden"):
        return spec.question(subject)
    if d == "D1":                                     # skip rule
        rule = spec.rule(subject.split(":")[0])
        return spec.question(rule.evaluation_point) if (
            rule and rule.evaluation_point) else None
    if d == "D3":
        q = spec.question(subject)
        if q is not None:
            return q
        rule = spec.rule(subject)
        return spec.question(rule.evaluation_point) if (
            rule and rule.evaluation_point) else None
    if d == "D4":
        return spec.question(subject)
    if d in ("D5", "D6"):
        return spec.question(subject.split("->")[-1])
    if d == "D7":
        return spec.question(subject)
    if d == "D8":
        quota = next((x for x in spec.quotas
                      if x.id == subject.split(":")[0]), None)
        return spec.question(quota.variable_question_id) if quota else None
    if d == "D9":
        return spec.question(subject.split("+")[-1])
    return None


def _blocks(target: CoverageTarget) -> bool:
    """Does this claim expect the survey to refuse to move on?"""
    return ((target.dimension == "D3" and target.polarity == "violated")
            or (target.dimension == "D4" and target.polarity == "enforced"))


# --------------------------------------------------------------------------
# Assertions, derived from the claim
# --------------------------------------------------------------------------

def assertions_for(spec: CanonicalSpec, target: CoverageTarget,
                   obs: dict) -> list[dict]:
    d, subject, pol = target.dimension, target.subject, target.polarity
    out: list[dict] = []

    def A(kind, expected=True, on=None, detail=""):
        out.append({"kind": kind, "target": on, "expected": expected,
                    "detail": detail})

    if d == "D1" and pol == "advances":
        seen = obs.get("questions_seen_in_order") or []
        nxt = None
        if subject in seen:
            i = seen.index(subject)
            nxt = seen[i + 1] if i + 1 < len(seen) else None
        A("question_visible", True, subject,
          "the question must be on screen so it can be answered")
        if nxt:
            A("next_question_is", nxt, nxt,
              "and the very next question the respondent sees must be this one")
        else:
            A("survey_completed", True, obs.get("ending_reached"),
              "this is the last question the respondent sees, so answering it "
              "must take them to the end screen")
        return out

    if d == "D1" and pol == "shown":
        A("question_visible", True, subject,
          "the question must be rendered on the page it belongs to")
        return out

    if d == "D1" and pol == "hidden":
        A("question_absent", True, subject,
          "the question must not be rendered, and the respondent must continue "
          "to the next question rather than being stopped or ended")
        A("respondent_continues", True, None,
          "proves the absence is the show-condition working, not the respondent "
          "having been screened out earlier")
        return out

    if d == "D1" and pol == "skip_fired":
        rule = spec.rule(subject.split(":")[0])
        dest = rule.destination_id if rule else None
        A("next_question_is", dest, dest,
          "the respondent must land on the jump's destination, not the next "
          "question in sequence")
        return out

    if d == "D1" and pol == "skip_not_fired":
        rule = spec.rule(subject.split(":")[0])
        point = spec.question(rule.evaluation_point) if (
            rule and rule.evaluation_point) else None
        nxt = None
        if point is not None:
            later = [q for q in spec.in_order() if q.seq > point.seq]
            nxt = later[0].id if later else None
        A("next_question_is", nxt, nxt,
          "the jump must NOT fire, so the respondent continues in sequence")
        return out

    if d == "D2":
        ending, _, named_rule = subject.partition("<-")
        disposition = spec.disposition(ending)
        via = f" by way of rule {named_rule}" if named_rule else ""
        if disposition is not None and disposition.kind == "complete":
            A("survey_completed", True, ending,
              f"the respondent must reach the normal completion screen{via}")
        else:
            A("ending_reached", ending, ending,
              f"the respondent must be sent to this ending{via} and see its "
              f"message")
        return out

    if d == "D3" and pol in ("boundary_max_accepted",
                             "special_characters_accepted"):
        q = spec.question(subject)
        why = ("an answer sitting exactly on the stated maximum is inside the "
               "rule, not outside it"
               if pol == "boundary_max_accepted" else
               "the rule constrains length and says nothing about content, so "
               "punctuation must be accepted")
        A("answer_accepted", True, subject, why)
        return out

    if d == "D4" and pol == "whitespace_rejected":
        A("answer_rejected", True, subject,
          "spaces alone are not an answer, and the questionnaire marks this "
          "question compulsory")
        return out

    if d == "D4" and pol == "whitespace_accepted":
        A("answer_accepted", True, subject,
          "the questionnaire marks this question optional, so spaces must not "
          "block progress")
        return out

    if d == "D3" and pol == "satisfied":
        q = spec.question(subject)
        if q is not None:
            A("answer_accepted", True, subject,
              f"the page must accept the answer and advance, because it meets "
              f"the QRE's rule {q.validation.constraints}")
        else:
            A("answer_accepted", True, subject,
              "the page must advance, because the reject rule's condition is "
              "not met")
        return out

    if d == "D3" and pol == "violated":
        A("answer_rejected", True, subject,
          "the page must NOT advance; it must redisplay with an error against "
          "this question")
        return out

    if d == "D4" and pol == "enforced":
        A("answer_rejected", True, subject,
          "the page must NOT advance; a required-answer message must appear "
          "against this question")
        return out

    if d == "D4" and pol == "not_enforced":
        A("answer_accepted", True, subject,
          "the page must advance despite the blank, because the QRE marks this "
          "question optional")
        return out

    if d == "D5":
        src, dst = subject.split("->")
        expected = (obs.get("option_lists_visible") or {}).get(dst)
        A("options_shown_are", expected, dst,
          f"the option list must be narrowed to exactly what was chosen at {src}")
        return out

    if d == "D6":
        src, dst = subject.split("->")
        expected = (obs.get("piped_text_visible") or {}).get(dst)
        A("wording_contains", expected, dst,
          f"the question text must render the answer given at {src}")
        return out

    if d == "D8" and pol == "over_target_admits":
        quota, cell = subject.split(":")
        A("respondent_accepted", True, quota,
          "a soft quota must let the respondent continue even once the cell is "
          "over its target")
        A("quota_recorded_over_target", subject, quota,
          "and the overflow must be recorded, or the field team cannot see the "
          "imbalance")
        return out

    if d == "D8" and pol == "not_counted_by_other_cell":
        quota, cell = subject.split(":")
        A("cell_count_unchanged", subject, quota,
          "the count for this cell must be identical before and after a "
          "respondent who belongs to a different cell")
        return out

    if d == "D8":
        quota, cell = subject.split(":")
        if pol == "available":
            A("respondent_accepted", True, quota,
              "the respondent must be allowed to continue, because the quota "
              "group is still open")
        else:
            A("ending_reached", "quota full", quota,
              "the respondent must be turned away once the group is full")
        return out

    if d == "D9":
        src, dst = subject.split("+")
        A("question_visible", True, dst,
          "the question must appear, proving its show-condition")
        piped = ((obs.get("piped_text_visible") or {}).get(dst)
                 or (obs.get("option_lists_visible") or {}).get(dst))
        A("reflects_dependency", piped, dst,
          f"and must simultaneously reflect its dependency on {src}")
        return out

    if d == "D7" and pol == "completeness":
        q = spec.question(subject)
        n = len(q.options) if q else 0
        A("option_count_is", n, subject,
          f"all {n} options the QRE lists must be rendered, none missing and "
          f"none repeated")
        A("option_set_is", sorted(o.label for o in (q.options if q else [])),
          subject, "and they must be exactly the options the QRE lists")
        return out

    if d == "D7" and pol == "order_varies":
        A("display_order_differs_across_runs", True, subject,
          "the order the options are rendered in must not be identical on "
          "every run; if it never changes, shuffling is not switched on")
        return out

    if d == "D7":
        rnd = next((r for r in spec.randomization
                    if r.question_id == subject), None)
        anchored = list(rnd.anchored) if rnd else []
        A("anchored_options_in_place", anchored, subject,
          "these options must hold the same position on every run while the "
          "others move")
        return out

    return out


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def compile_all(spec: CanonicalSpec, targets: list[CoverageTarget],
                scenarios: list[VerifiedScenario]) -> list[LogicalTestCase]:
    by_id = {t.target_id: t for t in targets}
    out: list[LogicalTestCase] = []

    for sc in scenarios:
        if sc.status != COVERED:
            continue
        target = by_id[sc.target_id]
        obs = sc.expected or {}
        shown = obs.get("questions_seen_in_order") or list(sc.answers)

        focus = focus_question(spec, target)
        cutoff = focus.seq if focus is not None else None

        setup: list[dict] = []
        action: list[dict] = []

        for q in spec.in_order():
            if q.id not in sc.answers or q.id not in shown:
                continue
            if cutoff is not None and q.seq > cutoff:
                continue
            entry = {
                "question_id": q.id,
                "question_kind": q.kind,
                "value": sc.answers[q.id],
            }
            if focus is not None and q.id == focus.id:
                action.append(entry)
            else:
                setup.append(entry)

        for i, st in enumerate(setup, start=1):
            st["step"] = i

        # What the bot does at the focus question, in words.
        if focus is None:
            action_text = ("Answer through the whole survey as listed, then "
                           "observe where it ends.")
        elif action:
            action_text = f"At {focus.id}, {_verb(spec, focus, action[0]['value'])}, then submit."
        else:
            prior = [q for q in spec.in_order()
                     if q.id in shown and (cutoff is None or q.seq < cutoff)]
            last = prior[-1].id if prior else "the previous question"
            action_text = (f"After submitting {last}, look for {focus.id} on the "
                           f"next page. Do not answer it.")

        assertions = assertions_for(spec, target, obs)

        out.append(LogicalTestCase(
            test_id=stable_id("TC", {"s": sc.scenario_id}),
            target_id=sc.target_id,
            dimension=sc.dimension,
            title=target.claim,
            steps=setup + ([{**a, "step": len(setup) + 1} for a in action]),
            assertions=assertions,
            traces_to=target.traces_to,
            executable=False,
            non_executable_reason="NO_BUILD_MANIFEST",
            provisional_semantics=sc.provisional_semantics,
            campaign=sc.campaign,
        ))
        out[-1].setup = setup                     # type: ignore[attr-defined]
        out[-1].action = action                   # type: ignore[attr-defined]
        out[-1].action_text = action_text         # type: ignore[attr-defined]
        out[-1].focus = (focus.id if focus else None)   # type: ignore[attr-defined]
        out[-1].blocks = _blocks(target)          # type: ignore[attr-defined]
    return out


def _verb(spec: CanonicalSpec, q: Question, value: Any) -> str:
    """What the bot physically does at the focus question, in plain words."""
    if value is None or value == "" or value == [] or value == {}:
        if q.options:
            return "select nothing at all"
        return "type nothing"
    if isinstance(value, dict):
        return "fill in every row"
    if isinstance(value, (list, tuple)):
        labels = []
        for v in value:
            o = q.option_by_id(str(v))
            labels.append(o.label if o else str(v))
        n = len(labels)
        return (f"tick {n} option{'s' if n != 1 else ''} "
                f"({', '.join(labels)})")
    o = q.option_by_id(str(value))
    if o:
        return f"choose \u201c{o.label}\u201d"
    text = str(value)

    # Spaces are invisible, so saying "type    " tells the reader nothing and
    # summarising them as an empty answer is worse: it describes a different
    # test from the one being run.
    if text and not text.strip():
        n = len(text)
        return f"type {n} space{'s' if n != 1 else ''} and nothing else"

    # A long run of filler is worth summarising, because its content carries no
    # meaning. Anything with real characters in it must be shown, because the
    # characters ARE the test.
    if len(text) > 24 and len(set(text)) <= 2:
        return f"type a {len(text)}-character answer"
    if len(text) > 60:
        return f"type this {len(text)}-character answer: \u201c{text[:50]}\u2026\u201d"
    return f"type \u201c{text}\u201d"
