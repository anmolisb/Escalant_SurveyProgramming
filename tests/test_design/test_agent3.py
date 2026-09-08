"""Agent 3 self-tests. Run with pytest, or directly:

    pytest tests/test_design

Covers what the architecture requires proof of:

  * B1 invents, duplicates or omits no target
  * B2's false-feasible rate is 0 (adversarial: contradictory guards)
  * B2's false-infeasible rate is 0 (adversarial: exclusive-option-only escape)
  * B2 and B3 are genuinely independent (import canary + disagreement canary)
  * UNRESOLVED is never silently promoted to PASS
  * Reproducibility: identical inputs give byte-identical artifacts
  * Specification replay agrees with the QRE's own scenarios
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from src.agents.test_design import (
    b1_targets, b2_witness, b3_oracle, b4_reconcile, compile_logical, spec)
from src.agents.test_design.models import COVERED
from src.agents.test_design.semantics import Semantics

# Fixtures live beside this file, the same way tests/survey_builder keeps its
# stage4-outputs. Nothing is resolved relative to the repository root, so the
# suite cannot be broken by being moved.
FIXTURE_ROOT = Path(__file__).parent / "canonical-outputs"


def _discover() -> list[Path]:
    if not FIXTURE_ROOT.is_dir():
        return []
    return [d for d in sorted(FIXTURE_ROOT.iterdir())
            if d.is_dir() and (d / "part2_canonical.json").exists()]


AVAILABLE = _discover()

# A suite that finds nothing to test must fail, not pass quietly. Every check
# below loops over AVAILABLE, so an empty list means each one does nothing at
# all and the run still reports success. That is precisely the false
# confidence Agent 3 exists to prevent, so it must not happen here either.
if not AVAILABLE:
    raise RuntimeError(
        f"no Agent 1 output found under {FIXTURE_ROOT}. Each survey needs its "
        f"own directory there containing part2_canonical.json.")


def _load(d: Path):
    s = spec.load(d / "part2_canonical.json")
    dec = d / "agent1_decisions.json"
    sem = Semantics.load(s.raw, dec if dec.exists() else None)
    return s, sem


def _pipeline(s, sem):
    targets, b1 = b1_targets.enumerate_targets(s)
    witnesses = b2_witness.generate(s, targets, sem)
    preds = {w.target_id: b3_oracle.predict(s, w.answers, sem)
             for w in witnesses if w.feasible}
    scenarios, coverage = b4_reconcile.reconcile(s, targets, witnesses, preds, sem)
    tests = compile_logical.compile_all(s, targets, scenarios)
    return targets, witnesses, preds, scenarios, coverage, tests


# ---------------------------------------------------------------- B1

def test_b1_no_duplicate_or_invented_targets():
    for d in AVAILABLE:
        s, sem = _load(d)
        targets, report = b1_targets.enumerate_targets(s)
        ids = [t.target_id for t in targets]
        assert len(ids) == len(set(ids)), f"{d.name}: duplicate target ids"

        # Every target's subject must exist in the spec, or B1 invented one.
        # Composite subjects are listed explicitly so a typo in the composing
        # code shows up here rather than silently passing.
        known = ({q.id for q in s.questions} | {q.kind for q in s.questions}
                 | {dd.id for dd in s.dispositions} | {r.id for r in s.rules}
                 | {f"{dep.from_question}->{dep.to_question}"
                    for dep in s.dependencies}
                 | {f"{q.id}:{c.option_id}" for q in s.quotas for c in q.cells}
                 | {f"{a}+{b}" for a in [x.id for x in s.questions]
                    for b in [y.id for y in s.questions]}
                 | {f"{r.id}:{r.evaluation_point}->{r.destination_id}"
                    for r in s.rules}
                 # one target per ROUTE to an ending: "ENDING<-RULE"
                 | {f"{r.destination_id}<-{r.id}" for r in s.rules
                    if r.destination_id})
        for t in targets:
            assert t.subject in known, \
                f"{d.name}: B1 invented subject {t.subject!r}"

        # Every rule must be traced by at least one target.
        assert not report["orphan_rules"], \
            f"{d.name}: rules covered by no target: {report['orphan_rules']}"
        print(f"  [ok] B1 {d.name}: {len(targets)} targets, no orphans")


# ---------------------------------------------------------------- B2

def test_b2_no_false_feasible_on_contradictory_guard():
    """Adversarial: a guard that cannot hold must be reported INFEASIBLE.

    Injects `S1 == Yes AND S1 == No` as a guard. Any feasible verdict is a
    false-feasible, which the design requires to be 0.
    """
    d = AVAILABLE[0]
    s, sem = _load(d)
    victim = next(q for q in s.questions if q.guard is not None)
    s1 = s.in_order()[0]
    a, b = s1.options[0].option_id, s1.options[1].option_id

    victim.guard = spec.Cond(
        op="and", source_text="injected contradiction",
        operands=[
            spec.Cond(op="eq", left_qid=s1.id, right_option_ids=[a]),
            spec.Cond(op="eq", left_qid=s1.id, right_option_ids=[b]),
        ])

    targets, _ = b1_targets.enumerate_targets(s)
    shown = next(t for t in targets
                 if t.dimension == "D1" and t.subject == victim.id
                 and t.polarity == "shown")
    w = b2_witness.generate(s, [shown], sem)[0]
    assert not w.feasible, "false-feasible: contradictory guard reported reachable"
    assert w.reason == "INFEASIBLE", f"expected INFEASIBLE, got {w.reason}"
    print(f"  [ok] B2 false-feasible rate 0 (contradiction on {victim.id} caught)")


def test_b2_no_false_infeasible_when_only_exclusive_option_escapes():
    """Adversarial: falsifying `contains_any` sometimes requires the exclusive
    option ("None of these"). Reporting that INFEASIBLE is a false-infeasible.

    This test exists because v0.1 had exactly this bug: `usable_options`
    excluded exclusive options, so Q6/hidden came back INFEASIBLE on C01.
    """
    d = AVAILABLE[0]
    s, sem = _load(d)
    targets, _ = b1_targets.enumerate_targets(s)
    witnesses = b2_witness.generate(s, targets, sem)

    false_infeasible = []
    for t, w in zip(targets, witnesses):
        if t.dimension != "D1" or t.polarity != "hidden":
            continue
        if w.feasible or w.reason != "INFEASIBLE":
            continue
        q = s.question(t.subject)
        if q is None or q.guard is None:
            continue
        # A contains_any guard over a strict subset of some question's options
        # is always falsifiable, because at least one option is left over.
        for cond in [q.guard] + q.guard.operands:
            if cond.op != "contains_any" or not cond.left_qid:
                continue
            src = s.question(cond.left_qid)
            if src and len(cond.right_option_ids) < len(src.options):
                false_infeasible.append((t.subject, cond.render()))
    assert not false_infeasible, f"false-infeasible verdicts: {false_infeasible}"
    print("  [ok] B2 false-infeasible rate 0 on all D1/hidden targets")


# ---------------------------------------------------------------- independence

def test_b2_and_b3_share_no_evaluation_code():
    """Import canary. If either module ever imports the other, or a shared
    condition evaluator appears, the independence guarantee is gone and this
    fails loudly rather than silently.

    Checks the parsed import graph, not raw text: both modules discuss the
    other in their docstrings on purpose, and a substring match would fire on
    the very comment that explains the rule.
    """
    import ast

    def imported_modules(module) -> set[str]:
        tree = ast.parse(Path(module.__file__).read_text())
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module)
                names.update(a.name for a in node.names)
        return names

    b2_imports = imported_modules(b2_witness)
    b3_imports = imported_modules(b3_oracle)

    assert "b3_oracle" not in b2_imports, "B2 imports B3: independence broken"
    assert "b2_witness" not in b3_imports, "B3 imports B2: independence broken"
    assert not (b2_imports & b3_imports & {"conditions", "evaluate", "evaluator"}), \
        "a shared condition evaluator appeared: independence broken"

    # Both may read `spec` (parsing is shared on purpose) and `semantics`, but
    # nothing that evaluates or solves conditions.
    shared = b2_imports & b3_imports
    assert shared <= {"spec", "semantics", "models", "__future__",
                      "annotations", "typing", "Any", "CanonicalSpec", "Cond",
                      "Question", "Semantics", "UNASKED", "PRECEDENCE",
                      "MULTI_EQ", "ExpectedState", "Witness", "CoverageTarget",
                      "INFEASIBLE", "BOUND_REACHED", "QUOTA_SIZE_UNDEFINED",
                      "RANDOMIZATION_ANCHOR_UNDEFINED"}, \
        f"unexpected shared dependency between B2 and B3: {sorted(shared)}"
    print("  [ok] B2/B3 import independence holds "
          f"(shared: {sorted(shared & {'spec', 'semantics', 'models'})})")


def test_b3_never_receives_the_target():
    """B3's public signature must not admit a target. If it did, B3 could tilt
    its prediction toward what the test wants to see.
    """
    import inspect
    params = list(inspect.signature(b3_oracle.predict).parameters)

    # The oracle may accept facts about the world the respondent walks into,
    # such as which quota cells are already full, because those are inputs to
    # the prediction rather than hints about the test. What it must never
    # accept is anything naming the target under test.
    allowed = {"spec", "answers", "semantics", "quota_full"}
    leaked = [p for p in params if p not in allowed]
    assert not leaked, f"B3.predict signature leaks: {leaked}"
    forbidden = {"target", "target_id", "claim", "dimension", "polarity",
                 "expected", "coverage_target"}
    assert not (set(params) & forbidden), \
        f"B3.predict accepts target information: {set(params) & forbidden}"
    print(f"  [ok] B3.predict takes no target argument (params: {params})")


def test_b3_disagrees_when_the_spec_is_broken():
    """Disagreement canary. Flip a guard's polarity in the spec B3 reads. If
    B2 and B3 secretly shared logic, both would flip together and B4 would
    still report the target covered. B4 must now report it uncovered.
    """
    d = AVAILABLE[0]
    s, sem = _load(d)
    targets, _ = b1_targets.enumerate_targets(s)
    victim = next(t for t in targets if t.dimension == "D1"
                  and t.polarity == "shown"
                  and s.question(t.subject) is not None
                  and s.question(t.subject).guard is not None)

    w = b2_witness.generate(s, [victim], sem)[0]
    assert w.feasible, "precondition: witness should be feasible"

    # Corrupt only the spec B3 reads.
    broken = copy.deepcopy(s)
    bq = broken.question(victim.subject)
    bq.guard = spec.Cond(op="not", source_text="canary inversion",
                         operands=[bq.guard])

    pred = b3_oracle.predict(broken, w.answers, sem)
    scenarios, _ = b4_reconcile.reconcile(s, [victim], [w],
                                          {victim.target_id: pred}, sem)
    assert scenarios[0].status != COVERED, \
        "B4 passed a target whose predicted state contradicts it"
    print("  [ok] B4 rejects a target when B3's prediction disagrees")


# ---------------------------------------------------------------- honesty

def test_unresolved_is_never_promoted_to_covered():
    """A target whose witness hit a search bound must never come back COVERED."""
    for d in AVAILABLE:
        s, sem = _load(d)
        targets, witnesses, preds, scenarios, _, _ = _pipeline(s, sem)
        by_w = {w.target_id: w for w in witnesses}
        for sc in scenarios:
            if sc.status != COVERED:
                continue
            w = by_w[sc.target_id]
            assert w.feasible, f"{sc.target_id}: covered without a feasible witness"
            assert w.reason is None, \
                f"{sc.target_id}: covered while carrying reason {w.reason}"
        print(f"  [ok] {d.name}: no bounded/infeasible target reported covered")


def test_every_uncovered_target_has_a_controlled_reason():
    allowed = {"INFEASIBLE", "BOUND_REACHED", "UNRESOLVED_DECISION",
               "UNSUPPORTED", "NOT_IN_IMPLEMENTATION", "UNVERIFIABLE",
               "QUOTA_SIZE_UNDEFINED", "RANDOMIZATION_ANCHOR_UNDEFINED"}
    for d in AVAILABLE:
        s, sem = _load(d)
        *_, scenarios, _, _ = _pipeline(s, sem)
        for sc in scenarios:
            if sc.status == COVERED:
                continue
            assert sc.reason in allowed, \
                f"{sc.target_id}: uncontrolled reason {sc.reason!r}"
        print(f"  [ok] {d.name}: every uncovered target carries a controlled reason")


def test_every_generated_test_is_marked_non_executable():
    """Nothing may reach Agent 4 pretending to be runnable while Block C is
    unbound. Block C refuses rather than guessing a missing identifier.
    """
    for d in AVAILABLE:
        s, sem = _load(d)
        *_, tests = _pipeline(s, sem)
        for t in tests:
            assert t.executable is False
            assert t.non_executable_reason == "NO_BUILD_MANIFEST"
            assert t.steps and t.assertions, f"{t.test_id}: empty test"
        print(f"  [ok] {d.name}: all {len(tests)} tests marked non-executable")


# ---------------------------------------------------------------- reproducibility

def test_reproducible_across_runs():
    for d in AVAILABLE:
        digests = []
        for _ in range(2):
            s, sem = _load(d)
            targets, witnesses, _, scenarios, coverage, tests = _pipeline(s, sem)
            blob = json.dumps({
                "t": [x.to_dict() for x in targets],
                "w": [x.to_dict() for x in witnesses],
                "s": [x.to_dict() for x in scenarios],
                "c": coverage,
                "tc": [x.to_dict() for x in tests],
            }, sort_keys=True, default=str)
            digests.append(hashlib.sha256(blob.encode()).hexdigest())
        assert digests[0] == digests[1], f"{d.name}: not reproducible"
        print(f"  [ok] {d.name}: reproducible, sha {digests[0][:12]}")


def test_specification_replay_has_no_disagreement():
    """B3 must not contradict the QRE's own acceptance scenarios.

    UNRESOLVED is acceptable and expected where a condition cannot be read.
    DISAGREE is not: it means either B3 is wrong or the QRE is inconsistent.
    """
    from src.agents.test_design.run import _replay
    for d in AVAILABLE:
        s, sem = _load(d)
        r = _replay(s, sem)
        assert r["disagreed"] == 0, \
            f"{d.name}: B3 contradicts the QRE on {r['disagreed']} scenario(s)"
        print(f"  [ok] {d.name}: replay {r['agreed']} agree / "
              f"{r['unresolved']} unresolved / 0 disagree")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    print(f"Agent 3 self-tests, fixtures: {[d.name for d in AVAILABLE]}\n")
    for fn in fns:
        print(f"{fn.__name__}:")
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
