"""Orchestrator. Runs the four stages, writing each artifact to disk.

    python3 src/orchestrator.py <file.docx> [--from-stage N]

Every stage reads only the previous stage's artifact, so any stage can be re-run
on its own:

    python3 src/orchestrator.py doc.docx --from-stage 4

re-runs the deep parse against the existing stage3 files without re-reading the
DOCX or re-calling the model for stages 2 and 3.

Artifacts, under out/<document stem>/:
    stage1_document.json
    stage2_blocks.json      stage2_flags.json
    stage3_<target>.json    (one per matched target)
    stage4_<target>.json    stage4_flags.json
    stage5_audit.json

Targets: questionnaire, routing, scenarios, messages, quotas, study,
programming. A target absent from the document is flagged, not fatal.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stage1_ingestion
import stage2_headings
import stage3_raw_json
import stage4_deep_parse
import stage5_audit
from models import (
    SCHEMA_VERSION,
    ArtifactEnvelope,
    FlagSeverity,
    ReviewFlag,
    SourceDocument,
    Stage1Document,
    Stage2Blocks,
    Stage3Block,
    Stage5Audit,
    TargetHeading,
)

OUT_ROOT = Path(__file__).resolve().parents[1] / "out"

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
    """Record which document this run is reading, and its digest."""
    global _SOURCE
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


def run_stage4(source: str, blocks: list[Stage3Block]) -> tuple[dict, list[ReviewFlag]]:
    parsed, flags = stage4_deep_parse.run(blocks)
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
        _write(
            out / f"stage4_{slug}.json",
            parsed[key],
            artifact=f"stage4_{slug}",
            stage=4,
            source=source,
        )
    _write(
        out / "stage4_flags.json",
        flags,
        artifact="stage4_flags",
        stage=4,
        source=source,
    )
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

    parsed, stage4_flags = run_stage4(source, stage3)
    audit = run_stage5(document, blocks, stage3, parsed)

    _summarise(blocks, stage3, parsed, [*stage3_flags, *stage4_flags])
    _summarise_audit(audit)
    print(f"\nArtifacts: {_out_dir(source)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
