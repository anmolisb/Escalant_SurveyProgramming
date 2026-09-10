"""Dashboard entry point.

    PYTHONPATH=. streamlit run src/dashboard/app.py

Upload a QRE, run the QRE Interpreter, inspect what it extracted, build a
LimeSurvey file, then design tests against it.
"""

from __future__ import annotations

import html as html_lib
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import networkx as nx
import streamlit as st

UPLOADS = Path("data/inputs/qre_interpretation")
OUT = Path("out")

GROUPS = {
    "Stage 4 (survey specification)": ("stage4_",),
    "Stage 3 (raw extraction)": ("stage3_",),
    "Stages 1 and 2 (ingestion)": ("stage1_", "stage2_"),
    "Stage 5 (audit)": ("stage5_",),
    "Part 2 (canonical and graph)": ("part2_",),
    "Graphs": ("route_graph", "dependency_graph"),
    "Agent 1 decisions and gate": ("agent1_",),
}

NODE_STYLE = {
    "start": ("ellipse", "#e8f4ea"),
    "question": ("box", "#eef2f8"),
    "ending": ("ellipse", "#f8ece8"),
    "disposition": ("ellipse", "#f8ece8"),
}

st.set_page_config(page_title="Survey Programming", layout="wide")

st.markdown(
    """
    <style>
    .tblwrap { overflow: auto; border: 1px solid #e6e6e6; border-radius: 6px; }
    table.tbl { border-collapse: collapse; width: 100%; font-size: 15px; }
    table.tbl th {
        position: sticky; top: 0; background: #eceff3; text-align: left;
        padding: 10px 12px; font-weight: 600; border-bottom: 1px solid #d8dde3;
        white-space: nowrap;
    }
    table.tbl td {
        padding: 9px 12px; border-bottom: 1px solid #eef0f2; vertical-align: top;
    }
    table.tbl tr.odd td { background: #f7f8fa; }
    table.tbl tr:hover td { background: #eef4fb; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- helpers ---------------------------------------------------------------


def read_json(directory: Path, name: str, default=None):
    path = directory / name
    if not path.exists():
        return default
    data = json.loads(path.read_text())
    return data.get("content", data) if isinstance(data, dict) and "content" in data else data


def sentence(value: str) -> str:
    """'terminate' -> 'Terminate'. Leaves anything already capitalised alone."""
    text = str(value or "").strip()
    return text[:1].upper() + text[1:] if text else ""


def table(rows: list[dict], widths: dict[str, str] | None = None, height: int = 520) -> None:
    """A striped HTML table. Used instead of st.dataframe because that renders
    to canvas, so its font size cannot be changed."""
    if not rows:
        st.write("Nothing to show.")
        return
    widths = widths or {}
    columns = list(rows[0])
    head = "".join(
        f'<th style="width:{widths.get(c, "auto")}">{html_lib.escape(c)}</th>'
        for c in columns
    )
    body = "".join(
        '<tr class="{}">{}</tr>'.format(
            "odd" if index % 2 else "even",
            "".join(
                f"<td>{html_lib.escape(str(row.get(column, '')))}</td>"
                for column in columns
            ),
        )
        for index, row in enumerate(rows)
    )
    st.markdown(
        f'<div class="tblwrap" style="max-height:{height}px">'
        f"<table class='tbl'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        "</div>",
        unsafe_allow_html=True,
    )


def file_rows(files: list[Path]) -> None:
    for path in files:
        left, right = st.columns([4, 1])
        left.write(path.name)
        right.download_button(
            "Download", data=path.read_bytes(), file_name=path.name, key=str(path)
        )


def to_dot(graph: nx.DiGraph) -> str:
    lines = [
        "digraph {",
        "  rankdir=LR;",
        "  nodesep=0.3;",
        "  ranksep=0.6;",
        '  node [fontname="Helvetica" fontsize=12 height=0.5 width=1.4];',
        '  edge [fontname="Helvetica" fontsize=10];',
    ]
    for name, data in graph.nodes(data=True):
        shape, fill = NODE_STYLE.get(data.get("kind", ""), ("box", "#ffffff"))
        label = data.get("label") or name
        lines.append(
            f'  "{name}" [label="{label}" shape={shape} style=filled fillcolor="{fill}"];'
        )
    for source, target, data in graph.edges(data=True):
        label = data.get("rule_id") or ""
        dashed = " style=dashed" if data.get("kind") != "advance" else ""
        lines.append(f'  "{source}" -> "{target}" [label="{label}"{dashed}];')
    lines.append("}")
    return "\n".join(lines)


# --- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.header("Pipeline")

    existing = (
        sorted(
            (p for p in OUT.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if OUT.exists()
        else []
    )

    if existing:
        names = ["(new upload)"] + [p.name for p in existing]
        picked = st.selectbox("Run", names)
        if picked != "(new upload)":
            st.session_state["run_name"] = picked

    if st.session_state.get("run_name"):
        current = OUT / st.session_state["run_name"]
        if st.button("Delete this run"):
            shutil.rmtree(current, ignore_errors=True)
            (OUT / f"{current.name}_generated.lss").unlink(missing_ok=True)
            for key in ("run_name", "log", "build_log", "build_ok", "design"):
                st.session_state.pop(key, None)
            st.rerun()

    uploaded = st.file_uploader("QRE document", type="docx")
    already_run = bool(uploaded) and (OUT / Path(uploaded.name).stem).exists()

    if uploaded:
        if st.button("Run QRE Interpreter", type="primary", disabled=already_run):
            UPLOADS.mkdir(parents=True, exist_ok=True)
            source = UPLOADS / uploaded.name
            source.write_bytes(uploaded.getbuffer())

            with st.spinner("Running the QRE Interpreter. This takes a few minutes."):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "src.agents.qre_interpretation.orchestrator",
                        str(source),
                    ],
                    capture_output=True,
                    text=True,
                )

            st.session_state["run_name"] = source.stem
            st.session_state["log"] = result.stdout + result.stderr
            for key in ("build_log", "build_ok", "design"):
                st.session_state.pop(key, None)
            if result.returncode != 0:
                st.session_state["run_failed"] = True
            st.rerun()

        if already_run:
            st.caption("Already processed. Select it under Run above.")

    if st.session_state.pop("run_failed", False):
        st.error("The run reported problems. Artifacts may still be usable.")

    if "log" in st.session_state:
        with st.expander("Run log"):
            st.code(st.session_state["log"])


# --- main ------------------------------------------------------------------

st.title("Survey Programming")

run_name = st.session_state.get("run_name")
if not run_name or not (OUT / run_name).exists():
    st.info("Upload a QRE document in the sidebar to begin.")
    st.stop()

directory = OUT / run_name
survey = read_json(directory, "stage4_survey.json", {})
questions = read_json(directory, "stage4_questionnaire.json", [])
routing = read_json(directory, "stage4_routing.json", [])
gate = read_json(directory, "agent1_stage9_gate.json", {})
lss = OUT / f"{run_name}_generated.lss"
design_dir = directory / "agent3"


def build_survey() -> None:
    with st.spinner("Building"):
        result = subprocess.run(
            [sys.executable, "-m", "src.agents.survey_builder.build", str(directory)],
            capture_output=True,
            text=True,
        )
    st.session_state["build_log"] = result.stdout + result.stderr
    st.session_state["build_ok"] = result.returncode == 0

def design_tests() -> None:
    command = [sys.executable, "-m", "src.agents.test_design.run", str(directory)]
    if lss.exists():
        command += ["--lss", str(lss)]
    inputs = Path("data/inputs/test_design") / f"{run_name}.json"
    if inputs.exists():
        command += ["--inputs", str(inputs)]
    with st.spinner("Designing tests"):
        result = subprocess.run(command, capture_output=True, text=True)
    st.session_state["design_log"] = result.stdout + result.stderr
    st.session_state["design_ok"] = result.returncode == 0
    try:
        st.session_state["design"] = json.loads(result.stdout)
    except json.JSONDecodeError:
        st.session_state["design"] = None


st.subheader(survey.get("title") or run_name)

a, b, c, d = st.columns(4)
a.metric("Questions", len(questions))
b.metric("Routing rules", len(routing))
c.metric("Test Design approval", gate.get("status", "Unknown"))
d.metric("Survey file", "Built" if lss.exists() else "Not built")
if not lss.exists():
    d.button("Build now", key="build_top", on_click=build_survey)

if gate.get("blocked_by"):
    st.warning("Blocked by: " + ", ".join(gate["blocked_by"]))

tab_q, tab_r, tab_g, tab_t, tab_f, tab_b = st.tabs(
    ["Questions", "Routing", "Flow graph", "Test Design", "Artifacts", "Survey Builder"]
)

with tab_q:
    table(
        [
            {
                "ID": q.get("id"),
                "Type": sentence(q.get("type")),
                "Wording": q.get("wording"),
                "Options": len(q.get("options") or []),
                "Shown if": q.get("display_condition") or "",
            }
            for q in questions
        ],
        widths={"ID": "70px", "Type": "90px", "Options": "80px", "Shown if": "260px"},
    )

with tab_r:
    table(
        [
            {
                "Rule": r.get("rule"),
                "Condition": r.get("condition_raw"),
                "Expression": r.get("condition_expression"),
                "Action": sentence(r.get("action")),
                "Destination": r.get("destination"),
            }
            for r in routing
        ],
        widths={"Rule": "70px", "Action": "100px", "Destination": "180px"},
    )

with tab_g:
    gexf = directory / "route_graph.gexf"
    if not gexf.exists():
        st.write("No route graph was produced for this run.")
    else:
        graph = nx.read_gexf(gexf)
        endings = sum(
            1
            for _, data in graph.nodes(data=True)
            if data.get("kind") in {"ending", "disposition"}
        )
        st.markdown(
            f"- **Nodes:** {graph.number_of_nodes()}\n"
            f"- **Edges:** {graph.number_of_edges()}\n"
            f"- **Endings:** {endings}\n"
            "\n*Note: dashed edges are conditional. Edge labels are rule IDs.*"
        )
        st.graphviz_chart(to_dot(graph), use_container_width=True)

with tab_t:
    canonical = directory / "part2_canonical.json"
    if not canonical.exists():
        st.warning("No part2_canonical.json in this run, so tests cannot be designed.")
    else:
        if not lss.exists():
            st.info(
                "No survey file yet. Tests will be designed but marked not runnable. "
                "Build the survey first to bind them to real field names."
            )
        st.button(
            "Design tests",
            type="primary",
            on_click=design_tests,
            key="design_button",
        )

        design = st.session_state.get("design")
        if design:
            one, two, three, four = st.columns(4)
            one.metric("Paths", design.get("paths", "—"))
            two.metric("Test cases", design.get("logical_tests", "—"))
            three.metric("Executable", design.get("executable_tests", "—"))
            four.metric("Coverage", f"{design.get('coverage_floor_pct', 0)}%")

            st.caption(
                f"Verdict: {design.get('conformance_verdict', 'unknown')}  ·  "
                f"branch states {design.get('branch_states', '—')}  ·  "
                f"{design.get('compilation_refused', 0)} refused to compile"
            )

            vector = design.get("coverage_vector") or {}
            if vector:
                table(
                    [{"Dimension": k, "Coverage": v} for k, v in vector.items()],
                    widths={"Dimension": "120px"},
                    height=280,
                )

        if st.session_state.get("design_ok") is False:
            st.error("The test design run failed.")
            st.code(st.session_state.get("design_log", ""))

        if design_dir.exists():
            review = design_dir / "agent3_review.md"
            if review.exists():
                with st.expander("Review"):
                    st.markdown(review.read_text())

            st.write("**Output files**")
            file_rows(sorted(p for p in design_dir.iterdir() if p.is_file()))

with tab_f:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory))
    st.download_button(
        "Download all artifacts",
        data=buffer.getvalue(),
        file_name=f"{run_name}_artifacts.zip",
        mime="application/zip",
    )
    st.caption(str(directory))

    top_level = [p for p in directory.iterdir() if p.is_file()]
    shown: set[Path] = set()
    for label, prefixes in GROUPS.items():
        files = sorted(p for p in top_level if p.name.startswith(prefixes))
        if not files:
            continue
        shown.update(files)
        with st.expander(f"{label}  ({len(files)})"):
            file_rows(files)

    other = sorted(p for p in top_level if p not in shown)
    if other:
        with st.expander(f"Other  ({len(other)})"):
            file_rows(other)

with tab_b:
    st.button(
        "Build LimeSurvey file",
        type="primary",
        disabled=lss.exists(),
        on_click=build_survey,
        key="build_tab",
    )

    if lss.exists():
        st.caption("Already built. Delete the .lss file to rebuild.")

    if "build_log" in st.session_state:
        if st.session_state["build_ok"]:
            st.success(st.session_state["build_log"].strip())
        else:
            st.error("Build failed. Preflight found gaps.")
            st.code(st.session_state["build_log"])

    if lss.exists():
        st.download_button(
            "Download .lss",
            data=lss.read_bytes(),
            file_name=lss.name,
            mime="application/xml",
        )