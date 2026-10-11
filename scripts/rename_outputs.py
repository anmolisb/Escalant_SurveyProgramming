"""Rename existing run outputs to the file names in src/common/paths.py.

A one-off for outputs written before the names changed, so they can be kept
without re-running anything (re-running Agent 1 costs model calls). It also
sets the `artifact` id inside each JSON file to the file's new name, which is
what a fresh run writes. Safe to run twice: a file already renamed is left
alone, and nothing is overwritten.

    python scripts/rename_outputs.py            show what would move
    python scripts/rename_outputs.py --apply    move it
"""

from __future__ import annotations

import re
import sys

_ARTIFACT_ID = re.compile(r'("artifact":\s*")([^"]*)(")')
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import paths  # noqa: E402

#: Agent 1 names that are not just "stageN_x" -> "agent1_sN_x".
AGENT1_FIXED = {
    "part2_canonical.json": paths.CANONICAL,
    "agent1_stage9_gate.json": paths.READY,
    "llm_decisions.json": paths.LLM_CACHE,
    "agent1_evaluation_tests.json": paths.agent1_stage(7, "evaluation_tests.json"),
    "agent1_evaluation_results.json": paths.agent1_stage(7, "evaluation_results.json"),
    "part2_validation.json": paths.agent1_stage(7, "validation.json"),
    "agent1_decisions.json": paths.DECISIONS,
    "agent1_decision_register.md": paths.DECISION_REGISTER,
    "part2_route_graph.json": paths.agent1_stage(8, "route_graph.json"),
    "part2_graph_report.json": paths.agent1_stage(8, "graph_report.json"),
    "route_graph.gexf": paths.ROUTE_GRAPH_GEXF,
}
_STAGE = re.compile(r"^stage([1-5])_(.+)$")


def planned(run_dir: Path) -> list[tuple[Path, Path]]:
    moves = []
    agent1 = run_dir / paths.AGENT1
    if agent1.is_dir():
        for f in sorted(agent1.iterdir()):
            new = AGENT1_FIXED.get(f.name)
            match = _STAGE.match(f.name)
            if new is None and match:
                new = paths.agent1_stage(int(match.group(1)), match.group(2))
            if new:
                moves.append((f, agent1 / new))
    old_lss = run_dir / paths.AGENT2 / f"{run_dir.name}_generated.lss"
    if old_lss.exists():
        moves.append((old_lss, paths.agent2_lss(run_dir)))
    snapshot = run_dir / "agent3" / "implementation_snapshot.json"
    if snapshot.exists():
        moves.append((snapshot, run_dir / "agent3" / paths.SNAPSHOT))
    return moves


def fix_artifact_id(path: Path, apply: bool) -> bool:
    """Make the id inside a JSON artifact match its file name. Only that one
    value changes, so the rest of the file stays byte for byte as it was."""
    if path.suffix != ".json":
        return False
    text = path.read_text(encoding="utf-8")
    match = _ARTIFACT_ID.search(text)
    wanted = paths.artifact_id(path.name)
    if not match or match.group(2) == wanted:
        return False
    if apply:
        path.write_text(text[:match.start(2)] + wanted + text[match.end(2):],
                        encoding="utf-8")
    return True


def main() -> int:
    apply = "--apply" in sys.argv
    clashes = 0
    count = 0
    for run_dir in sorted(p for p in paths.OUT_ROOT.iterdir() if p.is_dir()):
        for old, new in planned(run_dir):
            if new.exists():
                print(f"  skip, already exists: {new.relative_to(paths.REPO_ROOT)}")
                clashes += 1
                continue
            print(f"  {old.relative_to(paths.REPO_ROOT)}  ->  {new.name}")
            count += 1
            if apply:
                old.rename(new)
    ids = 0
    for run_dir in sorted(p for p in paths.OUT_ROOT.iterdir() if p.is_dir()):
        for folder in (run_dir / paths.AGENT1, run_dir / "agent3"):
            if folder.is_dir():
                ids += sum(fix_artifact_id(f, apply) for f in sorted(folder.glob("*.json")))
    verb = "renamed" if apply else "would rename"
    print(f"\n{verb} {count} file(s); {clashes} skipped")
    print(f"{'updated' if apply else 'would update'} the artifact id in {ids} file(s)")
    if not apply and count:
        print("run again with --apply to move them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
