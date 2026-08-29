"""Run the canonical validation and Agent 1 evaluation over one or more QREs.

    python3 src/run_validation.py S01_campus_cafeteria_experience C01_chronic_care_patient_journey

Reads the document and the Stage 4 artifacts already on disk, so nothing here
re-runs extraction. Rebuilding the specification for the reproducibility check
goes through the decision record, so it costs no model calls.

Writes, per document:
    out/<stem>/agent1_evaluation_tests.json
    out/<stem>/agent1_evaluation_results.json
    out/<stem>/part2_validation.json
    out/<stem>/agent1_decisions.json           (the decision register)
    out/<stem>/agent1_decision_register.md     (its human-readable form)
and one shared docs/agent1_validation_summary.md
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent1_decisions
import agent1_eval
import llm
import orchestrator
import part2_canonical
import part2_graph
import part2_validate
import qre_oracle
from models import (
    SCHEMA_VERSION, AcceptanceScenario, ArtifactEnvelope, CanonicalSurvey,
    CompletionMessage, ExtractedStatement, Question, RoutingRule,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "qre-samples"


def _load(out: Path, name: str):
    path = out / name
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["content"] if isinstance(data, dict) and "content" in data else data


def _stage4(out: Path) -> dict:
    def rows(name, model):
        payload = _load(out, name)
        return [model.model_validate(r) for r in payload] if payload else []

    return {
        "questions": rows("stage4_questionnaire.json", Question),
        "routing": rows("stage4_routing.json", RoutingRule),
        "scenarios": rows("stage4_scenarios.json", AcceptanceScenario),
        "messages": rows("stage4_messages.json", CompletionMessage),
        "quotas": rows("stage4_quotas.json", ExtractedStatement),
        "study": rows("stage4_study.json", ExtractedStatement),
        "programming": rows("stage4_programming.json", ExtractedStatement),
    }


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


def validate(stem: str, docx_path: Path | None = None,
             survey: CanonicalSurvey | None = None) -> dict:
    """Validate one document's canonical output.

    `docx_path` defaults to the fixtures corpus, which is what the standalone
    CLI below needs. The orchestrator, validating whatever document it was
    just given rather than a fixture, passes the real path. `survey` lets a
    caller that already has the object in memory - the orchestrator, again -
    skip a redundant read of the file it just wrote; the standalone CLI has no
    such object yet and reads it from disk.
    """
    docx = docx_path if docx_path is not None else FIXTURES / (stem + ".docx")
    out = ROOT / "out" / stem
    # Points the decision record at this document, so the rebuild below reuses
    # the answers already on record instead of asking again.
    source_document = orchestrator._set_source(docx)

    oracle = qre_oracle.read(docx)
    stage4 = _stage4(out)
    if survey is None:
        survey = CanonicalSurvey.model_validate(_load(out, "part2_canonical.json"))

    tests = agent1_eval.build_tests(oracle)
    results = agent1_eval.run_tests(tests, survey, oracle)
    coverage = agent1_eval.coverage(results)

    cross = part2_validate.cross_source(oracle, stage4, survey)
    repro = part2_validate.reproducibility(
        lambda: part2_canonical.run(docx.name, stage4), runs=2)
    gate = part2_validate.confirmation_gate(survey, results)

    # The human decision register. Detected fresh every run from the
    # specification alone, then reconciled against whatever this document
    # already has on record - reusing a prior resolution when nothing that
    # could invalidate it has changed, and demoting it back to pending, loudly,
    # the moment the document or the model has.
    decisions_path = out / agent1_decisions.REGISTER_ARTIFACT
    existing_decisions = agent1_decisions.load_register(decisions_path)
    raw_decisions = agent1_decisions.detect(survey)
    decisions, decisions_summary = agent1_decisions.reconcile(
        existing_decisions, raw_decisions, stem, source_document, model=llm.get_model())
    agent1_decisions.save_register(decisions_path, decisions, stem, source_document)
    (out / agent1_decisions.REGISTER_MARKDOWN).write_text(
        agent1_decisions.to_markdown(decisions, stem, source_document), encoding="utf-8")
    gate = part2_validate.attach_decision_ids(gate, decisions)

    # Build the graph rather than reasoning about whether it would build. Held
    # in memory: this is a check, and it must not overwrite the committed
    # artifact as a side effect of being run.
    _graphs, graph_report = part2_graph.run(survey)
    graph = {
        "nodes": graph_report.nodes, "edges": graph_report.edges,
        "rules_mapped": "%d/%d" % (graph_report.rules_mapped, graph_report.rules_total),
        "quotas_mapped": "%d/%d" % (graph_report.quotas_mapped, graph_report.quotas_total),
        "dependency_edges": graph_report.dependency_edges,
        "passed": graph_report.passed, "blocking": graph_report.blocking,
        "findings": [f.model_dump(mode="json") for f in graph_report.findings],
    }
    decision = part2_validate.verdict(results, coverage, cross, repro, gate, graph, decisions)

    counts = {status: sum(1 for r in results if r.status == status)
              for status in ("PASS", "FAIL", "UNVERIFIED", "BLOCKED")}

    _write(out / "agent1_evaluation_tests.json", agent1_eval.to_json(tests),
           artifact="agent1_evaluation_tests", stage=7, source=docx.name)
    _write(out / "agent1_evaluation_results.json",
           {"counts": counts, "coverage": coverage, "results": agent1_eval.to_json(results)},
           artifact="agent1_evaluation_results", stage=7, source=docx.name)
    _write(out / "part2_validation.json",
           {"cross_source": cross, "reproducibility": repro, "graph": graph,
            "confirmation_required": gate,
            "decisions": {
                "register": agent1_decisions.REGISTER_ARTIFACT,
                "human_readable": agent1_decisions.REGISTER_MARKDOWN,
                "summary": decisions_summary,
            },
            "verdict": decision},
           artifact="part2_validation", stage=7, source=docx.name)

    return {"stem": stem, "counts": counts, "coverage": coverage, "cross": cross,
            "repro": repro, "gate": gate, "verdict": decision, "graph": graph,
            "decisions": decisions, "decisions_summary": decisions_summary,
            "tests": len(tests), "results": results}


_SUMMARY_METRICS = [
    ("question_coverage", "Questions"), ("question_type_coverage", "Question types"),
    ("option_coverage", "Options"), ("display_rule_coverage", "Display rules"),
    ("skip_rule_coverage", "Skip rules"), ("routing_rule_coverage", "Routing rules"),
    ("termination_coverage", "Termination"), ("validation_coverage", "Validation"),
    ("dependency_piping_coverage", "Dependencies / piping"),
    ("randomization_coverage", "Randomization"), ("quota_coverage", "Quotas"),
    ("disposition_coverage", "Dispositions"),
    ("acceptance_scenario_coverage", "Acceptance scenarios"),
    ("programming_requirement_coverage", "Programming requirements"),
    ("study_metadata_coverage", "Study metadata"), ("provenance_coverage", "Provenance"),
]


def _pct(metric) -> str:
    """Numerator, denominator and percentage, without rounding a miss into a pass.

    219 of 220 is 99.5%, and printing it as 100% would hide exactly the kind of
    single missed rule these metrics exist to surface.
    """
    if metric["denominator"] == 0:
        return "n/a"
    share = 100 * metric["result"]
    figure = "%.0f%%" % share if metric["numerator"] == metric["denominator"] else "%.1f%%" % share
    return "%d/%d (%s)%s" % (metric["numerator"], metric["denominator"], figure,
                             "" if metric["meets_target"] else " — below target")


def summary(reports: list[dict]) -> str:
    lines = ["# Agent 1 validation summary", "",
             "Canonical specification checked against the raw QRE, independently of the",
             "pipeline that produced it. Tests are derived from the document; where the",
             "document does not establish what the right answer is, the test is reported",
             "UNVERIFIED rather than passed.", ""]

    lines += ["## Verdict", "",
              "| Survey | Canonical | Human decision gate | Graph | Agent 3 | Tests | Pass | Fail | Unverified | Blocked |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for report in reports:
        counts, decision = report["counts"], report["verdict"]
        lines.append("| %s | %s | %s | %s | %s | %d | %d | %d | %d | %d |" % (
            report["stem"].split("_")[0], decision["canonical_status"],
            decision["human_decision_gate"], decision["graph_ready"], decision["agent3_ready"],
            report["tests"], counts["PASS"], counts["FAIL"],
            counts["UNVERIFIED"], counts["BLOCKED"]))
    lines.append("")

    for report in reports:
        tag = report["stem"].split("_")[0]
        decision, coverage = report["verdict"], report["coverage"]
        lines += ["## %s — %s" % (tag, report["stem"]), "",
                  "### Logic coverage", "",
                  "| Metric | Result | Target | Unverified (excluded) |", "|---|---|---|---|"]
        for key, label in _SUMMARY_METRICS:
            metric = coverage[key]
            lines.append("| %s | %s | %.0f%% | %d |" % (
                label, _pct(metric), 100 * metric["target"], metric["unverified_excluded"]))
        recall = coverage["critical_rule_recall"]
        lines += ["| **Critical-rule recall** | %s | %.0f%% | %d |" % (
            _pct(recall), 100 * recall["target"], recall["unverified_excluded"]), ""]
        lines += ["_Critical-rule recall covers executable logic only — display, skip,",
                  "routing, termination, validation, dependencies, quotas and randomization._", ""]

        graph = report["graph"]
        lines += ["### Graph build (measured, not assumed)", "",
                  "- %d nodes, %d edges; rules mapped %s; quotas mapped %s; %d dependency edges"
                  % (graph["nodes"], graph["edges"], graph["rules_mapped"],
                     graph["quotas_mapped"], graph["dependency_edges"]),
                  "- Fidelity check: **%s** (%d blocking)"
                  % ("passed" if graph["passed"] else "failed", graph["blocking"]), ""]

        repro = report["repro"]
        lines += ["### Reproducibility", "",
                  "- Exact: **%s**" % ("identical" if repro["exact_reproducible"] else "differs"),
                  "- Semantic: **%s**" % ("identical" if repro["semantic_reproducible"] else "differs"),
                  "- Meaningful differences: %s" % (
                      ", ".join(repro["meaningful_differences"]) or "none"), ""]

        cross = report["cross"]
        lines += ["### Cross-source checks", ""]
        if cross:
            lines.append("| Check | Severity | Finding |")
            lines.append("|---|---|---|")
            for finding in cross[:12]:
                lines.append("| %s | %s | %s |" % (
                    finding["check"], finding["severity"], finding["finding"]))
            if len(cross) > 12:
                lines.append("| … | | %d more |" % (len(cross) - 12))
        else:
            lines.append("No missing, contradictory, unsupported or invented content found.")
        lines.append("")

        gate = report["gate"]
        lines += ["### CONFIRMATION_REQUIRED (%d)" % len(gate), ""]
        for entry in gate:
            lines += ["**%s** — affects %s" % (entry["issue"], ", ".join(entry["affected"]) or "the survey"),
                      "", "- Why it matters: %s" % entry["why_it_matters"],
                      "- Changes downstream: %s" % entry["changes_downstream"],
                      "- Decision IDs: %s" % (", ".join(entry.get("decision_ids", [])) or "—"), ""]

        ds = report["decisions_summary"]
        lines += ["### Human decision register", "",
                  "- %d total: %d pending, %d resolved, %d not required"
                  % (ds["total"], ds["pending"], ds["resolved"], ds["not_required"]),
                  "- raised this run: %d · resolved decisions reused: %d · "
                  "moved to not-required: %d · invalidated by a changed context: %d"
                  % (ds["raised_this_run"], ds["resolved_reused"],
                     ds["newly_transitioned_not_required"], ds["context_changed"]),
                  "- blocking and still pending: %s" % (", ".join(ds["blocking_pending"]) or "none"),
                  "- full register: `out/%s/%s` · human-readable: `out/%s/%s`"
                  % (report["stem"], agent1_decisions.REGISTER_ARTIFACT,
                     report["stem"], agent1_decisions.REGISTER_MARKDOWN),
                  ""]

        lines += ["### Top issues", ""]
        issues = (decision["what_is_incorrect"] + decision["what_is_missing"])[:8]
        if issues:
            for issue in issues:
                lines.append("- %s" % issue)
        else:
            lines.append("- No incorrect or missing content. Everything outstanding is a decision, above.")
        lines.append("")
        if decision["what_must_change"]:
            lines += ["### What must change", ""]
            for item in decision["what_must_change"]:
                lines.append("- %s" % item)
            lines.append("")
        if decision["agent3_ready"] == "NO":
            lines += ["Agent 3 is blocked by: %s" % ", ".join(decision["agent3_blocked_by"]), ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    stems = argv[1:] or ["S01_campus_cafeteria_experience", "C01_chronic_care_patient_journey"]
    reports = []
    for stem in stems:
        report = validate(stem)
        reports.append(report)
        decision, counts, ds = report["verdict"], report["counts"], report["decisions_summary"]
        print("%-40s %-22s gate=%-25s graph=%-3s agent3=%-3s  pass=%d fail=%d unverified=%d blocked=%d" % (
            stem, decision["canonical_status"], decision["human_decision_gate"],
            decision["graph_ready"], decision["agent3_ready"], counts["PASS"], counts["FAIL"],
            counts["UNVERIFIED"], counts["BLOCKED"]), flush=True)
        print("    decisions: %d total (%d pending, %d resolved, %d not required) — "
              "raised %d, reused %d, context-changed %d"
              % (ds["total"], ds["pending"], ds["resolved"], ds["not_required"],
                 ds["raised_this_run"], ds["resolved_reused"], ds["context_changed"]), flush=True)
        for failure in [r for r in report["results"] if r.status == "FAIL"][:10]:
            print("    FAIL %-6s %-22s %s" % (failure.test_id, failure.category,
                                              failure.explanation), flush=True)
        for finding in report["cross"][:8]:
            print("    CROSS %-26s %s" % (finding["check"], finding["finding"]), flush=True)

    path = ROOT / "docs" / "agent1_validation_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary(reports), encoding="utf-8")
    print("\nSummary: %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
