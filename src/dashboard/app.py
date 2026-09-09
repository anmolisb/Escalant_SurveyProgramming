"""Dashboard entry point.

    PYTHONPATH=. streamlit run src/dashboard/app.py

Upload a QRE, run the QRE Interpreter, inspect what it extracted, then
build a LimeSurvey file from it.
"""

from __future__ import annotations

import io
import json
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


def read_json(directory: Path, name: str, default=None):
    path = directory / name
    if not path.exists():
        return default
    data = json.loads(path.read_text())
    return data.get("content", data) if isinstance(data, dict) and "content" in data else data


def file_rows(files: list[Path]) -> None:
    for path in files:
        left, right = st.columns([4, 1])
        left.write(path.name)
        right.download_button(
            "Download", data=path.read_bytes(), file_name=path.name, key=str(path)
        )


def to_dot(graph: nx.DiGraph) -> str:
    # lines = ["digraph {", "  rankdir=TB;", '  node [fontname="Helvetica" fontsize=10];',
    #          '  edge [fontname="Helvetica" fontsize=9];']
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
        sorted((p for p in OUT.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
        if OUT.exists()
        else []
    )

    if existing:
        names = ["(new upload)"] + [p.name for p in existing]
        picked = st.selectbox("Run", names)
        if picked != "(new upload)":
            st.session_state["run_name"] = picked

    uploaded = st.file_uploader("QRE document", type="docx")
    already_run = bool(uploaded) and (OUT / Path(uploaded.name).stem).exists()

    if uploaded:
        if st.button("Run QRE Interpreter", type="primary", disabled=already_run):
            UPLOADS.mkdir(parents=True, exist_ok=True)
            source = UPLOADS / uploaded.name
            source.write_bytes(uploaded.getbuffer())

            with st.spinner("Running Agent 1. This takes a few minutes."):
                result = subprocess.run(
                    [sys.executable, "-m", "src.agents.qre_interpretation.orchestrator", str(source)],
                    capture_output=True,
                    text=True,
                )

            st.session_state["run_name"] = source.stem
            st.session_state["log"] = result.stdout + result.stderr
            st.session_state.pop("build_log", None)
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


def build_survey() -> None:
    with st.spinner("Building"):
        result = subprocess.run(
            [sys.executable, "-m", "src.agents.survey_builder.build", str(directory)],
            capture_output=True,
            text=True,
        )
    st.session_state["build_log"] = result.stdout + result.stderr
    st.session_state["build_ok"] = result.returncode == 0


st.subheader(survey.get("title") or run_name)

a, b, c, d = st.columns(4)
a.metric("Questions", len(questions))
b.metric("Routing rules", len(routing))
c.metric("Agent 3 approval", gate.get("status", "Unknown"))
d.metric("Survey file", "Built" if lss.exists() else "Not built")
if not lss.exists():
    d.button("Build now", key="build_top", on_click=build_survey)

if gate.get("blocked_by"):
    st.warning("Blocked by: " + ", ".join(gate["blocked_by"]))

tab_q, tab_r, tab_g, tab_f, tab_b = st.tabs(
    ["Questions", "Routing", "Flow graph", "Artifacts", "Survey Builder"]
)

with tab_q:
    st.dataframe(
        [
            {
                "ID": q.get("id"),
                "Type": q.get("type"),
                "Wording": q.get("wording"),
                "Options": len(q.get("options") or []),
                "Shown if": q.get("display_condition") or "",
            }
            for q in questions
        ],
        hide_index=True,
        use_container_width=True,
        height=min(600, 40 + 35 * len(routing)),
    )

with tab_r:
    if routing:
        st.dataframe(
            [
                {
                    "Rule": r.get("rule"),
                    "Condition": r.get("condition_raw"),
                    "Expression": r.get("condition_expression"),
                    "Action": r.get("action"),
                    "Destination": r.get("destination"),
                }
                for r in routing
            ],
            hide_index=True,
            use_container_width=True,
            height=min(600, 40 + 35 * len(questions)),
        )
    else:
        st.write("No routing rules were extracted.")

# with tab_g:
#     gexf = directory / "route_graph.gexf"
#     if not gexf.exists():
#         st.write("No route graph was produced for this run.")
#     else:
#         graph = nx.read_gexf(gexf)
#         left, right = st.columns(2)
#         left.metric("Nodes", graph.number_of_nodes())
#         right.metric("Edges", graph.number_of_edges())
#         st.graphviz_chart(to_dot(graph), use_container_width=True)
#         st.caption("Dashed edges are conditional. Edge labels are rule IDs.")

with tab_g:
    gexf = directory / "route_graph.gexf"
    if not gexf.exists():
        st.write("No route graph was produced for this run.")
    else:
        graph = nx.read_gexf(gexf)
        endings = sum(
            1 for _, d in graph.nodes(data=True) if d.get("kind") in {"ending", "disposition"}
        )
        # st.caption(
        #     f"{graph.number_of_nodes()} nodes  ·  {graph.number_of_edges()} edges  ·  "
        #     f"{endings} endings      Dashed edges are conditional, labelled with their rule ID."
        # )
        st.markdown(
            f"- **Nodes:** {graph.number_of_nodes()}\n"
            f"- **Edges:** {graph.number_of_edges()}\n"
            f"- **Endings:** {endings}\n"
            f"\n*Note: Dashed edges are conditional. Edge labels are rule IDs.*"
        )
        st.graphviz_chart(to_dot(graph), use_container_width=True)

with tab_f:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.iterdir()):
            archive.write(path, path.name)
    st.download_button(
        "Download all artifacts",
        data=buffer.getvalue(),
        file_name=f"{run_name}_artifacts.zip",
        mime="application/zip",
    )
    st.caption(str(directory))

    shown: set[Path] = set()
    for label, prefixes in GROUPS.items():
        files = sorted(p for p in directory.iterdir() if p.name.startswith(prefixes))
        if not files:
            continue
        shown.update(files)
        with st.expander(f"{label}  ({len(files)})"):
            file_rows(files)

    other = sorted(p for p in directory.iterdir() if p not in shown)
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