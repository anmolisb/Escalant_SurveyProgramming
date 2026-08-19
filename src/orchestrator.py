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
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stage1_ingestion
import stage2_headings
import stage3_raw_json
import stage4_deep_parse
from models import (
    ReviewFlag,
    Stage1Document,
    Stage2Blocks,
    Stage3Block,
    TargetHeading,
)

OUT_ROOT = Path(__file__).resolve().parents[1] / "out"

#: Filename-safe stem per target.
_SLUG = {
    TargetHeading.QUESTIONNAIRE: "questionnaire",
    TargetHeading.ROUTING_AND_TERMINATION: "routing",
    TargetHeading.ACCEPTANCE_TEST_SCENARIOS: "scenarios",
    TargetHeading.COMPLETION_MESSAGES: "messages",
}


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        text = payload.model_dump_json(indent=2)
    else:
        text = json.dumps(
            [p.model_dump() if hasattr(p, "model_dump") else p for p in payload],
            indent=2,
            default=str,
        )
    path.write_text(text)
    return path


def _out_dir(document: str) -> Path:
    return OUT_ROOT / Path(document).stem


def run_stage1(docx_path: Path) -> Stage1Document:
    document = stage1_ingestion.run(docx_path)
    _write(_out_dir(docx_path.name) / "stage1_document.json", document)
    return document


def run_stage2(document: Stage1Document) -> Stage2Blocks:
    blocks = stage2_headings.run(document)
    out = _out_dir(document.source)
    _write(out / "stage2_blocks.json", blocks)
    _write(out / "stage2_flags.json", blocks.flags)
    return blocks


def run_stage3(stage2: Stage2Blocks) -> tuple[list[Stage3Block], list[ReviewFlag]]:
    blocks, flags = stage3_raw_json.run(stage2)
    out = _out_dir(stage2.source)
    for block in blocks:
        _write(out / f"stage3_{_SLUG[block.target]}.json", block)
    # Always written, even when empty: an absent file is ambiguous between
    # "no flags" and "stage did not run".
    _write(out / "stage3_flags.json", flags)
    return blocks, flags


def run_stage4(source: str, blocks: list[Stage3Block]) -> tuple[dict, list[ReviewFlag]]:
    parsed, flags = stage4_deep_parse.run(blocks)
    out = _out_dir(source)
    for key, slug in (
        ("questions", "questionnaire"),
        ("routing", "routing"),
        ("scenarios", "scenarios"),
        ("messages", "messages"),
    ):
        _write(out / f"stage4_{slug}.json", parsed[key])
    _write(out / "stage4_flags.json", flags)
    return parsed, flags


# ---------------------------------------------------------------------------
# Re-entry: load a previous stage's artifact instead of recomputing it
# ---------------------------------------------------------------------------


def load_stage1(source: str) -> Stage1Document:
    path = _out_dir(source) / "stage1_document.json"
    return Stage1Document.model_validate_json(path.read_text())


def load_stage2(source: str) -> Stage2Blocks:
    path = _out_dir(source) / "stage2_blocks.json"
    return Stage2Blocks.model_validate_json(path.read_text())


def load_stage3(source: str) -> list[Stage3Block]:
    out = _out_dir(source)
    return [
        Stage3Block.model_validate_json(p.read_text())
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
        print(f"\nREVIEW FLAGS — {len(all_flags)}")
        for flag in all_flags:
            confidence = f" ({flag.confidence:.2f})" if flag.confidence else ""
            candidate = f" -> {flag.candidate_heading}" if flag.candidate_heading else ""
            print(f"  [{flag.status.value}] {flag.target_heading.value}{candidate}{confidence}")
            print(f"      {flag.reasoning}")
    else:
        print("\nREVIEW FLAGS — none")


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

    _summarise(blocks, stage3, parsed, [*stage3_flags, *stage4_flags])
    print(f"\nArtifacts: {_out_dir(source)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
