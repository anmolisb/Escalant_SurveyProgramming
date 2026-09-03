"""Orchestrator. Runs the four stages, writing each artifact to disk.

    python3 src/orchestrator.py <file.docx> [--from-stage N]

Every stage reads only the previous stage's artifact, so any stage can be re-run
on its own:

    python3 src/orchestrator.py doc.docx --from-stage 4

re-runs the deep parse against the existing stage3 files without re-reading the
DOCX or re-calling the model for stages 2 and 3.

Artifacts, under out/<document stem>/, in the order the pipeline actually
produces them:
    stage1_document.json
    stage2_blocks.json      stage2_flags.json
    stage3_<target>.json    (one per matched target)
    stage4_<target>.json    stage4_flags.json
    stage5_audit.json
    part2_canonical.json             (Part 2 — what the QRE means)
    agent1_evaluation_tests.json     (Stage 7 — validation, always run)
    agent1_evaluation_results.json
    part2_validation.json
    agent1_decisions.json            (the human decision register)
    agent1_decision_register.md      (its human-readable form)
    part2_route_graph.json           (Stage 8 — the graph builder, always run)
    part2_graph_report.json
    part2_graph_validation.json      (Stage 9 — graph validation, always run)
    route_graph.graphml  route_graph.gexf
    dependency_graph.graphml  dependency_graph.gexf
    agent1_stage9_gate.json          (Agent 3 execution approval, computed last)

Targets: questionnaire, routing, scenarios, messages, quotas, study,
programming. A target absent from the document is flagged, not fatal.

Stage 7 runs on every call, right after the canonical specification exists -
not as a separate command a person has to remember to run. It checks the
canonical output against the raw document independently, and writes
`part2_validation.json` next to `part2_canonical.json`. Its verdict is a gate:
`main` exits 0 only when `canonical_status` is not FAILED.

Part of Stage 7 is a persistent decision register. Anything Part 2 could only
infer, derive or guess at - not what the document plainly states - is written
to `agent1_decisions.json`, one entry per decision, and reused unchanged on
the next run as long as the document and the reading it depends on have not
moved. A project owner resolves one by hand-editing its entry (`status`,
`decision`, `decision_provenance`) and re-running; nothing in this pipeline
resolves a decision on its own. `human_decision_gate` in the validation
verdict is CLEAR only once every BLOCKING decision has been resolved this way.

Stage 8, the graph builder, runs after Stage 7 and always - it needs no
model, and nothing about how it builds depends on Stage 7's verdict. What
does depend on that verdict is what `part2_graph_report.json` is allowed to
say about the result: `structurally_buildable` is a fact about the graph
alone, true the moment it builds and passes its own fidelity checks;
`behaviorally_approved` additionally requires `canonical_status` not FAILED
and `human_decision_gate` CLEAR, and is `null` rather than a guess when
nobody supplied a verdict to judge it against.

Stage 9, graph validation, runs after Stage 8 and always - proving the
persisted graph is faithful to the specification and, where a condition is
formally readable, behaves correctly when walked. It writes
`part2_graph_validation.json` and the GraphML/GEXF exports, reusing exactly
what Stages 6 and 8 already wrote - no Stage 4 rerun, no model call, nothing
regenerated. Its own verdict answers one question only:
`GRAPH_INPUT_SUFFICIENCY` - is the graph, together with the canonical
specification, structurally and behaviourally enough for Agent 3 to build
tests from. It does not, and structurally cannot, answer the separate
question of whether Agent 3 may actually proceed: `AGENT3_EXECUTION_APPROVAL`
is computed by `main` afterward, as the plain conjunction of Stage 7's two
verdicts and Stage 9's one - never by Stage 9 alone, and never in a way that
lets a sufficient graph stand in for a human decision nobody has made yet.
`agent1_stage9_gate.json` records that conjunction; it is additive, sits
beside the other two artifacts, and changes nothing about how either of them
is written.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


from src.common.llm import groq_client as llm
from . import stage1_ingestion
from . import stage2_headings
from . import stage3_raw_json
from . import stage4_deep_parse
from . import stage5_audit
from . import part2_canonical
from . import part2_graph
# Not imported at module level: run_validation imports this module to reuse
# _set_source, so importing it up here would be a cycle. Imported inside
# run_agent1_validation instead, by which point this module has finished
# loading.
from .models import (
    SCHEMA_VERSION,
    ArtifactEnvelope,
    FlagSeverity,
    Paragraph,
    ReviewFlag,
    SourceDocument,
    Stage1Document,
    Stage2Blocks,
    Stage3Block,
    CanonicalSurvey,
    GraphReport,
    RouteGraphs,
    Stage5Audit,
    TargetHeading,
)

OUT_ROOT = Path(__file__).resolve().parents[3] / "out"

#: Filename-safe stem per target.
_SLUG = {
    TargetHeading.QUESTIONNAIRE: "questionnaire",
    TargetHeading.ROUTING_AND_TERMINATION: "routing",
    TargetHeading.ACCEPTANCE_TEST_SCENARIOS: "scenarios",
    TargetHeading.COMPLETION_MESSAGES: "messages",
    TargetHeading.QUOTA_CONTROLS: "quotas",
    TargetHeading.STUDY_SPECIFICATION: "study",
    TargetHeading.PROGRAMMING_AND_QA: "programming",
}


#: The QRE the current run is reading, set by `main` before any stage runs.
#: A module-level holder rather than an extra argument on every `run_stage*`,
#: because the digest is a property of the run, not of any one stage, and
#: threading it through four signatures would say otherwise.
_SOURCE: SourceDocument | None = None


def _set_source(docx_path: Path) -> SourceDocument:
    """Record which document this run is reading, and its digest.

    Also points the model's decision record at this document's output folder, so
    a reading the model gave once is reused rather than asked again. Every stage
    that calls a model goes through `llm.complete`, so one hook here covers all
    of them.
    """
    global _SOURCE
    llm.use_cache(_out_dir(docx_path.name))
    if docx_path.exists():
        raw = docx_path.read_bytes()
        _SOURCE = SourceDocument(
            filename=docx_path.name,
            sha256=hashlib.sha256(raw).hexdigest(),
            bytes=len(raw),
        )
    else:
        # `--from-stage N` can name a document that is not on this machine; the
        # saved artifacts are enough to continue. Record the name, admit there
        # is no digest, rather than inventing one.
        _SOURCE = SourceDocument(filename=docx_path.name)
    return _SOURCE


def _source_for(document_name: str) -> SourceDocument:
    return _SOURCE or SourceDocument(filename=document_name)


def _write(path: Path, payload, *, artifact: str, stage: int, source: str) -> Path:
    """Write one artifact inside a header naming the run that produced it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        content = payload.model_dump(mode="json")
        item_count = None
    else:
        content = [
            p.model_dump(mode="json") if hasattr(p, "model_dump") else p
            for p in payload
        ]
        item_count = len(content)

    envelope = ArtifactEnvelope(
        schema_version=SCHEMA_VERSION,
        artifact=artifact,
        stage=stage,
        survey_id=Path(source).stem,
        source_document=_source_for(source),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        item_count=item_count,
        content=content,
    )
    path.write_text(
        json.dumps(envelope.model_dump(mode="json"), indent=2, default=str)
    )
    return path


