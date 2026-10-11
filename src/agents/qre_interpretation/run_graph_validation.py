"""Stage 9: validate the graph Stage 8 wrote, called by the orchestrator.

Reads `part2_canonical.json`, `part2_route_graph.json` and
`part2_graph_report.json` already on disk. No Stage 4, no Part 2, no model
call, no graph rebuild - the graph this validates is exactly the one Stage 8
already wrote.

Writes, under out/<stem>/agent1/:
    part2_graph_validation.json
    route_graph.gexf                 (the dashboard's flow graph)
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


from src.common import paths
from . import graph_validate
from . import orchestrator
from . import qre_oracle
from .models import SCHEMA_VERSION, ArtifactEnvelope, CanonicalSurvey

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


def validate(stem: str, docx_path: Path) -> dict:
    docx = docx_path
    out = paths.agent1_out(stem)
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

    exported = graph_validate.export_route_graph(route, out)

    return {
        "stem": stem, "structural_status": structural_status, "behavioural_status": behavioural_status,
        "overall": overall, "agent3_input_status": agent3_input_status, "counts": payload["test_counts"],
        "coverage": coverage, "findings": findings, "results": results, "sufficiency": sufficiency,
        "graph_report": graph_report_content, "exported": exported,
    }
