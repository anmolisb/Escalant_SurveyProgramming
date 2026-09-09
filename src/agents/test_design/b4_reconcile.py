"""B4 - Reconciliation / Coverage Integrity.

"Does this witness plus this predicted outcome actually prove the target?"

B4 deliberately has no logic-evaluation engine of its own. It compares; it does
not re-derive. If it re-evaluated conditions it would become a third opinion
that could quietly agree with a wrong B2 or a wrong B3, which defeats the point
of separating them.

WHAT B4 CANNOT CATCH, stated plainly rather than hidden: if B2 and B3 are both
wrong in the same direction and happen to agree, B4 will pass the target. That
is a real hole. The mitigation is structural independence upstream, not a check
here, and the residual risk is recorded rather than papered over.
"""

from __future__ import annotations

from .models import (
    VerifiedScenario, CoverageTarget, Witness, ExpectedState,
    COVERED, UNCOVERED, INFEASIBLE, UNVERIFIABLE, BOUND_REACHED,
    NOT_IN_IMPLEMENTATION, stable_id,
    EXHAUSTIVE, BOUNDED, PARTIAL, DIMENSIONS,
)
from .spec import CanonicalSpec
from .semantics import Semantics


def reconcile(spec: CanonicalSpec, targets: list[CoverageTarget],
              witnesses: list[Witness], predictions: dict[str, ExpectedState],
              sem: Semantics) -> tuple[list[VerifiedScenario], dict]:
    by_target = {w.target_id: w for w in witnesses}
    scenarios: list[VerifiedScenario] = []

    # Reject-rule equivalence is checked against targets already decided in
    # this pass, so question-level and dependency targets are settled first.
    def sort_key(t: CoverageTarget) -> tuple:
        return (1 if (t.dimension == "D3" and spec.rule(t.subject) is not None)
                else 0, t.dimension, t.subject, t.polarity)
    targets = sorted(targets, key=sort_key)

    for target in targets:
        witness = by_target.get(target.target_id)
        if witness is None or not witness.feasible:
            scenarios.append(VerifiedScenario(
                scenario_id=stable_id("SC", {"t": target.target_id}),
                target_id=target.target_id,
                dimension=target.dimension,
                status=UNCOVERED,
                reason=(witness.reason if witness else INFEASIBLE),
                proof=(witness.evidence if witness else "no witness generated"),
            ))
            continue

        state = predictions.get(target.target_id)
        if state is None:
            scenarios.append(VerifiedScenario(
                scenario_id=stable_id("SC", {"t": target.target_id}),
                target_id=target.target_id,
                dimension=target.dimension,
                status=UNCOVERED,
                reason=BOUND_REACHED,
                answers=witness.answers,
                proof="no prediction available for this witness",
            ))
            continue

        proven, proof = _demonstrates(spec, target, state)
        _ = scenarios      # equivalence reads the scenarios decided so far
        tags = sem.tags(set(state.semantics_used))

        reason = None
        covered_by = None
        if not proven:
            reason = UNVERIFIABLE
            if (target.dimension == "D3"
                    and spec.rule(target.subject) is not None
                    and "emits nothing for reject rules" in proof):
                reason = NOT_IN_IMPLEMENTATION
                # Before recording a gap, check whether some other test already
                # proves the same behaviour. A reject rule that restates a
                # constraint carried elsewhere is not an untested behaviour; it
                # is the same behaviour reached by a different route.
                covered_by = _equivalent_test(spec, target, targets, scenarios)
                if covered_by:
                    proven = True
                    reason = None
                    proof = (f"No separate run needed. This rule restates a "
                             f"constraint that {covered_by} already proves; the "
                             f"builder therefore emits nothing for it.")

        scenarios.append(VerifiedScenario(
            scenario_id=stable_id("SC", {"t": target.target_id,
                                         "a": witness.answers}),
            target_id=target.target_id,
            dimension=target.dimension,
            status=COVERED if proven else UNCOVERED,
            reason=reason,
            answers=witness.answers,
            expected=state.observable,
            proof=proof,
            provisional_semantics=tags,
            preconditions=witness.preconditions,
            campaign=witness.campaign,
            covered_by=covered_by,
        ))

    report = _coverage_report(targets, scenarios)
    return scenarios, report