#: Fields dropped from Stage 4's files. `source_reference` is provenance for a
#: reader of the pipeline, not part of the survey definition, and Stage 4's
#: files are the survey builder's input.
_STAGE4_OMIT = {"source_reference"}


def _write_bare(path: Path, payload) -> Path:
    """Write Stage 4's records with no envelope and no per-item provenance.

    Every other stage keeps both. Stage 4 is the handover point to the survey
    builder, and there the header and the source references are weight the
    consumer has to step over rather than anything it uses.

    Nothing in memory changes. Stage 5 and Part 2 are handed the objects
    directly, not the file, so both still see full provenance and
    `part2_canonical.json` still carries a source reference for every item.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        content = payload.model_dump(mode="json", exclude=_STAGE4_OMIT)
    else:
        content = [
            item.model_dump(mode="json", exclude=_STAGE4_OMIT)
            if hasattr(item, "model_dump")
            else item
            for item in payload
        ]
    path.write_text(json.dumps(content, indent=2, default=str))
    return path


def _read_content(path: Path):
    """Unwrap an artifact, tolerating one written before headers existed."""
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "schema_version" in data and "content" in data:
        return data["content"]
    return data


def _out_dir(document: str) -> Path:
    return OUT_ROOT / Path(document).stem


def run_stage1(docx_path: Path) -> Stage1Document:
    document = stage1_ingestion.run(docx_path)
    _write(
        _out_dir(docx_path.name) / "stage1_document.json",
        document,
        artifact="stage1_document",
        stage=1,
        source=docx_path.name,
    )
    return document


def run_stage2(document: Stage1Document) -> Stage2Blocks:
    blocks = stage2_headings.run(document)
    out = _out_dir(document.source)
    _write(
        out / "stage2_blocks.json",
        blocks,
        artifact="stage2_blocks",
        stage=2,
        source=document.source,
    )
    _write(
        out / "stage2_flags.json",
        blocks.flags,
        artifact="stage2_flags",
        stage=2,
        source=document.source,
    )
    return blocks


def run_stage3(stage2: Stage2Blocks) -> tuple[list[Stage3Block], list[ReviewFlag]]:
    blocks, flags = stage3_raw_json.run(stage2)
    out = _out_dir(stage2.source)
    for block in blocks:
        _write(
            out / f"stage3_{_SLUG[block.target]}.json",
            block,
            artifact=f"stage3_{_SLUG[block.target]}",
            stage=3,
            source=stage2.source,
        )
    # Always written, even when empty: an absent file is ambiguous between
    # "no flags" and "stage did not run".
    _write(
        out / "stage3_flags.json",
        flags,
        artifact="stage3_flags",
        stage=3,
        source=stage2.source,
    )
    return blocks, flags


def _front_matter(document: Stage1Document) -> list[Paragraph]:
    """The paragraphs above the first heading.

    They belong to no section, so Stage 2 hands them to no target and Stage 5
    reports them as uncovered. They are still where the title and the study id
    are written, so Stage 4 is given them from the Stage 1 record directly
    rather than a heading being invented for lines that do not have one.
    """
    front: list[Paragraph] = []
    for block in document.blocks:
        if getattr(block, "heading_level", None):
            break
        if isinstance(block, Paragraph):
            front.append(block)
    return front


def run_stage4(
    source: str, blocks: list[Stage3Block], front_matter: list[Paragraph]
) -> tuple[dict, list[ReviewFlag]]:
    parsed, flags = stage4_deep_parse.run(blocks, source, front_matter)
    out = _out_dir(source)
    for key, slug in (
        ("questions", "questionnaire"),
        ("routing", "routing"),
        ("scenarios", "scenarios"),
        ("messages", "messages"),
        ("quotas", "quotas"),
        ("study", "study"),
        ("programming", "programming"),
    ):
        _write_bare(out / f"stage4_{slug}.json", parsed[key])
    _write_bare(out / "stage4_survey.json", parsed["survey"])
    _write_bare(out / "stage4_flags.json", flags)
    return parsed, flags


def run_stage5(
    document: Stage1Document,
    stage2: Stage2Blocks,
    stage3: list[Stage3Block],
    parsed: dict,
) -> Stage5Audit:
    """Audit Stage 4 against what produced it.

    Written as one artifact rather than appended to `stage4_flags.json`. The
    README left that open; keeping them apart preserves which of the two you are
    reading — a Stage 4 flag is trouble that stage hit while working, an audit
    finding is a disagreement between artifacts that each looked fine alone.
    """
    audit = stage5_audit.run(document, stage2, stage3, parsed)
    _write(
        _out_dir(document.source) / "stage5_audit.json",
        audit,
        artifact="stage5_audit",
        stage=5,
        source=document.source,
    )
    return audit


def run_part2(source: str, parsed: dict) -> CanonicalSurvey:
    """Build the canonical specification: what the QRE means.

    A separate artifact from Part 1's, not a replacement for them. Part 1's
    files stay the record of what the document says, so a disagreement about
    interpretation never costs us the extraction.
    """
    survey = part2_canonical.run(source, parsed)
    _write(
        _out_dir(source) / "part2_canonical.json",
        survey,
        artifact="part2_canonical",
        stage=6,
        source=source,
    )
    return survey


def run_graphs(
    source: str, survey: CanonicalSurvey, validation_report: dict | None = None,
) -> tuple[RouteGraphs, GraphReport]:
    """Stage 8 - build the route and dependency graphs, last, and say plainly
    whether this one may be trusted for downstream use.

    Runs after Stage 7's validation and human-decision gate, not before -
    the graph builder needs no model and nothing about it depends on the
    verdict, but the verdict is what decides `behaviorally_approved`, and a
    graph that has not been told the verdict can only ever say it does not
    know. `main` always has one to pass by the time it calls this; a caller
    building a graph on its own, without running Stage 7 first, gets a graph
    that says exactly that - `behaviorally_approved: null` - rather than a
    guess dressed up as an answer.
    """
    canonical_status = human_decision_gate = None
    if validation_report is not None:
        verdict = validation_report["verdict"]
        canonical_status = verdict["canonical_status"]
        human_decision_gate = verdict["human_decision_gate"]

    graphs, report = part2_graph.run(
        survey, canonical_status=canonical_status, human_decision_gate=human_decision_gate,
    )
    out = _out_dir(source)
    _write(
        out / "part2_route_graph.json",
        graphs,
        artifact="part2_route_graph",
        stage=8,
        source=source,
    )
    _write(
        out / "part2_graph_report.json",
        report,
        artifact="part2_graph_report",
        stage=8,
        source=source,
    )
    return graphs, report


def run_graph_validation(docx_path: Path, source: str) -> dict:
    """Stage 9 - prove the persisted graph is faithful to the specification,
    and that walking it behaves the way the QRE says it should. Always run,
    right after Stage 8.

    Reads `part2_canonical.json` and `part2_route_graph.json` straight off
    disk - exactly what Stages 6 and 8 just wrote - and calls no model. The
    graph-validation implementation itself (`graph_validate.py`,
    `run_graph_validation.py`) is untouched by this wiring; this only calls
    it on every run instead of leaving it as a script someone has to
    remember to invoke.

    Returns Stage 9's own report, which answers exactly one question -
    `GRAPH_INPUT_SUFFICIENCY`, is the graph plus the specification enough for
    Agent 3 to build tests from. It does not, and must not, answer whether
    Agent 3 may actually proceed; that needs Stage 7's verdict too, and is
    computed by `agent3_execution_approval` below, never inside this stage.
    """
    import run_graph_validation  # deferred: it imports this module too

    return run_graph_validation.validate(Path(source).stem, docx_path=docx_path)


def agent3_execution_approval(validation_report: dict, graph_validation_report: dict) -> dict:
    """AGENT3_EXECUTION_APPROVAL - the plain conjunction of Stage 7's two
    verdicts and Stage 9's one, computed here and nowhere inside either
    stage's own code.

    Three conditions, all required, none of them able to stand in for
    another:

        canonical validation has no blocking defect   (Stage 7)
        human decision gate has no pending BLOCKING    (Stage 7)
        graph validation passes sufficiently            (Stage 9)

    A structurally sound, behaviourally correct, input-sufficient graph is
    still not an approval by itself - it is one of three conditions, and the
    other two belong to a human, not to this function. Nothing here resolves
    a decision or reruns anything; it only reads what the two stages already
    decided and reports whether every gate stands open at once.
    """
    verdict = validation_report["verdict"]
    canonical_ok = verdict["canonical_status"] != "FAILED"
    decisions_clear = verdict["human_decision_gate"] == "CLEAR"
    # "Passes sufficiently": structurally and behaviourally not NOT_READY, and
    # the graph judged input-sufficient for Agent 3 to build tests from at
    # all. A FAIL anywhere in Stage 9 - a real defect, not an open question -
    # blocks this exactly the way a canonical defect does.
    graph_ok = (
        graph_validation_report["overall"] in ("READY", "READY_WITH_WARNINGS")
        and graph_validation_report["agent3_input_status"] == "READY"
    )

    blocked_by = []
    if not canonical_ok:
        blocked_by.append("canonical_status=%s" % verdict["canonical_status"])
    if not decisions_clear:
        blocked_by.append("human_decision_gate=PENDING_BLOCKING_DECISIONS")
    if not graph_ok:
        blocked_by.append(
            "graph_validation=%s" % graph_validation_report["overall"]
            if graph_validation_report["overall"] not in ("READY", "READY_WITH_WARNINGS")
            else "agent3_input_status=NOT_READY"
        )

    return {
        "graph_input_sufficiency": graph_validation_report["agent3_input_status"],
        "status": "APPROVED" if (canonical_ok and decisions_clear and graph_ok) else "BLOCKED",
        "canonical_validation_clear": canonical_ok,
        "human_decision_gate_clear": decisions_clear,
        "graph_validation_passed": graph_ok,
        "blocked_by": blocked_by,
    }


def write_stage9_gate(source: str, survey_id: str, gate: dict) -> Path:
    """Persist AGENT3_EXECUTION_APPROVAL beside the artifacts it was computed
    from, without touching either of them.

    A dict payload, not a model, so this uses its own small envelope rather
    than `_write` - the same reason `run_validation.py` and
    `run_graph_validation.py` each keep their own: `_write` below treats
    anything without `model_dump` as a list of records, which would turn this
    single object into a list of its own keys.
    """
    path = _out_dir(source) / "agent1_stage9_gate.json"
    envelope = ArtifactEnvelope(
        schema_version=SCHEMA_VERSION, artifact="agent1_stage9_gate", stage=9,
        survey_id=survey_id, source_document=_source_for(source),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        item_count=None, content=gate,
    )
    path.write_text(json.dumps(envelope.model_dump(mode="json"), indent=2, default=str), encoding="utf-8")
    return path


def run_agent1_validation(docx_path: Path, source: str, survey: CanonicalSurvey) -> dict:
    """Stage 7 - check the canonical output against the raw document, always.

    Not a separate command. Every call to `main` reaches this right after the
    canonical specification exists and before the graph is built, so a
    validation report is never more than one run of the pipeline out of date,
    and the graph builder that follows always has a fresh verdict to consult.

    Rebuilds an oracle reading of the document and re-derives the reproducibility
    comparison, both of which cost model calls only the first time a document is
    seen - after that, `llm.py`'s decision record answers every prompt this
    needs, so validating on every call is not validating for free but it is
    validating for nearly free.
    """
    import run_validation  # deferred: see the note where this module is imported

    return run_validation.validate(Path(source).stem, docx_path=docx_path, survey=survey)


# ---------------------------------------------------------------------------
# Re-entry: load a previous stage's artifact instead of recomputing it
# ---------------------------------------------------------------------------


def load_stage1(source: str) -> Stage1Document:
    path = _out_dir(source) / "stage1_document.json"
    return Stage1Document.model_validate(_read_content(path))


def load_stage2(source: str) -> Stage2Blocks:
    path = _out_dir(source) / "stage2_blocks.json"
    return Stage2Blocks.model_validate(_read_content(path))


def load_stage3(source: str) -> list[Stage3Block]:
    out = _out_dir(source)
    return [
        Stage3Block.model_validate(_read_content(p))
        for p in sorted(out.glob("stage3_*.json"))
        if p.name != "stage3_flags.json"
    ]


def _summarise(blocks: Stage2Blocks, stage3: list[Stage3Block], parsed: dict, flags):
    info = parsed["survey"]
    print(f"\nSURVEY  {info.qre_id or '?'} — {info.title or '(no title)'}")
    absent = [
        name
        for name in ("title", "description", "welcome_text")
        if getattr(info, name) is None
    ]
    if absent:
        print(f"        not stated: {', '.join(absent)}")
    print(f"\n{'TARGET':<28} {'MATCHED BY':<11} {'RAW ROWS':>9} {'PARSED':>7}")
    print("-" * 60)
    counts = {
        TargetHeading.QUESTIONNAIRE: len(parsed["questions"]),
        TargetHeading.ROUTING_AND_TERMINATION: len(parsed["routing"]),
        TargetHeading.ACCEPTANCE_TEST_SCENARIOS: len(parsed["scenarios"]),
        TargetHeading.COMPLETION_MESSAGES: len(parsed["messages"]),
        TargetHeading.QUOTA_CONTROLS: len(parsed["quotas"]),
        TargetHeading.STUDY_SPECIFICATION: len(parsed["study"]),
        TargetHeading.PROGRAMMING_AND_QA: len(parsed["programming"]),
    }
    raw = {b.target: len(b.rows) for b in stage3}
    matched = {b.target: b.matched_by for b in blocks.blocks}
    for target in TargetHeading:
        print(
            f"{target.value:<28} {matched.get(target, '—'):<11} "
            f"{raw.get(target, 0):>9} {counts[target]:>7}"
        )

    all_flags = [*blocks.flags, *flags]
    if all_flags:
        blocking = sum(1 for f in all_flags if f.severity is FlagSeverity.BLOCKING)
        print(f"\nREVIEW FLAGS — {len(all_flags)} ({blocking} blocking)")
        # Blocking first: a run with fifty warnings and one blocker should not
        # bury the blocker fifty lines down.
        for flag in sorted(all_flags, key=lambda f: f.severity is not FlagSeverity.BLOCKING):
            confidence = f" ({flag.confidence:.2f})" if flag.confidence else ""
            candidate = f" -> {flag.candidate_heading}" if flag.candidate_heading else ""
            target = f" {flag.target.kind}:{flag.target.id}" if flag.target else ""
            print(
                f"  [{flag.severity.value:<8}] {flag.target_heading.value}"
                f"{target}{candidate}{confidence}"
            )
            print(f"      {flag.reasoning}")
    else:
        print("\nREVIEW FLAGS — none")


def _summarise_audit(audit: Stage5Audit) -> None:
    print(f"\nSTAGE 5 AUDIT — {'PASS' if audit.passed else 'FAIL'}")
    print(f"{'SECTION':<28} {'ROWS':>5} {'IDENT':>6} {'SCORE':>7} {'':>5}")
    print("-" * 55)
    for score in audit.sections:
        mark = "ok" if score.passed else "BELOW"
        print(
            f"{score.target.value[:28]:<28} {score.rows_in:>5} {score.identified:>6} "
            f"{score.score:>6.0%} {mark:>6}"
        )
    if audit.findings:
        print(f"\nFINDINGS — {len(audit.findings)} ({audit.blocking} blocking)")
        for f in sorted(
            audit.findings, key=lambda f: f.severity is not FlagSeverity.BLOCKING
        ):
            target = f" {f.target.kind}:{f.target.id}" if f.target else ""
            print(f"  [{f.severity.value:<8}] {f.check}{target}")
            print(f"      {f.finding}")
    else:
        print("\nFINDINGS — none. All five checks ran and found nothing.")


def _summarise_part2(survey: CanonicalSurvey) -> None:
    from collections import Counter

    readable = sum(1 for r in survey.rules if r.when is not None)
    kinds = Counter(r.destination.kind.value for r in survey.rules)
    guards = Counter(q.guard.agreement.value for q in survey.questions if q.guard)
    blocking = sum(
        1 for r in survey.review if r.severity is FlagSeverity.BLOCKING
    )
    print("\nPART 2 — CANONICAL SPECIFICATION")
    print(f"  rules            {len(survey.rules)} ({readable} conditions read)")
    print(f"  destinations     {dict(kinds)}")
    print(f"  guards           {dict(guards)}")
    print(f"  dependencies     {len(survey.dependencies)}")
    print(f"  randomised       {len(survey.randomization)}")
    print(f"  review           {len(survey.review)} ({blocking} blocking)")


def _summarise_graphs(report: GraphReport) -> None:
    print("\nSTAGE 8 — GRAPH BUILDER")
    print(f"  nodes            {report.nodes} ({report.questions} questions, {report.dispositions} endings)")
    print(f"  edges            {report.edges}")
    print(f"  rules mapped     {report.rules_mapped}/{report.rules_total}")
    print(f"  quotas mapped    {report.quotas_mapped}/{report.quotas_total}")
    print(f"  dependency edges {report.dependency_edges}")
    print(f"  check            {'PASS' if report.passed else 'FAIL'} ({report.blocking} blocking, {len(report.findings)} findings)")
    for f in report.findings:
        print(f"    [{f.severity.value:<8}] {f.check}: {f.finding}")
    print("  coverage by category:")
    for name, metric in report.coverage.items():
        shown = "n/a" if metric["result"] is None else f"{metric['numerator']}/{metric['denominator']}"
        print(f"    {name:<32} {shown}")
    print(f"  GRAPH_STRUCTURALLY_BUILDABLE  {'YES' if report.structurally_buildable else 'NO'}")
    approved = report.behaviorally_approved
    print(f"  GRAPH_BEHAVIORALLY_APPROVED   {'YES' if approved else ('NO' if approved is False else 'UNKNOWN')}")
    if report.approval_blocked_by:
        print(f"    blocked by: {', '.join(report.approval_blocked_by)}")


def _summarise_validation(report: dict) -> bool:
    """Print the gate's verdict plainly, and say whether the run may exit 0.

    Returns False on anything but a clean pass, which `main` turns into a
    non-zero exit code - the mechanical half of "do not silently pass a
    blocking canonical output to the graph builder". The graph artifacts are
    still written either way, same as Stage 5's audit never withheld Stage 4's
    output; what changes is whether the run that produced them reports success.
    """
    verdict = report["verdict"]
    counts = report["counts"]
    status = verdict["canonical_status"]
    print("\nSTAGE 7 — AGENT 1 VALIDATION")
    print(f"  tests            {sum(counts.values())} "
          f"(pass {counts['PASS']}, fail {counts['FAIL']}, "
          f"unverified {counts['UNVERIFIED']}, blocked {counts['BLOCKED']})")
    print(f"  canonical status {status}")
    print(f"  human decisions  {verdict['human_decision_gate']}")
    print(f"  graph ready      {verdict['graph_ready']}")
    print(f"  agent 3 ready    {verdict['agent3_ready']}")
    if verdict["pending_blocking_decisions"]:
        print(f"  pending blocking decisions: {len(verdict['pending_blocking_decisions'])} "
              f"(see agent1_decision_register.md)")
    if verdict["agent3_blocked_by"]:
        print(f"  agent 3 blocked by: {', '.join(verdict['agent3_blocked_by'])}")
    if status == "FAILED":
        print("  BLOCKING — this canonical output must not be treated as ready.")
        for line in verdict["what_must_change"]:
            print(f"    - {line}")
    return status != "FAILED"


def _summarise_graph_validation(report: dict) -> None:
    print("\nSTAGE 9 — GRAPH VALIDATION")
    counts = report["counts"]
    print(f"  behavioural tests {counts['total']} "
          f"(pass {counts['PASS']}, fail {counts['FAIL']}, "
          f"unverified {counts['UNVERIFIED']}, blocked {counts['BLOCKED']})")
    print(f"  structural status {report['structural_status']}")
    print(f"  behavioural status {report['behavioural_status']}")
    print(f"  GRAPH_INPUT_SUFFICIENCY  {report['agent3_input_status']}")
    for f in report["findings"]:
        print(f"    [{f.status:<18}] {f.category}: {f.finding}")
    for r in report["results"]:
        if r.status == "FAIL":
            print(f"    [FAIL] {r.category} {r.rule_or_question}: {r.explanation}")


def _summarise_stage9_gate(gate: dict) -> None:
    print("\nAGENT 3 EXECUTION APPROVAL")
    print(f"  GRAPH_INPUT_SUFFICIENCY   {gate['graph_input_sufficiency']}")
    print(f"  AGENT3_EXECUTION_APPROVAL {gate['status']}")
    print(f"    canonical validation clear   {gate['canonical_validation_clear']}")
    print(f"    human decision gate clear    {gate['human_decision_gate_clear']}")
    print(f"    graph validation passed      {gate['graph_validation_passed']}")
    if gate["blocked_by"]:
        print(f"    blocked by: {', '.join(gate['blocked_by'])}")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1

    docx_path = Path(args[0])
    start = 1
    for arg in argv[1:]:
        if arg.startswith("--from-stage"):
            start = int(arg.split("=", 1)[1] if "=" in arg else argv[argv.index(arg) + 1])

    source = docx_path.name
    _set_source(docx_path)

    if start <= 1:
        document = run_stage1(docx_path)
    else:
        document = load_stage1(source)

    if start <= 2:
        blocks = run_stage2(document)
    else:
        blocks = load_stage2(source)

    if start <= 3:
        stage3, stage3_flags = run_stage3(blocks)
    else:
        stage3, stage3_flags = load_stage3(source), []

    parsed, stage4_flags = run_stage4(source, stage3, _front_matter(document))
    audit = run_stage5(document, blocks, stage3, parsed)
    survey = run_part2(source, parsed)
    # Validation and the human decision gate run before the graph is built,
    # not after: the graph builder needs no model and nothing about how it
    # builds depends on the verdict, but the verdict is what the report it
    # writes needs to say whether this graph may be trusted downstream.
    validation_report = run_agent1_validation(docx_path, source, survey)
    _graphs, graph_report = run_graphs(source, survey, validation_report)
    # Stage 9 reuses exactly what Stages 6 and 8 just wrote to disk - no
    # model call, nothing upstream rerun.
    graph_validation_report = run_graph_validation(docx_path, source)
    gate = agent3_execution_approval(validation_report, graph_validation_report)
    write_stage9_gate(source, Path(source).stem, gate)

    _summarise(blocks, stage3, parsed, [*stage3_flags, *stage4_flags])
    _summarise_audit(audit)
    _summarise_part2(survey)
    passed = _summarise_validation(validation_report)
    _summarise_graphs(graph_report)
    _summarise_graph_validation(graph_validation_report)
    _summarise_stage9_gate(gate)
    print(f"\nArtifacts: {_out_dir(source)}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
