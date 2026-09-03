"""Run the graph validation layer against S01 and C01's committed artifacts.

    python3 src/run_graph_validation.py [S01_campus_cafeteria_experience ...]

Reads `part2_canonical.json`, `part2_route_graph.json` and
`part2_graph_report.json` already on disk. No Stage 4, no Part 2, no model
call, no graph rebuild - the graph this validates is exactly the one Stage 8
already wrote.

Writes, per document:
    out/<stem>/part2_graph_validation.json
    out/<stem>/route_graph.graphml     out/<stem>/route_graph.gexf
    out/<stem>/dependency_graph.graphml  out/<stem>/dependency_graph.gexf
and one shared docs/graph_validation_report.md
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


from . import graph_validate
from . import orchestrator
from . import qre_oracle
from .models import SCHEMA_VERSION, ArtifactEnvelope, CanonicalSurvey

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "qre-samples"


def _load(out: Path, name: str):
    return orchestrator._read_content(out / name)


def _envelope(out: Path, name: str) -> dict:
    return json.loads((out / name).read_text(encoding="utf-8"))


def _write(path: Path, payload, *, artifact: str, stage: int, source: str) -> None:
    envelope = ArtifactEnvelope(
        schema_version=SCHEMA_VERSION, artifact=artifact, stage=stage,
        survey_id=Path(source).stem, source_document=orchestrator._source_for(source),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        item_count=None, content=payload,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope.model_dump(mode="json"), indent=2, default=str), encoding="utf-8")


def _structural_status(findings) -> str:
    if any(f.status == graph_validate.INCORRECT or f.status == graph_validate.MISSING for f in findings):
        return "NOT_READY"
    if any(f.status == graph_validate.WARNING for f in findings):
        return "READY_WITH_WARNINGS"
    return "READY"


def _behavioural_status(counts: dict) -> str:
    if counts.get(graph_validate.FAIL):
        return "NOT_READY"
    if counts.get(graph_validate.BLOCKED) or counts.get(graph_validate.UNVERIFIED):
        return "READY_WITH_WARNINGS"
    return "READY"


def _overall(structural: str, behavioural: str) -> str:
    order = {"NOT_READY": 0, "READY_WITH_WARNINGS": 1, "READY": 2}
    return min((structural, behavioural), key=lambda s: order[s])


def _agent3_input_status(sufficiency: dict) -> str:
    ready_values = {"READY", "READY_VIA_CANONICAL_SPEC"}
    categories = [v for k, v in sufficiency.items() if k != "canonical_spec_required_for"]
    return "READY" if all(v in ready_values for v in categories) else "NOT_READY"


def validate(stem: str, docx_path: Path | None = None) -> dict:
    docx = docx_path if docx_path is not None else FIXTURES / (stem + ".docx")
    out = ROOT / "out" / stem
    source_document = orchestrator._set_source(docx)

    survey = CanonicalSurvey.model_validate(_load(out, "part2_canonical.json"))
    route_graph_envelope = _envelope(out, "part2_route_graph.json")
    route_graphs_content = route_graph_envelope.get("content", route_graph_envelope)
    graph_report_content = _load(out, "part2_graph_report.json")
    route, dependency = graph_validate.load_route_graph(route_graphs_content)
    rule_map = route_graphs_content["rule_edge_map"]
    oracle = qre_oracle.read(docx)

    findings = graph_validate.structural_checks(survey, route, dependency, rule_map)
    coverage = graph_validate.coverage_from_findings(survey, findings)

    tests = graph_validate.build_behavioural_tests(survey, oracle)
    results = graph_validate.run_behavioural_tests(tests, survey, route, dependency)
    counts = Counter(r.status for r in results)

    sufficiency = graph_validate.agent3_sufficiency(survey, coverage)

    structural_status = _structural_status(findings)
    behavioural_status = _behavioural_status(counts)
    overall = _overall(structural_status, behavioural_status)
    agent3_input_status = _agent3_input_status(sufficiency)

    blockers = [asdict(f) for f in findings if f.status in (graph_validate.INCORRECT, graph_validate.MISSING)]
    warnings = [asdict(f) for f in findings if f.status == graph_validate.WARNING]
    warnings += [asdict(r) for r in results if r.status in (graph_validate.UNVERIFIED, graph_validate.BLOCKED)]

    payload = {
        "survey_id": stem,
        "source_document": {"filename": source_document.filename, "sha256": source_document.sha256},
        "graph_artifact": {
            "route_graph": "part2_route_graph.json",
            "graph_report": "part2_graph_report.json",
            "schema_version": route_graph_envelope.get("schema_version"),
            "generated_at": route_graph_envelope.get("generated_at"),
        },
        "validation_status": structural_status,
        "graph_readiness": overall,
        "node_coverage": coverage["node_preservation"],
        "edge_rule_coverage": {
            "routing_transition_preservation": coverage["routing_transition_preservation"],
            "skip_preservation": coverage["skip_preservation"],
            "termination_preservation": coverage["termination_preservation"],
        },
        "coverage_by_category": coverage,
        "behavioural_test_cases": [asdict(t) for t in tests],
        "behavioural_test_results": [asdict(r) for r in results],
        "test_counts": {
            "total": len(results),
            "PASS": counts.get(graph_validate.PASS, 0),
            "FAIL": counts.get(graph_validate.FAIL, 0),
            "UNVERIFIED": counts.get(graph_validate.UNVERIFIED, 0),
            "BLOCKED": counts.get(graph_validate.BLOCKED, 0),
        },
        "structural_findings": [asdict(f) for f in findings],
        "traceability_result": coverage["traceability"],
        "agent3_input_sufficiency": sufficiency,
        "agent3_input_status": agent3_input_status,
        "blockers": blockers,
        "warnings": warnings,
        "structural_graph_status": structural_status,
        "behavioural_graph_status": behavioural_status,
    }

    _write(out / "part2_graph_validation.json", payload,
           artifact="part2_graph_validation", stage=9, source=docx.name)

    exported = graph_validate.export_shareable_graphs(route, dependency, out)

    return {
        "stem": stem, "structural_status": structural_status, "behavioural_status": behavioural_status,
        "overall": overall, "agent3_input_status": agent3_input_status, "counts": payload["test_counts"],
        "coverage": coverage, "findings": findings, "results": results, "sufficiency": sufficiency,
        "graph_report": graph_report_content, "exported": exported,
    }


_METRIC_LABELS = [
    ("node_preservation", "Node preservation (A)"),
    ("routing_transition_preservation", "Routing / show transition (B)"),
    ("skip_preservation", "Skip logic (D)"),
    ("termination_preservation", "Termination (E)"),
    ("guard_preservation", "Display / guards (C)"),
    ("validation_reject_preservation", "Validation / reject rules (F)"),
    ("dependency_preservation", "Dependency / piping (G)"),
    ("randomization_preservation", "Randomization (H)"),
    ("quota_preservation", "Quotas (I)"),
    ("traceability", "Traceability (J)"),
]


def _pct(metric) -> str:
    if metric["denominator"] == 0:
        return "n/a"
    return "%d/%d (%.0f%%)" % (metric["numerator"], metric["denominator"], 100 * metric["result"])


def summary(reports: list[dict]) -> str:
    lines = ["# Graph validation report", "",
             "Whether the persisted NetworkX graph (`part2_route_graph.json`) faithfully",
             "represents the validated canonical specification, and whether walking it",
             "produces the behaviour the QRE itself expects. No model calls; no Stage 4 or",
             "Part 2 re-run - every check reads artifacts already on disk.", ""]

    overall_order = {"NOT_READY": 0, "READY_WITH_WARNINGS": 1, "READY": 2}
    overall_graph = min((r["overall"] for r in reports), key=lambda s: overall_order[s])
    overall_agent3 = "READY" if all(r["agent3_input_status"] == "READY" for r in reports) else "NOT_READY"

    lines += ["## Aggregate result", "",
              "**OVERALL GRAPH STATUS: %s**" % overall_graph, "",
              "**AGENT 3 INPUT STATUS: %s**" % overall_agent3, ""]

    lines += ["## Per survey", "",
              "| Survey | Structural | Behavioural | Tests | Pass | Fail | Unverified | Blocked | Agent 3 input |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in reports:
        c = r["counts"]
        lines.append("| %s | %s | %s | %d | %d | %d | %d | %d | %s |" % (
            r["stem"].split("_")[0], r["structural_status"], r["behavioural_status"],
            c["total"], c["PASS"], c["FAIL"], c["UNVERIFIED"], c["BLOCKED"], r["agent3_input_status"]))
    lines.append("")

    for r in reports:
        tag = r["stem"].split("_")[0]
        lines += ["## %s — %s" % (tag, r["stem"]), "",
                  "### Structural preservation, by category (A–J)", "",
                  "| Category | Coverage |", "|---|---|"]
        for key, label in _METRIC_LABELS:
            lines.append("| %s | %s |" % (label, _pct(r["coverage"][key])))
        lines.append("")

        if r["findings"]:
            lines += ["### Structural findings (%d)" % len(r["findings"]), "",
                      "| Category | Status | Finding |", "|---|---|---|"]
            for f in r["findings"]:
                lines.append("| %s | %s | %s |" % (f.category, f.status, f.finding))
            lines.append("")
        else:
            lines += ["### Structural findings", "", "None. Every node, edge, guard, dependency,",
                      "quota and metadata field checked matches the canonical specification.", ""]

        lines += ["### Behavioural tests", ""]
        fails = [x for x in r["results"] if x.status == "FAIL"]
        if fails:
            lines.append("**%d FAIL:**" % len(fails))
            for x in fails:
                lines.append("- `%s` [%s] %s — expected %r, got %r (%s)" % (
                    x.test_id, x.category, x.rule_or_question, x.expected, x.actual, x.explanation))
        unverified = [x for x in r["results"] if x.status == "UNVERIFIED"]
        if unverified:
            lines.append("\n%d UNVERIFIED (no independent oracle exists — needs a person):" % len(unverified))
            for x in unverified:
                lines.append("- `%s` [%s] %s" % (x.test_id, x.category, x.rule_or_question))
        if not fails and not unverified:
            lines.append("All behavioural tests PASS.")
        lines.append("")

        lines += ["### Agent 3 input sufficiency", "",
                  "| Test class | Status |", "|---|---|"]
        for key, value in r["sufficiency"].items():
            if key == "canonical_spec_required_for":
                continue
            lines.append("| %s | %s |" % (key.replace("_", " "), value))
        lines += ["", "Must be read from the canonical specification, not the graph:", ""]
        for item in r["sufficiency"]["canonical_spec_required_for"]:
            lines.append("- **%s** — %s" % (item["needs"], item["why"]))
        lines.append("")

        lines += ["### Shareable exports", ""]
        for path in r["exported"]:
            lines.append("- `%s`" % path.relative_to(ROOT).as_posix())
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str]) -> int:
    stems = argv[1:] or ["S01_campus_cafeteria_experience", "C01_chronic_care_patient_journey"]
    reports = []
    for stem in stems:
        report = validate(stem)
        reports.append(report)
        c = report["counts"]
        print("%-40s structural=%-20s behavioural=%-20s overall=%-20s agent3=%-10s "
              "pass=%d fail=%d unverified=%d blocked=%d" % (
                  stem, report["structural_status"], report["behavioural_status"], report["overall"],
                  report["agent3_input_status"], c["PASS"], c["FAIL"], c["UNVERIFIED"], c["BLOCKED"]),
              flush=True)
        for f in report["findings"]:
            print("    FINDING [%s] %s: %s" % (f.category, f.status, f.finding), flush=True)
        for x in report["results"]:
            if x.status == "FAIL":
                print("    FAIL %-6s %-14s %s: %s" % (x.test_id, x.category, x.rule_or_question, x.explanation),
                      flush=True)

    path = ROOT / "docs" / "graph_validation_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary(reports), encoding="utf-8")
    print("\nReport: %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