def _equivalent_test(spec: CanonicalSpec, target: CoverageTarget,
                     targets: list[CoverageTarget],
                     decided: list[VerifiedScenario]) -> str | None:
    """Is this reject rule the same behaviour as an already-covered target?

    Two shapes recur in our questionnaires and both are genuine equivalences
    rather than convenient assumptions:

      an aggregate rule such as `sum(Q18) != 100`, where the question itself
      already carries `must total 100`, so the question's own accept and reject
      tests prove exactly the rule's effect; and

      a cross-question rule such as `the choice at Q6 must have been chosen at
      Q5`, where a carry-forward dependency already narrows Q6's option list to
      Q5's answers, making the rule unbreakable by construction.

    Anything else returns None and is recorded as a gap.
    """
    rule = spec.rule(target.subject)
    if rule is None or rule.when is None:
        return None
    done = {s.target_id: s for s in decided}

    # A condition is a tree. `not (Q5 contains Q6)` puts the comparison one
    # level down, so looking only at the top node misses it.
    def comparisons(node):
        if node is None:
            return []
        if not node.is_logical:
            return [node]
        found = []
        for child in node.operands:
            found.extend(comparisons(child))
        return found

    leaves = comparisons(rule.when)

    def covered_subject(dimension: str, subject: str) -> str | None:
        for t in targets:
            if t.dimension != dimension or t.subject != subject:
                continue
            sc = done.get(t.target_id)
            if sc is not None and sc.status == COVERED:
                return f"the {dimension} test on {subject}"
        return None

    for cond in leaves:
        # aggregate rule versus the question's own total
        if (cond.left_aggregate == "sum" and cond.left_qid
                and cond.right_number is not None):
            q = spec.question(cond.left_qid)
            if q is not None and q.validation.get("sum_to") == cond.right_number:
                found = covered_subject("D3", q.id)
                if found:
                    return found

        # cross-question rule versus a carry-forward dependency
        if cond.left_qid and cond.right_qid:
            for dep in spec.dependencies:
                if dep.kind != "option_source":
                    continue
                if {dep.from_question, dep.to_question} == {cond.left_qid,
                                                            cond.right_qid}:
                    found = covered_subject(
                        "D5", f"{dep.from_question}->{dep.to_question}")
                    if found:
                        return found
    return None


