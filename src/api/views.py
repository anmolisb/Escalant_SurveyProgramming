"""What the web app shows, read from the files the agents write.

Nothing here runs an agent. Each function reads one run folder under out/ and
returns plain data for the frontend, so every screen shows exactly what the
agents produced.
"""

from __future__ import annotations

import json
from pathlib import Path

import graphviz
import networkx as nx
from graphviz.backend.execute import ExecutableNotFound

from src.agents.qre_interpretation import stage6_conditions
from src.agents.respondent_bot.run_browser import tests_digest
from src.agents.qre_interpretation.models import DISPLAY_KINDS, Condition
from src.common import paths as fnames
from src.common.paths import OUT_ROOT, agent1_dir, agent2_lss

#: Agent 1's files, grouped for the Artifacts screen by the stage that wrote them.
GROUPS = {
    "Canonical survey specification (stage 6)": ("agent1_canonical",),
    "Survey specification (stage 4)": ("agent1_s4_",),
    "Raw extraction (stage 3)": ("agent1_s3_",),
    "Ingestion (stages 1 and 2)": ("agent1_s1_", "agent1_s2_"),
    "Audit (stage 5)": ("agent1_s5_",),
    "Checks and decisions (stage 7)": ("agent1_s7_",),
    "Route graph (stage 8)": ("agent1_s8_",),
    "Readiness and model answers": ("agent1_ready", "agent1_llm_cache"),
}

EDGE_STYLE = {
    "advance": ("#8b95a3", "solid", "normal", ""),
    "jump": ("#1b7f6b", "dashed", "normal", "Skip to"),
    "terminate": ("#c0392b", "solid", "normal", "Terminate"),
    "visibility": ("#3d6fa5", "dashed", "empty", "Visibility"),
    "quota": ("#7b52a8", "dotted", "normal", "Quota"),
}

DISPOSITION_FILL = {
    "complete": "#dcefe1",
    "screenout": "#fbe4dc",
    "quota_full": "#ece4f5",
}


#: The supported QRE format's three tiers, by the letter that starts a QRE's name.
TIERS = {"S": "Simple", "M": "Moderate", "C": "Complex"}


class NotFound(Exception):
    """A run, or a file inside one, that does not exist."""


# --- reading ---------------------------------------------------------------


def run_dir(name: str) -> Path:
    """A run folder by name, refusing anything that would leave out/."""
    path = (OUT_ROOT / name).resolve()
    if path.parent != OUT_ROOT.resolve() or not path.is_dir():
        raise NotFound(name)
    return path


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "content" in data:
        return data["content"]
    return data


def _rendered(condition: dict | None) -> str | None:
    """A condition tree written out in the one grammar, or None if unread."""
    if not condition:
        return None
    try:
        return stage6_conditions.render(Condition.model_validate(condition))
    except Exception:  # noqa: BLE001 - a display, not a check
        return None


# --- runs ------------------------------------------------------------------


def _outputs(directory: Path) -> dict[str, Path]:
    return {
        "interpreted": agent1_dir(directory) / fnames.CANONICAL,
        "built": agent2_lss(directory),
        "designed": directory / "agent3" / "agent3_executable_tests.json",
        "ran": directory / "agent4" / "agent4_results.json",
        "judged": directory / "agent5" / "agent5_findings.json",
    }


