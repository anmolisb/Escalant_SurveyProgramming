"""B3 - Expected-State Oracle. "What should happen?"

Given an answer-set, computes what the survey should do. This is the safeguard
against a test and its expected answer sharing the same bug, so two rules are
enforced structurally rather than merely intended:

  1. B3 never receives the target. `predict()` takes a spec, an answer-set and
     the semantics. It cannot tilt its prediction toward what a target wants,
     because it does not know what is being tested.

  2. B3 shares no evaluation code with B2. B2 solves conditions backwards into
     Requirements. B3 evaluates them forwards against concrete values. This
     module imports nothing from b2_witness and there is no shared condition
     evaluator between them.

The interpreter is sequential: it walks questions in spec order, decides
visibility, applies rules at their evaluation point, and stops at an ending.
That mirrors how a respondent moves, which is why it predicts a path and not
merely a final state.

The three survey-wide semantics decisions enter here and nowhere else.
"""

from __future__ import annotations

from typing import Any

from .models import ExpectedState
from .spec import CanonicalSpec, Cond, Question
from .semantics import Semantics, WHITESPACE, UNASKED, PRECEDENCE, MULTI_EQ


UNRESOLVED = "UNRESOLVED"


class Interpreter:
    def __init__(self, spec: CanonicalSpec, semantics: Semantics,
                 quota_full: set[str] | None = None):
        self.spec = spec
        self.sem = semantics
        self.used: set[str] = set()
        # Which quota cells are already at target when this respondent arrives.
        # Whether a quota turns someone away depends on the respondents who
        # came before, which is not in the answer set. Stating it as an explicit
        # precondition keeps the prediction a function of its inputs.
        self.quota_full: set[str] = set(quota_full or ())

    # ------------------------------------------------------------------
    # Normalising an answer into option ids
    # ------------------------------------------------------------------

    def _given(self, qid: str, answers: dict[str, Any]) -> list[str] | None:
        if qid not in answers:
            return None
        raw = answers[qid]
        if raw is None or raw == [] or raw == {} or raw == "":
            return []
        q = self.spec.question(qid)
        if isinstance(raw, dict):
            return [str(v) for v in raw.values()]
        vals = list(raw) if isinstance(raw, (list, tuple, set)) else [raw]
        out = []
        for v in vals:
            resolved = q.resolve(v) if q else None
            out.append(resolved or str(v))
        return out

    def _expected(self, cond: Cond) -> set[str]:
        if cond.right_option_ids:
            return set(cond.right_option_ids)
        q = self.spec.question(cond.left_qid) if cond.left_qid else None
        out = set()
        for v in cond.right_values:
            out.add((q.resolve(v) if q else None) or str(v))
        return out

    # ------------------------------------------------------------------
    # Forward evaluation
    # ------------------------------------------------------------------

    def evaluate(self, cond: Cond | None, answers: dict[str, Any],
                 shown: set[str]) -> Any:
        """Returns True, False or UNRESOLVED. Never guesses."""
        if cond is None:
            return True

        if cond.op == "not":
            if not cond.operands:
                return UNRESOLVED
            inner = self.evaluate(cond.operands[0], answers, shown)
            return UNRESOLVED if inner is UNRESOLVED else (not inner)

        if cond.op in ("and", "or"):
            if not cond.operands:
                return UNRESOLVED
            results = [self.evaluate(c, answers, shown) for c in cond.operands]
            if cond.op == "and":
                if False in results:
                    return False
                return UNRESOLVED if UNRESOLVED in results else True
            if True in results:
                return True
            return UNRESOLVED if UNRESOLVED in results else False

        qid = cond.left_qid
        if not qid:
            return UNRESOLVED
        q = self.spec.question(qid)
        given = self._given(qid, answers)

        # Semantics decision 1: a condition naming a question the respondent
        # was never asked.
        if given is None or (q is not None and q.id not in shown and given == []):
            self.used.add(UNASKED)
            reading = self.sem.unasked_is
            if reading in ("condition_false", "false"):
                return False
            if reading in ("condition_true", "true"):
                return True
            return UNRESOLVED

        if cond.left_aggregate or cond.op.startswith("sum"):
            raw = answers.get(qid)
            if not isinstance(raw, dict) or cond.right_number is None:
                return UNRESOLVED
            total = sum(v for v in raw.values() if isinstance(v, (int, float)))
            if cond.op in ("eq", "sum_eq"):
                return total == cond.right_number
            if cond.op in ("ne", "sum_ne"):
                return total != cond.right_number
            return UNRESOLVED

        if cond.right_qid:
            other = self._given(cond.right_qid, answers)
            if other is None:
                self.used.add(UNASKED)
                return False if self.sem.unasked_is in ("condition_false", "false") \
                    else UNRESOLVED
            if cond.op == "eq":
                return set(given) == set(other)
            if cond.op == "ne":
                return set(given) != set(other)
            return UNRESOLVED

        expected = self._expected(cond)
        op = cond.op
        multi = bool(q and q.is_multi)

        if op == "answered":
            return len(given) > 0
        if op == "not_answered":
            return len(given) == 0

        # Semantics decision 3: what == means on a multi-select.
        if multi and op in ("eq", "set_eq"):
            self.used.add(MULTI_EQ)
            if op == "set_eq" or self.sem.multi_eq_is_exact_set:
                return set(given) == expected
            return bool(expected & set(given))
        if multi and op == "ne":
            self.used.add(MULTI_EQ)
            if self.sem.multi_eq_is_exact_set:
                return set(given) != expected
            return not (expected & set(given))

        if op == "eq":
            return len(given) == 1 and given[0] in expected
        if op == "ne":
            return not (len(given) == 1 and given[0] in expected)
        if op == "in":
            return len(given) >= 1 and given[0] in expected
        if op == "not_in":
            return not (len(given) >= 1 and given[0] in expected)
        if op in ("contains", "contains_all"):
            return expected <= set(given)
        if op == "contains_any":
            return bool(expected & set(given))

        return UNRESOLVED

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, q: Question, answers: dict[str, Any]) -> list[dict]:
        v = q.validation
        out: list[dict] = []

        # A question absent from the answer set is UNSPECIFIED, not blank.
        # The distinction matters: a witness deliberately leaving a question
        # empty carries an explicit None, whereas the QRE's own acceptance
        # scenarios list only the answers that matter and say nothing about the
        # rest. Treating an unmentioned question as a blank one would make
        # every such scenario fail on a mandatory-field error the author never
        # intended.
        if q.id not in answers:
            return out

        raw = answers[q.id]
        blank = raw is None or raw == [] or raw == {} or raw == ""

        # An answer of spaces alone. Whether that counts as an answer is a
        # reading the questionnaire never states, so it is taken from the
        # semantics rather than assumed here, and every test that depends on it
        # is tagged. The default reading is that spaces are not an answer.
        if not blank and isinstance(raw, str) and raw and not raw.strip():
            self.used.add(WHITESPACE)
            blank = self.sem.values.get(WHITESPACE) != "an_answer"

        if blank:
            if q.mandatory:
                out.append({"question_id": q.id, "rule": "mandatory",
                            "outcome": "violated",
                            "detail": "mandatory question left blank, "
                                      "progress should be blocked"})
            else:
                out.append({"question_id": q.id, "rule": "mandatory",
                            "outcome": "satisfied",
                            "detail": "optional question left blank, "
                                      "progress should be permitted"})
            return out

        if isinstance(raw, str):
            lo, hi = v.raw.get("min_length"), v.raw.get("max_length")
            if lo is not None and len(raw) < lo:
                out.append({"question_id": q.id, "rule": "min_length",
                            "outcome": "violated",
                            "detail": f"length {len(raw)} below minimum {lo}"})
            elif hi is not None and len(raw) > hi:
                out.append({"question_id": q.id, "rule": "max_length",
                            "outcome": "violated",
                            "detail": f"length {len(raw)} above maximum {hi}"})
            elif lo is not None or hi is not None:
                out.append({"question_id": q.id, "rule": "length",
                            "outcome": "satisfied",
                            "detail": f"length {len(raw)} within [{lo}, {hi}]"})

        if isinstance(raw, list):
            lo = v.raw.get("min_selections")
            if lo is not None and len(raw) < lo:
                out.append({"question_id": q.id, "rule": "min_selections",
                            "outcome": "violated",
                            "detail": f"{len(raw)} selected, minimum is {lo}"})
            elif lo is not None:
                out.append({"question_id": q.id, "rule": "min_selections",
                            "outcome": "satisfied",
                            "detail": f"{len(raw)} selected, minimum {lo} met"})

            excl = v.raw.get("exclusive_option_id")
            if excl:
                ids = {str(x) for x in raw}
                if excl in ids and len(ids) > 1:
                    out.append({"question_id": q.id, "rule": "exclusive_option",
                                "outcome": "violated",
                                "detail": f"exclusive option {excl} chosen "
                                          f"alongside {sorted(ids - {excl})}"})
                elif excl in ids:
                    out.append({"question_id": q.id, "rule": "exclusive_option",
                                "outcome": "satisfied",
                                "detail": f"exclusive option {excl} chosen alone"})

        if isinstance(raw, dict):
            if v.raw.get("require_each_row"):
                missing = [r for r in (q.matrix_rows or []) if r not in raw]
                if missing:
                    out.append({"question_id": q.id, "rule": "require_each_row",
                                "outcome": "violated",
                                "detail": f"rows left blank: {missing}"})
                else:
                    out.append({"question_id": q.id, "rule": "require_each_row",
                                "outcome": "satisfied",
                                "detail": "every row answered"})
            target = v.raw.get("sum_to")
            if target is not None:
                total = sum(x for x in raw.values() if isinstance(x, (int, float)))
                out.append({"question_id": q.id, "rule": "sum_to",
                            "outcome": "satisfied" if total == target else "violated",
                            "detail": f"values total {total}, required {target}"})
        return out

    # ------------------------------------------------------------------
    # The sequential walk
    # ------------------------------------------------------------------

    def run(self, answers: dict[str, Any]) -> ExpectedState:
        state = ExpectedState(witness_target_id="")
        shown: set[str] = set()
        path: list[str] = ["__START__"]

        if self.sem.precedence in ("document_order_first_match", "document_order"):
            ordered = sorted(self.spec.rules, key=lambda r: (r.precedence, r.id))
        elif self.sem.precedence == "most_specific":
            ordered = sorted(self.spec.rules,
                             key=lambda r: (-(r.when.size() if r.when else 0),
                                            r.precedence, r.id))
        else:
            ordered = sorted(self.spec.rules, key=lambda r: (r.precedence, r.id))
            state.unresolved.append(
                f"rule_precedence reading `{self.sem.precedence}` not implemented; "
                "fell back to document order")

        skip_target: str | None = None

        for q in self.spec.in_order():
            if skip_target is not None:
                if q.id != skip_target:
                    state.hidden.append(q.id)
                    continue
                skip_target = None

            guard = self.evaluate(q.guard, answers, shown)
            if guard is UNRESOLVED:
                state.unresolved.append(
                    f"{q.id}: display guard could not be evaluated "
                    f"({q.guard.render() if q.guard else ''})")
                state.hidden.append(q.id)
                continue
            if guard is False:
                state.hidden.append(q.id)
                continue

            shown.add(q.id)
            state.shown.append(q.id)
            path.append(q.id)

            if q.option_source:
                src = str(q.option_source.get("from_question") or "")
                chosen = self._given(src, answers)
                if chosen:
                    sq = self.spec.question(src)
                    labels = []
                    for oid in chosen:
                        o = sq.option_by_id(oid) if sq else None
                        labels.append(o.label if o else oid)
                    state.piped_options[q.id] = labels
                else:
                    state.unresolved.append(
                        f"{q.id}: option source {src} carries no answer to pipe")

            for dep in self.spec.dependencies:
                if dep.kind == "text_pipe" and dep.to_question == q.id:
                    chosen = self._given(dep.from_question, answers)
                    if chosen:
                        sq = self.spec.question(dep.from_question)
                        o = sq.option_by_id(chosen[0]) if sq else None
                        state.piped_text[q.id] = str(o.label if o else chosen[0])
                    else:
                        state.unresolved.append(
                            f"{q.id}: text pipe from {dep.from_question} "
                            "has nothing to render")

            findings = self._validate(q, answers)
            state.validation_triggered.extend(findings)

            # A quota check happens once the question it is measured on has
            # been answered.
            for quota in self.spec.quotas:
                if quota.variable_question_id != q.id or not quota.on_full:
                    continue
                # A soft quota records the overflow and lets the respondent
                # continue. Only a hard quota ends the journey.
                if (quota.enforcement or "hard").lower() == "soft":
                    chosen_soft = self._given(q.id, answers) or []
                    for oid in chosen_soft:
                        if f"{quota.id}:{oid}" in self.quota_full:
                            state.quota_over_target = f"{quota.id}:{oid}"
                    continue

                chosen = self._given(q.id, answers) or []
                for oid in chosen:
                    if f"{quota.id}:{oid}" in self.quota_full:
                        state.ending = quota.on_full
                        state.quota_stopped = f"{quota.id}:{oid}"
                        path.append(quota.on_full)
                        state.path = path
                        state.hidden.extend(
                            [x.id for x in self.spec.in_order()
                             if x.seq > q.seq and x.id not in state.hidden])
                        state.observable = _observable(state)
                        state.semantics_used = sorted(self.used)
                        return state

            # A real respondent who breaks a validation rule cannot move on:
            # the page redisplays with an error and nothing after it is
            # reachable. Walking past the failure would predict an ending the
            # respondent never sees, and would make the test assert both "an
            # error appears" and "the survey completes", which cannot both be
            # true.
            if any(f.get("outcome") == "violated" for f in findings):
                state.blocked_at = q.id
                state.ending = None
                path.append(f"BLOCKED_AT:{q.id}")
                state.path = path
                state.hidden.extend(
                    [x.id for x in self.spec.in_order()
                     if x.seq > q.seq and x.id not in state.hidden])
                state.observable = _observable(state)
                state.semantics_used = sorted(self.used)
                return state

            jumped = False
            for rule in ordered:
                if not self._applies_at(rule, q):
                    continue
                result = self.evaluate(rule.when, answers, shown)
                if result is UNRESOLVED:
                    state.unresolved.append(
                        f"{rule.id}: condition could not be evaluated at {q.id}")
                    continue
                if result is not True:
                    continue
                if len(ordered) > 1:
                    self.used.add(PRECEDENCE)

                if rule.kind == "terminate":
                    state.ending = rule.destination_id
                    path.append(rule.destination_id or "TERMINATE")
                    state.path = path
                    state.observable = _observable(state)
                    state.semantics_used = sorted(self.used)
                    return state
                if rule.kind == "skip":
                    skip_target = rule.destination_id
                    state.fired_rules.append(rule.id)
                    jumped = True
                    break
                if rule.kind == "reject":
                    state.validation_triggered.append(
                        {"question_id": q.id, "rule": rule.id, "outcome": "violated",
                         "detail": f"reject rule {rule.id} fires: {rule.when.render() if rule.when else ''}"})
                    state.fired_rules.append(rule.id)
            if jumped:
                continue

        completion = next((d for d in self.spec.dispositions
                           if d.kind == "complete"), None)
        if completion is None:
            state.unresolved.append("survey has no `complete` disposition to end at")
        else:
            state.ending = completion.id
            path.append(completion.id)
        state.path = path
        state.observable = _observable(state)
        state.semantics_used = sorted(self.used)
        return state

    def _applies_at(self, rule, q: Question) -> bool:
        """Is this rule evaluated once `q` has been answered?

        Agent 1 populates `evaluation_point` on every rule, so that is
        authoritative. Where it is absent, the rule is evaluated at the last
        question its condition mentions, because that is the earliest point
        every value it needs exists.
        """
        if rule.kind == "show":
            return False          # a show rule is the target question's guard
        if rule.evaluation_point:
            return rule.evaluation_point == q.id
        if rule.when is None:
            return False
        seqs = []
        for qid in rule.when.mentioned():
            mq = self.spec.question(qid)
            if mq is not None:
                seqs.append((mq.seq, mq.id))
        return bool(seqs) and max(seqs)[1] == q.id


def _observable(state: ExpectedState) -> dict:
    """Cap the prediction to what Agent 4 could actually verify on screen.

    Anything B3 knows that a respondent could not see is excluded on purpose,
    so no assertion can be written against something unobservable.
    """
    return {
        "questions_seen_in_order": list(state.shown),
        "questions_not_seen": list(state.hidden),
        "ending_reached": state.ending,
        "blocked_at": state.blocked_at,
        "quota_stopped": state.quota_stopped,
        "quota_over_target": state.quota_over_target,
        "validation_messages_expected": [
            f for f in state.validation_triggered if f.get("outcome") == "violated"],
        "piped_text_visible": dict(state.piped_text),
        "option_lists_visible": dict(state.piped_options),
    }


def predict(spec: CanonicalSpec, answers: dict[str, Any],
            semantics: Semantics,
            quota_full: set[str] | None = None) -> ExpectedState:
    """The only public entry point. Note the absence of a target argument.

    `quota_full` is a stated fact about the world the respondent walks into,
    not a hint about what is being tested. The prediction stays a pure function
    of the specification, the answers and that world state.
    """
    return Interpreter(spec, semantics, quota_full).run(answers)