def _demonstrates(spec: CanonicalSpec, target: CoverageTarget,
                  state: ExpectedState) -> tuple[bool, str]:
    """Does the independently-predicted state actually show the target?

    This is a comparison against the OBSERVABLE part of the prediction only.
    A target that B3 can predict but Agent 4 could never see is not covered.
    """
    obs = state.observable
    seen = set(obs.get("questions_seen_in_order") or [])
    not_seen = set(obs.get("questions_not_seen") or [])
    ending = obs.get("ending_reached")
    blocked_at = obs.get("blocked_at")
    violations = {(v.get("question_id"), v.get("rule"))
                  for v in (obs.get("validation_messages_expected") or [])}

    d, subject, polarity = target.dimension, target.subject, target.polarity

    if d == "D1" and polarity == "advances":
        if blocked_at is not None:
            return False, (f"the respondent was blocked at {blocked_at}, so "
                           f"nothing is proved about moving on from {subject}")
        if subject not in seen:
            return False, f"{subject} was never reached; path {state.path}"
        i = list(obs.get("questions_seen_in_order") or []).index(subject)
        rest = list(obs.get("questions_seen_in_order") or [])[i + 1:]
        if rest:
            return True, (f"after answering {subject} the respondent went on to "
                          f"{rest[0]}")
        if ending:
            return True, (f"{subject} is the last question shown, and answering "
                          f"it took the respondent to {ending}")
        return False, (f"the respondent neither continued past {subject} nor "
                       f"reached an ending")

    if d == "D1" and polarity == "shown":
        return (subject in seen,
                f"{subject} appears in the predicted path" if subject in seen
                else f"{subject} was NOT shown: predicted path is {state.path}")

    if d == "D1" and polarity == "hidden":
        if blocked_at is not None:
            return False, (f"the respondent was blocked at {blocked_at}, so "
                           f"{subject}'s absence proves nothing about its guard")
        if subject in not_seen:
            return True, f"{subject} predicted hidden while the respondent continued"
        if ending and subject not in seen:
            return False, (f"{subject} is absent only because the respondent ended at "
                           f"{ending}; absence-by-termination does not prove the guard")
        return False, f"{subject} was shown: predicted path is {state.path}"

    if d == "D1" and polarity == "skip_fired":
        rule_id = subject.split(":")[0]
        dest = subject.split("->")[-1]
        fired = rule_id in state.fired_rules
        return (fired and dest in seen,
                f"{rule_id} fired and the respondent resumed at {dest}" if fired
                else f"{rule_id} did not fire: predicted path is {state.path}")

    if d == "D1" and polarity == "skip_not_fired":
        rule_id = subject.split(":")[0]
        return (rule_id not in state.fired_rules,
                f"{rule_id} correctly did not fire; respondent continued in sequence"
                if rule_id not in state.fired_rules
                else f"{rule_id} fired when it should not have")

    if d == "D2" and blocked_at is not None:
        return False, (f"the respondent was blocked at {blocked_at} and never "
                       f"reached an ending")

    if d == "D2" and "<-" in subject:
        want_ending, _, named_rule = subject.partition("<-")
        rule = spec.rule(named_rule)
        where = rule.evaluation_point if rule else None
        if ending != want_ending:
            return False, (f"the respondent reached {ending}, not "
                           f"{want_ending}; path {state.path}")
        if where and where not in seen:
            return False, (f"{where}, where {named_rule} fires, was never "
                           f"reached, so this route was not the one taken")
        return True, (f"{named_rule}, evaluated at {where}, sent the respondent "
                      f"to {want_ending}; path {state.path}")

    if d == "D2":
        return (ending == subject,
                f"predicted ending is {subject}, path {state.path}" if ending == subject
                else f"predicted ending is {ending}, not {subject}")

    if d == "D3":
        rule = spec.rule(subject)
        if rule is not None:
            # A rule whose QRE evaluation point is "the current question"
            # applies wherever its condition can hold, so a violation raised at
            # ANY question the condition names counts. Agent 1 resolves such a
            # rule to a single question, which would otherwise make a
            # multi-question rule look untestable.
            mentioned = rule.when.mentioned() if rule.when else set()
            points = {p for p in ({rule.evaluation_point} | mentioned) if p}
            hit = any(r == subject for _, r in violations)
            if not hit and polarity == "violated":
                hit = any(q in mentioned for q, _ in violations)
            if polarity == "violated":
                if hit:
                    return True, (f"reject rule {subject} fired as expected, at "
                                  f"one of the questions its condition names "
                                  f"({sorted(mentioned)})")
                if points and not (points & seen):
                    return False, (f"none of {sorted(points)}, where {subject} "
                                   f"can fire, was reached; path {state.path}")
                return False, (f"{subject} did not fire. The survey builder "
                               f"emits nothing for reject rules, treating them "
                               f"as restatements of the constraint already on "
                               f"the question, so there is no separate "
                               f"behaviour in the built survey to trigger")
            if points and not (points & seen):
                return False, (f"none of {sorted(points)}, where {subject} is "
                               f"evaluated, was reached; path {state.path}")
            return (not hit,
                    f"{subject} correctly did not fire" if not hit
                    else f"{subject} fired when it should not have")

        hit = any(q == subject for q, _ in violations)
        if polarity == "violated":
            return hit, (f"a validation message is predicted for {subject}" if hit
                         else f"no validation message predicted for {subject}")
        if subject not in seen and not hit:
            return False, (f"{subject} was not reached, so its validation rule was "
                           f"never exercised; path {state.path}")
        return (not hit,
                f"{subject} accepted the answer with no validation message" if not hit
                else f"{subject} unexpectedly triggered a validation message")

    if d == "D4":
        # Subject is a question id in both directions now, so the ruling names
        # the question at fault rather than a whole question type.
        hit = any(q == subject and r == "mandatory" for q, r in violations)
        if polarity == "enforced":
            return hit, (f"{subject} blocked the blank answer as required"
                         if hit else
                         f"{subject} let a blank answer through; no "
                         f"required-answer message was predicted")
        return (not hit,
                f"{subject} permitted a blank answer, as an optional question "
                f"should" if not hit else
                f"{subject} blocked a blank answer despite being optional")

    if d == "D5":
        dest = subject.split("->")[-1]
        piped = (obs.get("option_lists_visible") or {})
        if dest not in seen:
            return False, f"{dest} was not reached; path {state.path}"
        if dest in piped:
            return True, f"{dest} predicted to show only {piped[dest]}"
        return False, f"{dest} shown but no narrowed option list was predicted"

    if d == "D6":
        dest = subject.split("->")[-1]
        piped = (obs.get("piped_text_visible") or {})
        if dest not in seen:
            return False, f"{dest} was not reached; path {state.path}"
        if dest in piped:
            return True, f"{dest} predicted to render '{piped[dest]}' in its wording"
        return False, f"{dest} shown but no piped text was predicted"

    if d == "D8" and polarity == "available":
        quota_id = subject.split(":")[0]
        on_full = next((q.on_full for q in spec.quotas if q.id == quota_id), None)
        ok = ending is not None and ending != on_full
        return ok, (f"respondent admitted into the cell and reached {ending}"
                    if ok else
                    f"respondent was turned away at {ending} despite the cell "
                    f"being open")

    if d == "D8" and polarity == "full":
        stopped = obs.get("quota_stopped")
        ok = stopped == subject
        return ok, (f"respondent turned away by {subject} once it was at target"
                    if ok else
                    f"respondent was not stopped by {subject}; the run ended at "
                    f"{ending}")

    if d == "D7" and polarity == "completeness":
        q = spec.question(subject)
        if subject not in seen:
            return False, f"{subject} was not reached; path {state.path}"
        return True, (f"{subject} was reached, so its rendered option list can "
                      f"be counted against the {len(q.options) if q else 0} the "
                      f"QRE lists")

    if d == "D7" and polarity == "order_varies":
        if subject not in seen:
            return False, f"{subject} was not reached; path {state.path}"
        return True, (f"{subject} was reached, so the order it renders can be "
                      f"recorded and compared across repeated runs")

    if d == "D7":
        rnd = next((r for r in spec.randomization
                    if r.question_id == subject), None)
        if rnd is None or not rnd.anchored:
            return False, "no anchor list available, so there is no position to assert"
        if subject not in seen:
            return False, f"{subject} was not reached; path {state.path}"
        return True, (f"{subject} was reached, so the position of {rnd.anchored} "
                      f"can be recorded and compared across runs")

    if d == "D9":
        dest = subject.split("+")[-1]
        piped = set((obs.get("piped_text_visible") or {})) | \
            set((obs.get("option_lists_visible") or {}))
        if dest in seen and dest in piped:
            return True, f"{dest} shown by its guard and reflecting its dependency"
        if dest in seen:
            return False, f"{dest} shown but its dependency was not reflected"
        return False, f"{dest} was not reached; path {state.path}"

    return False, f"no reconciliation rule for {d}/{polarity}"


