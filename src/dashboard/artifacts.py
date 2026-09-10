"""Read a run directory produced by Agent 1 into typed objects.

A run directory is out/<qre_name>/. Agent 1 writes 35 files there; this
module exposes the subset the dashboard reads. Nothing here imports an
agent, so the pages work without a Groq key or a pipeline run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

OUT_DIR = Path("out")


def list_runs(root: Path = OUT_DIR) -> list[Path]:
    """Run directories, most recently modified first."""
    if not root.exists():
        return []
    runs = [p for p in root.iterdir() if p.is_dir() and (p / "stage4_survey.json").exists()]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


def _read(directory: Path, name: str, default=None):
    path = directory / name
    if not path.exists():
        return default
    return json.loads(path.read_text())


@dataclass
class Run:
    directory: Path
    survey: dict
    questions: list[dict]
    routing: list[dict]
    messages: list = field(default_factory=list)
    audit: dict = field(default_factory=dict)
    gate: dict = field(default_factory=dict)
    graph_report: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.directory.name

    @property
    def title(self) -> str:
        return self.survey.get("title") or self.name

    @property
    def route_graph(self) -> Path | None:
        path = self.directory / "route_graph.gexf"
        return path if path.exists() else None

    @property
    def decision_register(self) -> str | None:
        path = self.directory / "agent1_decision_register.md"
        return path.read_text() if path.exists() else None


def load_run(directory: Path) -> Run:
    return Run(
        directory=directory,
        survey=_read(directory, "stage4_survey.json", {}),
        questions=_read(directory, "stage4_questionnaire.json", []),
        routing=_read(directory, "stage4_routing.json", []),
        messages=_read(directory, "stage4_messages.json", []),
        audit=_read(directory, "stage5_audit.json", {}),
        gate=_read(directory, "agent1_stage9_gate.json", {}),
        graph_report=_read(directory, "part2_graph_report.json", {}),
    )