def _raw(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def stale(directory: Path) -> list[str]:
    """Stages whose output was made from an older version of its input.

    Re-reading a questionnaire or redesigning the tests leaves the last bot
    run and verdict on disk, but they describe the old tests. Each agent
    records what it was made from, and an output whose record no longer
    matches is not shown as current until its agent runs again. File times
    are not used: a git checkout resets them.
    """
    outputs = _outputs(directory)
    canonical = _raw(outputs["interpreted"])
    tests = _raw(outputs["designed"])
    results = _raw(outputs["ran"])
    findings = _raw(outputs["judged"])
    out: list[str] = []
    made_from = (tests.get("upstream") or {}).get("canonical_generated_at")
    if tests and made_from and made_from != canonical.get("generated_at"):
        out.append("designed")
    ran_on = results.get("tests_sha256")
    if results and ("designed" in out or (ran_on and outputs["designed"].exists() and ran_on !=
                    tests_digest(outputs["designed"]))):
        out.append("ran")
    explained = findings.get("results_run_at")
    if findings and ("ran" in out or (explained and explained != results.get("run_at"))):
        out.append("judged")
    return out


def stages(directory: Path) -> dict[str, bool]:
    """Which agents have current output for this run."""
    old = stale(directory)
    return {stage: path.exists() and stage not in old
            for stage, path in _outputs(directory).items()}


def list_runs() -> list[dict]:
    """Every run under out/, most recently changed first."""
    if not OUT_ROOT.exists():
        return []
    runs = []
    for directory in OUT_ROOT.iterdir():
        if not directory.is_dir():
            continue
        spec = read_json(agent1_dir(directory) / fnames.CANONICAL, {}) or {}
        survey = spec.get("survey") or {}
        done = stages(directory)
        results = (read_json(directory / "agent4" / "agent4_results.json") or {}) if done["ran"] else {}
        counts = results.get("counts") or {}
        findings = (read_json(directory / "agent5" / "agent5_findings.json") or {}) if done["judged"] else {}
        journeys = findings.get("journeys") or []
        runs.append({
            "name": directory.name,
            "code": survey.get("qre_id") or directory.name.split("_")[0],
            "title": survey.get("title") or directory.name,
            "description": survey.get("description"),
            "tier": TIERS.get(directory.name[:1].upper(), "Other"),
            "modified": directory.stat().st_mtime,
            "stages": done,
            "tests": sum(counts.values()) if counts else None,
            "passed": counts.get("PASSED") if counts else None,
            "journeys": len(journeys) if journeys else None,
            "working": (sum(1 for j in journeys if j.get("status") == "WORKING")
                        if journeys else None),
        })
    return sorted(runs, key=lambda r: r["modified"], reverse=True)


def _specification(directory: Path) -> tuple[dict, list[dict], list[dict]]:
    """The survey heading, questions and rules, from the canonical specification."""
    spec = read_json(agent1_dir(directory) / fnames.CANONICAL, {}) or {}
    questions = []
    for q in spec.get("questions") or []:
        guard = q.get("guard") or {}
        raw = guard.get("raw_texts") or []
        kind = str(q.get("kind") or "")
        questions.append({
            "id": q.get("question_id"),
            "type": kind,
            "display": kind.strip().lower() in DISPLAY_KINDS,
            "wording": q.get("wording"),
            "options": [o.get("label") for o in (q.get("options") or [])],
            "shown_if": raw[0] if raw else None,
        })
    rules = []
    for r in spec.get("rules") or []:
        when = r.get("when")
        rules.append({
            "id": r.get("rule_id"),
            "action": r.get("kind"),
            "destination": (r.get("destination") or {}).get("id"),
            "condition": (when or {}).get("source_text") or r.get("when_unread"),
            "reading": _rendered(when),
        })
    return spec.get("survey") or {}, questions, rules


def run_detail(name: str) -> dict:
    """Everything the screens show for one run."""
    directory = run_dir(name)
    survey, questions, rules = _specification(directory)
    design_dir = directory / "agent3"
    paths_file = read_json(design_dir / "agent3_paths.json", {}) or {}
    lss = agent2_lss(directory)
    done = stages(directory)
    return {
        "name": name,
        "code": survey.get("qre_id") or name.split("_")[0],
        "title": survey.get("title") or name,
        "description": survey.get("description"),
        "tier": TIERS.get(name[:1].upper(), "Other"),
        "stages": done,
        "stale": stale(directory),
        "questions": questions,
        "rules": rules,
        "survey_file": ({"name": lss.name, "size": lss.stat().st_size}
                        if lss.exists() else None),
        "design": read_json(design_dir / "agent3_summary.json"),
        "paths_report": paths_file.get("report") or {},
        "paths": paths_file.get("paths") or [],
        "review": ((design_dir / "agent3_review.md").read_text(encoding="utf-8")
                   if (design_dir / "agent3_review.md").exists() else None),
        "results": read_json(directory / "agent4" / "agent4_results.json") if done["ran"] else None,
        "findings": read_json(directory / "agent5" / "agent5_findings.json") if done["judged"] else None,
        "ready": read_json(agent1_dir(directory) / fnames.READY),
    }


# --- diagrams --------------------------------------------------------------


def _svg(dot: str) -> str:
    try:
        return graphviz.Source(dot).pipe(format="svg").decode()
    except ExecutableNotFound as error:
        raise RuntimeError(
            "Diagrams need the Graphviz program (brew install graphviz, or "
            "apt-get install graphviz)") from error


def _quote(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', "'")


def flow_graph(name: str, vertical: bool = False) -> dict:
    """The whole survey's route graph, drawn by Graphviz."""
    gexf = agent1_dir(run_dir(name)) / fnames.ROUTE_GRAPH_GEXF
    if not gexf.exists():
        raise NotFound(gexf.name)
    graph = nx.read_gexf(gexf)
    lines = [
        "digraph {",
        f"  rankdir={'TB' if vertical else 'LR'};",
        "  pad=0.3; nodesep=0.35; ranksep=0.7; bgcolor=transparent;",
        '  node [fontname="Helvetica" fontsize=13 height=0.45 width=1.2];',
        '  edge [fontname="Helvetica" fontsize=10];',
    ]
    endings = 0
    for node, data in graph.nodes(data=True):
        label = _quote(data.get("label") or node)
        kind = data.get("kind")
        if kind == "start":
            attrs = 'shape=ellipse style=filled fillcolor="#dcefe1" color="#6aa583"'
        elif kind in ("disposition", "ending"):
            endings += 1
            fill = DISPOSITION_FILL.get(data.get("disposition_kind"), "#fbe4dc")
            attrs = f'shape=ellipse style=filled fillcolor="{fill}" color="#c58d7a"'
        else:
            outline = "dashed" if str(data.get("has_guard")).lower() == "true" else "solid"
            attrs = (f'shape=box style="filled,{outline}" fillcolor="#e7eefb" '
                     'color="#8fa8cc"')
        tip = _quote(data.get("guard") or "")
        lines.append(f'  "{_quote(node)}" [label="{label}" {attrs}'
                     + (f' tooltip="{tip}"' if tip else "") + "];")
    for source, target, data in graph.edges(data=True):
        colour, style, arrow, prefix = EDGE_STYLE.get(
            data.get("kind"), ("#8b95a3", "solid", "normal", ""))
        rule = data.get("rule_id") or ""
        label = f"{prefix} ({rule})" if prefix and rule else prefix or rule
        tip = _quote(data.get("condition") or "")
        lines.append(
            f'  "{_quote(source)}" -> "{_quote(target)}" [label="{label}" '
            f'color="{colour}" fontcolor="{colour}" style={style} arrowhead={arrow}'
            + (f' tooltip="{tip}"' if tip else "") + "];")
    lines.append("}")
    return {"svg": _svg("\n".join(lines)), "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(), "endings": endings}


def journey_graph(name: str, path_id: str) -> str:
    """One journey drawn as a left-to-right chain, ending at its disposition."""
    paths = (read_json(run_dir(name) / "agent3" / "agent3_paths.json", {}) or {}
             ).get("paths") or []
    path = next((p for p in paths if p.get("path_id") == path_id), None)
    if path is None:
        raise NotFound(path_id)
    sequence = list(path.get("sequence") or [])
    ending = path.get("disposition")
    lines = [
        "digraph {",
        "  rankdir=LR; pad=0.15; nodesep=0.25; ranksep=0.4; bgcolor=transparent;",
        '  node [fontname="Helvetica" fontsize=12 shape=box height=0.4 width=0.9 '
        'style=filled fillcolor="#e7eefb" color="#c3ccd8"];',
        '  edge [color="#8b95a3" arrowsize=0.7];',
    ]
    lines += [f'  "{_quote(q)}";' for q in sequence]
    if ending:
        fill = "#dcefe1" if path.get("route_class") == "MAIN" else "#fbe4dc"
        lines.append(f'  "{_quote(ending)}" [shape=ellipse fillcolor="{fill}" width=1.3];')
    chain = sequence + ([ending] if ending else [])
    lines += [f'  "{_quote(a)}" -> "{_quote(b)}";' for a, b in zip(chain, chain[1:])]
    lines.append("}")
    return _svg("\n".join(lines))


# --- files -----------------------------------------------------------------


def files(name: str) -> list[dict]:
    """Every file the run produced, grouped for display."""
    directory = run_dir(name)
    groups: list[dict] = []

    def entry(path: Path) -> dict:
        return {"path": str(path.relative_to(directory)), "name": path.name,
                "size": path.stat().st_size}

    agent1 = sorted(p for p in agent1_dir(directory).glob("*") if p.is_file())
    shown: set[Path] = set()
    for label, prefixes in GROUPS.items():
        members = [p for p in agent1 if p.name.startswith(prefixes)]
        if members:
            shown.update(members)
            groups.append({"label": label, "files": [entry(p) for p in members]})
    rest = [p for p in agent1 if p not in shown]
    if rest:
        groups.append({"label": "Agent 1, other", "files": [entry(p) for p in rest]})
    for folder, label in (("agent2", "Survey file (Agent 2)"),
                          ("agent3", "Test design (Agent 3)"),
                          ("agent4", "Respondent bot (Agent 4)"),
                          ("agent5", "QA report (Agent 5)")):
        members = sorted(p for p in (directory / folder).glob("*") if p.is_file())
        if members:
            groups.append({"label": label, "files": [entry(p) for p in members]})
    return groups


def file_path(name: str, relative: str) -> Path:
    """A file inside a run, refusing anything outside it."""
    directory = run_dir(name)
    path = (directory / relative).resolve()
    if directory not in path.parents or not path.is_file():
        raise NotFound(relative)
    return path
