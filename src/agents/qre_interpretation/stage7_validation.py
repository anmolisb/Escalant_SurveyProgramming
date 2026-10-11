"""Stage 7: the canonical validation and Agent 1 evaluation for one QRE.

Called by the orchestrator right after Part 2, with the document, the Stage 4
result and the canonical specification it already holds in memory.

Writes, under out/<stem>/agent1/:
    agent1_s7_evaluation_tests.json
    agent1_s7_evaluation_results.json
    agent1_s7_validation.json
    agent1_s7_decisions.json         (the decision register)
    agent1_s7_decision_register.md   (its human-readable form)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


from . import stage7_decisions
from . import stage7_tests
from src.common.llm import groq_client as llm
from src.common import paths
from . import orchestrator
from . import stage8_graph
from . import stage7_cross_check
from . import stage7_oracle
from .models import SCHEMA_VERSION, ArtifactEnvelope, CanonicalSurvey


def _write(path: Path, payload, *, artifact: str, stage: int, source: str) -> None:
    """Write one artifact inside the same header every other artifact carries.

    Not `orchestrator._write`: that one treats anything without `model_dump` as
    a sequence, so a dict payload comes back out as a list of its keys. These
    artifacts are reports rather than lists of records, so they need the dict
    kept whole.
    """
    envelope = ArtifactEnvelope(
        schema_version=SCHEMA_VERSION,
        artifact=artifact,
        stage=stage,
        survey_id=Path(source).stem,
        source_document=orchestrator._source_for(source),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        item_count=len(payload) if isinstance(payload, list) else None,
        content=payload,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(envelope.model_dump(mode="json"), indent=2, default=str),
        encoding="utf-8",
    )


def validate(stem: str, docx_path: Path, survey: CanonicalSurvey, stage4: dict) -> dict:
    """Validate one document's canonical output against the document itself.

    `stage4` is the Stage 4 result the orchestrator already holds, so nothing
    is read back from disk.
    """
    docx = docx_path
    out = paths.agent1_out(stem)
    source_document = orchestrator._set_source(docx)

    oracle = stage7_oracle.read(docx)

    tests = stage7_tests.build_tests(oracle)
    results = stage7_tests.run_tests(tests, survey, oracle)
    coverage = stage7_tests.coverage(results)

    cross = stage7_cross_check.cross_source(oracle, stage4, survey)
    gate = stage7_cross_check.confirmation_gate(survey, results)

    # The human decision register. Detected fresh every run from the
    # specification alone, then reconciled against whatever this document
    # already has on record - reusing a prior resolution when nothing that
    # could invalidate it has changed, and demoting it back to pending, loudly,
    # the moment the document or the model has.
    decisions_path = out / stage7_decisions.REGISTER_ARTIFACT
    existing_decisions = stage7_decisions.load_register(decisions_path)
    raw_decisions = stage7_decisions.detect(survey)
    decisions, decisions_summary = stage7_decisions.reconcile(
        existing_decisions, raw_decisions, stem, source_document, model=llm.get_model())
    stage7_decisions.save_register(decisions_path, decisions, stem, source_document)
    (out / stage7_decisions.REGISTER_MARKDOWN).write_text(
        stage7_decisions.to_markdown(decisions, stem, source_document), encoding="utf-8")
    gate = stage7_cross_check.attach_decision_ids(gate, decisions)

    # Build the graph rather than reasoning about whether it would build. Held
    # in memory: this is a check, and it must not overwrite the committed
    # artifact as a side effect of being run.
    _graphs, graph_report = stage8_graph.run(survey)
    graph = {
        "nodes": graph_report.nodes, "edges": graph_report.edges,
        "rules_mapped": "%d/%d" % (graph_report.rules_mapped, graph_report.rules_total),
        "quotas_mapped": "%d/%d" % (graph_report.quotas_mapped, graph_report.quotas_total),
        "dependency_edges": graph_report.dependency_edges,
        "passed": graph_report.passed, "blocking": graph_report.blocking,
        "findings": [f.model_dump(mode="json") for f in graph_report.findings],
    }
    decision = stage7_cross_check.verdict(results, cross, gate, graph, decisions)

    counts = {status: sum(1 for r in results if r.status == status)
              for status in ("PASS", "FAIL", "UNVERIFIED", "BLOCKED")}

    _write(out / paths.agent1_stage(7, "evaluation_tests.json"), stage7_tests.to_json(tests),
           artifact=paths.agent1_stage(7, "evaluation_tests"), stage=7, source=docx.name)
    _write(out / paths.agent1_stage(7, "evaluation_results.json"),
           {"counts": counts, "coverage": coverage, "results": stage7_tests.to_json(results)},
           artifact=paths.agent1_stage(7, "evaluation_results"), stage=7, source=docx.name)
    _write(out / paths.agent1_stage(7, "validation.json"),
           {"cross_source": cross, "graph": graph,
            "confirmation_required": gate,
            "decisions": {
                "register": stage7_decisions.REGISTER_ARTIFACT,
                "human_readable": stage7_decisions.REGISTER_MARKDOWN,
                "summary": decisions_summary,
            },
            "verdict": decision},
           artifact=paths.agent1_stage(7, "validation"), stage=7, source=docx.name)

    return {"stem": stem, "counts": counts, "coverage": coverage, "cross": cross,
            "gate": gate, "verdict": decision, "graph": graph,
            "decisions": decisions, "decisions_summary": decisions_summary,
            "tests": len(tests), "results": results}
