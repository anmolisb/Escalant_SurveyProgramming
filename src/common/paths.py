"""Where each agent's output for one QRE run lives, and what each file is called.

    out/<QRE stem>/
        agent1/    QRE Interpreter
            agent1_canonical_survey_spec.json   the contract Agents 2 to 4 read
            agent1_ready.json                   whether Agent 3 may run
            agent1_llm_cache.json               every model answer, replayed on a re-run
            agent1_s1_document.json ... agent1_s8_graph_report.json
                                                one file per stage output, in order
        agent2/    Survey Builder: agent2_<QRE stem>.lss
        agent3/    Test Designer: agent3_*.json, *.xlsx, *.md
        agent4/    Respondent Bot: agent4_results.json, .xlsx
        agent5/    QA Adjudicator: agent5_findings.json, agent5_qc_report.xlsx

Every file name starts with its agent, because files are downloaded and shared
one at a time, and outside its folder the name is the only thing saying where
it came from. Agent 1's stage files carry their stage too (`agent1_s4_...`) so
they sort in pipeline order.

The names are defined here and nowhere else. Code that reads another agent's
output asks this module rather than spelling the name, so a rename is one edit.

Agent 1 writes through `agent1_out`. Readers are handed the run folder
(`out/<QRE stem>`) and find Agent 1's files through `agent1_dir`, which also
accepts a folder that holds those files directly, such as a test fixture.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "out"
AGENT1 = "agent1"
AGENT2 = "agent2"

# ---------------------------------------------------------------- Agent 1
#: What the QRE means: the Canonical Survey Specification. The one Agent 1 file
#: other agents read.
CANONICAL = "agent1_canonical_survey_spec.json"
#: Whether Agent 3 may run on this specification, and if not, why not.
READY = "agent1_ready.json"
#: Every model answer for this document, replayed on a re-run.
LLM_CACHE = "agent1_llm_cache.json"
#: The human decision register, and its readable form.
DECISIONS = "agent1_s7_decisions.json"
DECISION_REGISTER = "agent1_s7_decision_register.md"
#: The route graph the dashboard draws.
ROUTE_GRAPH_GEXF = "agent1_s8_route_graph.gexf"

# ---------------------------------------------------------------- Agent 3
SNAPSHOT = "agent3_implementation_snapshot.json"


def agent1_stage(stage: int, name: str) -> str:
    """A stage artifact's file name, `agent1_stage(4, "routing.json")`, or its
    artifact id without the extension, `agent1_stage(4, "routing")`."""
    return f"agent1_s{stage}_{name}"


def artifact_id(file_name: str) -> str:
    """The id an artifact carries inside its envelope: its file name without the
    extension, so a file can always be matched to what it says it is."""
    return file_name.rsplit(".", 1)[0]


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


def canonical(run_dir: str | Path) -> Path:
    """The Canonical Survey Specification for a run folder."""
    return agent1_dir(run_dir) / CANONICAL


def lss_name(stem: str) -> str:
    """The survey file's name. Keeps the QRE stem, so an import is identifiable."""
    return f"agent2_{stem}.lss"


def agent2_lss(run_dir: str | Path) -> Path:
    """The survey file the Survey Builder writes for a run folder."""
    run_dir = Path(run_dir)
    return run_dir / AGENT2 / lss_name(run_dir.name)
