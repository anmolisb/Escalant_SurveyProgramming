"""Where each agent's output for one QRE run lives.

    out/<QRE stem>/
        agent1/    QRE Interpreter: every stage artifact and llm_decisions.json
        agent3/    Test Designer
        agent4/    Respondent Bot
        agent5/    QA Adjudicator

Agent 1 writes through `agent1_out`. Readers are handed the run folder
(`out/<QRE stem>`) and find Agent 1's files through `agent1_dir`, which also
accepts a folder that holds those files directly, such as a test fixture.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "out"
AGENT1 = "agent1"


def agent1_out(stem: str) -> Path:
    """The folder Agent 1 writes one QRE's artifacts to."""
    return OUT_ROOT / stem / AGENT1


def agent1_dir(run_dir: str | Path) -> Path:
    """Agent 1's artifacts for a run folder.

    A run folder keeps them in `agent1/`. A folder without that subfolder is
    taken to hold the artifacts itself.
    """
    run_dir = Path(run_dir)
    nested = run_dir / AGENT1
    return nested if nested.is_dir() else run_dir