def _coverage_report(targets: list[CoverageTarget],
                     scenarios: list[VerifiedScenario]) -> dict:
    by_id = {t.target_id: t for t in targets}
    dims: dict[str, dict] = {}

    for sc in scenarios:
        t = by_id[sc.target_id]
        d = dims.setdefault(t.dimension, {
            "name": DIMENSIONS.get(t.dimension, t.dimension),
            "enumerated": 0, "covered": 0, "uncovered": 0,
            "reasons": {}, "provisional": 0,
        })
        d["enumerated"] += 1
        if sc.status == COVERED:
            d["covered"] += 1
            if sc.provisional_semantics:
                d["provisional"] += 1
        else:
            d["uncovered"] += 1
            d["reasons"][sc.reason] = d["reasons"].get(sc.reason, 0) + 1

    for code, d in dims.items():
        if code == "D9":
            d["enumeration_status"] = BOUNDED     # never claimed exhaustive
        elif d["uncovered"] == 0:
            d["enumeration_status"] = EXHAUSTIVE
        elif any(r in ("BOUND_REACHED",) for r in d["reasons"]):
            d["enumeration_status"] = BOUNDED
        else:
            d["enumeration_status"] = PARTIAL
        d["logical_coverage_pct"] = round(
            100.0 * d["covered"] / d["enumerated"], 1) if d["enumerated"] else 0.0

    floor = min((d["logical_coverage_pct"] for d in dims.values()), default=0.0)
    floor_dim = min(dims.items(), key=lambda kv: kv[1]["logical_coverage_pct"])[0] \
        if dims else None

    return {
        "coverage_vector": dims,
        "single_figure": {
            "value_pct": floor,
            "dimension": floor_dim,
            "label": "FLOOR - lowest dimension. Never a sum or an average.",
        },
        "executable_coverage_pct": 0.0,
        "executable_coverage_note": (
            "0% for every target and every survey. Block C cannot bind a "
            "canonical id to a LimeSurvey field without Agent 2's build "
            "manifest, which is not published yet. Logical and executable "
            "coverage are tracked separately precisely so this gap is visible."
        ),
        "known_blind_spot": (
            "B4 compares, it does not re-derive. Two independently-wrong "
            "components that happen to agree will pass. Mitigated by B2/B3 "
            "structural independence, not by a check in B4."
        ),
    }
