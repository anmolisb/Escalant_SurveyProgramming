"""Agent 3 v0.1 runner.

  python -m src.agents.test_design.run <survey-output-dir>

Reads Agent 1's artifacts from the given output directory, runs B1 -> B2 -> B3
-> B4, compiles logical test cases, and writes everything to
<dir>/agent3/.

Blocks A, C, D, E and F are not implemented in v0.1. A and C are blocked on
Agent 2's build manifest; D, E and F are pending design.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import (a_implementation, b1_targets, b2_witness, b3_oracle,
               b4_reconcile, c_compile_executable, compile_logical,
               path_enumerator, paths_workbook,
               qre_validation_workbook, report, spec)
from .models import COVERED
from .semantics import Semantics

SCHEMA_VERSION = "0.1.0"


def _envelope(spec_obj, artifact: str, payload) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": artifact,
        "agent": 3,
        "survey_id": spec_obj.survey_id,
        "source_document": {"filename": spec_obj.source_file,
                            "sha256": spec_obj.source_sha256},
        "upstream": {"canonical_schema_version": spec_obj.schema_version,
                     "canonical_generated_at": spec_obj.generated_at},
        "content": payload,
    }


def run(out_dir: str | Path, lss_path: str | Path | None = None,
        sample_size: int | None = None,
        inputs_path: str | Path | None = None) -> dict:
    out_dir = Path(out_dir)
    canonical = out_dir / "part2_canonical.json"
    decisions = out_dir / "agent1_decisions.json"
    gate = out_dir / "agent1_stage9_gate.json"

    # Facts the QRE never states but a test needs. Supplied by the project,
    # recorded in the output, never guessed.
    project_inputs: dict = {}
    if inputs_path:
        project_inputs = json.loads(Path(inputs_path).read_text(encoding="utf-8"))
    if sample_size is None:
        sample_size = project_inputs.get("sample_size")

    s = spec.load(canonical, sample_size=sample_size,
                  anchors=project_inputs.get("anchors"))
    sem = Semantics.load(s.raw, decisions if decisions.exists() else None)

    upstream_gate = {}
    if gate.exists():
        upstream_gate = json.loads(gate.read_text(encoding="utf-8"))

    # Paths first: the exclusive, branch-exhaustive set of journeys. A testing
    # team starts here, and every focused test is later hosted on one of them.
    paths, branches, path_report = path_enumerator.enumerate_paths(s)

    # B1
    targets, b1_report = b1_targets.enumerate_targets(s)

    # B2
    witnesses = b2_witness.generate(s, targets, sem)

    # B3 - note the call signature: no target is passed in.
    predictions = {}
    for w in witnesses:
        if not w.feasible:
            continue
        # Any world state the witness relies on is handed to the oracle as a
        # stated precondition, never as a hint about the target.
        full = set()
        cell = (w.preconditions or {}).get("quota_cell_full")
        if cell:
            full.add(cell)
        predictions[w.target_id] = b3_oracle.predict(s, w.answers, sem, full)

    # B4
    scenarios, coverage = b4_reconcile.reconcile(s, targets, witnesses,
                                                 predictions, sem)

    # Logical test compilation (always runs; platform-neutral)
    tests = compile_logical.compile_all(s, targets, scenarios)

    # Block A + Block C: only when a built .lss is available. Block C consumes
    # the logical tests, so they must exist first.
    snap = None
    conf = None
    exec_tests: list = []
    exec_report = {
        "logically_covered": sum(1 for sc in scenarios if sc.status == COVERED),
        "compiled_executable": 0,
        "refused": 0,
        "executable_coverage_pct": 0.0,
        "refusals": [],
        "note": "no built .lss supplied, so Blocks A and C did not run",
    }
    if lss_path:
        snap = a_implementation.parse_lss(lss_path, s)
        conf = a_implementation.conformance(s, snap)
        exec_tests, exec_report = c_compile_executable.compile_all(
            s, snap, targets, scenarios, tests)

    # Specification replay: Agent 1's own acceptance scenarios, walked through
    # B3. Tracked outside the coverage vector because it measures agreement
    # with the QRE's own examples, not behaviour coverage.
    replay = _replay(s, sem)

    dest = out_dir / "agent3"
    dest.mkdir(exist_ok=True)

    artifacts = {
        "agent3_targets.json": _envelope(s, "agent3_targets", {
            "report": b1_report,
            "targets": [t.to_dict() for t in targets]}),
        "agent3_witnesses.json": _envelope(s, "agent3_witnesses", {
            "feasible": sum(1 for w in witnesses if w.feasible),
            "total": len(witnesses),
            "witnesses": [w.to_dict() for w in witnesses]}),
        "agent3_expected_states.json": _envelope(s, "agent3_expected_states", {
            "predictions": {k: v.to_dict() for k, v in predictions.items()}}),
        "agent3_coverage.json": _envelope(s, "agent3_coverage", {
                "project_inputs": project_inputs,
            "semantics": sem.summary(),
            "semantics_all_resolved": sem.all_resolved,
            "upstream_gate": upstream_gate.get("content", upstream_gate),
            "b1": b1_report,
            "coverage": coverage,
            "specification_replay": replay}),
        "agent3_scenarios.json": _envelope(s, "agent3_scenarios", {
            "scenarios": [sc.to_dict() for sc in scenarios]}),
        "agent3_logical_tests.json": _envelope(s, "agent3_logical_tests", {
            "count": len(tests),
            "tests": [t.to_dict() for t in tests]}),
    }

    if snap is not None:
        artifacts["implementation_snapshot.json"] = _envelope(
            s, "implementation_snapshot", snap.to_dict())
        artifacts["agent3_conformance.json"] = _envelope(
            s, "agent3_conformance", conf)
        artifacts["agent3_executable_tests.json"] = _envelope(
            s, "agent3_executable_tests", {
                "report": exec_report,
                "tests": [t.to_dict() for t in exec_tests]})

    for name, payload in artifacts.items():
        (dest / name).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8")

    summary = {
        "survey_id": s.survey_id,
        "sample_size_supplied": s.sample_size,
        "anchors_supplied": sorted((project_inputs.get("anchors") or {}).keys()),
        "covered_without_a_separate_run": sum(
            1 for sc in scenarios if sc.covered_by),
        "targets": len(targets),
        "per_dimension": b1_report["per_dimension"],
        "feasible_witnesses": sum(1 for w in witnesses if w.feasible),
        "covered": sum(1 for sc in scenarios if sc.status == COVERED),
        "logical_tests": len(tests),
        "coverage_floor_pct": coverage["single_figure"]["value_pct"],
        "coverage_floor_dimension": coverage["single_figure"]["dimension"],
        "executable_tests": len(exec_tests),
        "executable_coverage_pct": exec_report["executable_coverage_pct"],
        "compilation_refused": exec_report["refused"],
        "conformance_verdict": (conf["verdict"] if conf else "NOT_RUN"),
        "conformance_blocking": (conf["blocking_count"] if conf else None),
        "semantics_provisional": sorted(sem.provisional),
        "specification_replay": (
            f"{replay['agreed']} agree / {replay['disagreed']} disagree / "
            f"{replay['unresolved']} unresolved of {replay['total']}"),
        "output_dir": str(dest),
        "coverage_vector": {k: f"{v['covered']}/{v['enumerated']} "
                               f"({v['logical_coverage_pct']}%) {v['enumeration_status']}"
                            for k, v in coverage["coverage_vector"].items()},
    }
    (dest / "agent3_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    target_dicts = [t.to_dict() for t in targets]
    witness_dicts = [w.to_dict() for w in witnesses]
    scenario_dicts = [sc.to_dict() for sc in scenarios]
    test_dicts = [t.to_dict() for t in tests]

    exec_dicts = [t.to_dict() for t in exec_tests]
    md = report.write_markdown(dest, summary, coverage, sem.summary(), replay,
                               b1_report, test_dicts, scenario_dicts,
                               target_dicts, conf, exec_report, exec_dicts)
    xl = report.write_workbook(dest, summary, coverage, target_dicts,
                               witness_dicts, scenario_dicts, test_dicts,
                               conf, exec_report, exec_dicts)
    pw = paths_workbook.build(
        dest / "agent3_test_cases_with_paths.xlsx", s, targets, scenarios,
        test_dicts, exec_dicts, snap, summary, paths, branches, path_report,
        conf)

    artifacts_extra = {
        "agent3_paths.json": _envelope(s, "agent3_paths", {
            "report": path_report,
            "branches": [b.to_dict() for b in branches],
            "paths": [p.to_dict() for p in paths]}),
    }
    for name, payload in artifacts_extra.items():
        (dest / name).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8")

    vb = qre_validation_workbook.build(
        dest / "agent3_test_cases_for_review.xlsx", s, targets, scenarios,
        test_dicts, exec_dicts, snap, summary, conf)
    summary["review_markdown"] = str(md)
    summary["review_workbook"] = str(xl)
    summary["test_cases_workbook"] = str(vb)
    summary["paths_workbook"] = str(pw)
    summary["paths"] = len(paths)
    summary["branch_states"] = (f"{path_report['branch_states_covered']}"
                                f"/{path_report['branch_states_total']}")
    summary["paths_exclusive"] = path_report["exclusive"]
    summary["paths_branch_exhaustive"] = path_report["branch_exhaustive"]
    return summary


def _replay(s, sem) -> dict:
    """Walk Agent 1's own acceptance scenarios through B3.

    Checks every expectation kind the QRE states, not only the ending:
    expected_end, expected_visible, expected_hidden and
    expected_validation_error. Checking only the ending would silently pass
    T6 and T7, whose entire point is a validation error with no ending at all.

    If B3 disagrees with a scenario the QRE author wrote themselves, either B3
    is wrong or the QRE contradicts itself. Both are worth knowing before a
    single test is designed, which is why this runs on every pass. Tracked
    outside the coverage vector because it measures agreement with the QRE's
    own examples, not behaviour coverage.
    """
    results = []
    agreed = 0
    unresolved_n = 0
    disagreed_n = 0
    for sc in s.scenarios:
        answers = {}
        for qid, raw in sc.inputs.items():
            q = s.question(qid)
            if q is None or isinstance(raw, dict):
                answers[qid] = raw
                continue
            if isinstance(raw, list):
                answers[qid] = [q.resolve(v) or v for v in raw]
            else:
                answers[qid] = q.resolve(raw) or raw

        state = b3_oracle.predict(s, answers, sem)
        seen = set(state.shown)
        errored = {v.get("question_id") for v in state.validation_triggered
                   if v.get("outcome") == "violated"}

        # Which questions had a rule B3 declined to evaluate. A check against
        # one of these is UNRESOLVED, not a disagreement. Turning "could not
        # evaluate" into "wrong" is the same sin as turning it into "right".
        unresolved_at: set[str] = set()
        for note in state.unresolved:
            rid = note.split(":")[0].strip()
            rule = s.rule(rid)
            if rule is not None and rule.evaluation_point:
                unresolved_at.add(rule.evaluation_point)
            q = s.question(rid)
            if q is not None:
                unresolved_at.add(q.id)

        def verdict(agrees: bool, target: str | None) -> str:
            if agrees:
                return "AGREE"
            if target and target in unresolved_at:
                return "UNRESOLVED"
            return "DISAGREE"

        checks = []
        if sc.expected_end is not None:
            a = state.ending == sc.expected_end
            checks.append({"kind": "expected_end", "expected": sc.expected_end,
                           "actual": state.ending,
                           "verdict": verdict(a, None)})
        for qid in sc.expected_visible:
            a = qid in seen
            checks.append({"kind": "expected_visible", "target": qid,
                           "actual": "visible" if a else "hidden",
                           "verdict": verdict(a, qid)})
        for qid in sc.expected_hidden:
            a = qid not in seen
            checks.append({"kind": "expected_hidden", "target": qid,
                           "actual": "hidden" if a else "visible",
                           "verdict": verdict(a, qid)})
        for qid in sc.expected_validation_error:
            a = qid in errored
            checks.append({"kind": "expected_validation_error", "target": qid,
                           "actual": ("error raised" if a else "no error raised"),
                           "verdict": verdict(a, qid)})

        verdicts = {c["verdict"] for c in checks}
        if not checks:
            outcome = "UNRESOLVED"
        elif "DISAGREE" in verdicts:
            outcome = "DISAGREE"
        elif "UNRESOLVED" in verdicts:
            outcome = "UNRESOLVED"
        else:
            outcome = "AGREE"

        agreed += 1 if outcome == "AGREE" else 0
        unresolved_n += 1 if outcome == "UNRESOLVED" else 0
        disagreed_n += 1 if outcome == "DISAGREE" else 0

        results.append({
            "scenario_id": sc.id,
            "purpose": sc.purpose,
            "inputs": sc.inputs,
            "outcome": outcome,
            "checks": checks,
            "problem_checks": [c for c in checks if c["verdict"] != "AGREE"],
            "path": state.path,
            "unresolved": state.unresolved,
        })
    return {"total": len(results), "agreed": agreed,
            "unresolved": unresolved_n, "disagreed": disagreed_n,
            "note": ("UNRESOLVED means B3 declined to evaluate a condition it "
                     "cannot read, which is not the same as disagreeing with "
                     "the QRE. Only DISAGREE indicates a real conflict."),
            "results": results}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    args = sys.argv[1:]
    lss = None
    if "--lss" in args:
        i = args.index("--lss")
        lss = args[i + 1]
        args = args[:i] + args[i + 2:]
    inputs = None
    if "--inputs" in args:
        i = args.index("--inputs")
        inputs = args[i + 1]
        args = args[:i] + args[i + 2:]
    size = None
    if "--sample-size" in args:
        i = args.index("--sample-size")
        size = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    for arg in args:
        out = run(arg, lss_path=lss, sample_size=size,
                  inputs_path=inputs)
        print(json.dumps(out, indent=2))
