"""Dashboard entry point.

    PYTHONPATH=. streamlit run src/dashboard/app.py

Upload a QRE, run Agent 1 on it, then download the artifacts it produced.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import streamlit as st

UPLOADS = Path("data/inputs/qre_interpretation")
OUT = Path("out")

st.set_page_config(page_title="Survey Programming", layout="wide")
st.title("Survey Programming")

uploaded = st.file_uploader("QRE document", type="docx")

if uploaded and st.button("Run QRE Interpreter"):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    source = UPLOADS / uploaded.name
    source.write_bytes(uploaded.getbuffer())

    with st.spinner(f"Running Agent 1 on {uploaded.name}. This takes a few minutes."):
        result = subprocess.run(
            [sys.executable, "-m", "src.agents.qre_interpretation.orchestrator", str(source)],
            capture_output=True,
            text=True,
        )

    st.session_state["run_name"] = source.stem
    st.session_state["log"] = result.stdout + result.stderr
    if result.returncode != 0:
        st.error("The run failed. See the log below.")

if "log" in st.session_state:
    with st.expander("Run log"):
        st.code(st.session_state["log"])

run_name = st.session_state.get("run_name")
if run_name and (OUT / run_name).exists():
    directory = OUT / run_name
    st.subheader("Artifacts")
    st.caption(str(directory))

    groups = {
        "Stage 4 (survey specification)": "stage4_",
        "Stage 3 (raw extraction)": "stage3_",
        "Stages 1 and 2 (ingestion)": ("stage1_", "stage2_"),
        "Stage 5 (audit)": "stage5_",
        "Part 2 (canonical and graph)": "part2_",
        "Graphs": ("route_graph", "dependency_graph"),
        "Agent 1 decisions and gate": "agent1_",
    }

    shown = set()
    for label, prefixes in groups.items():
        if isinstance(prefixes, str):
            prefixes = (prefixes,)
        files = sorted(p for p in directory.iterdir() if p.name.startswith(prefixes))
        if not files:
            continue
        shown.update(files)
        with st.expander(f"{label}  ({len(files)})"):
            for path in files:
                left, right = st.columns([3, 1])
                right.download_button(
                    "Download",
                    data=path.read_bytes(),
                    file_name=path.name,
                    key=str(path),
                )
                left.write(path.name)

    other = sorted(p for p in directory.iterdir() if p not in shown)
    if other:
        with st.expander(f"Other  ({len(other)})"):
            for path in other:
                left, right = st.columns([3, 1])
                right.download_button(
                    "Download",
                    data=path.read_bytes(),
                    file_name=path.name,
                    key=str(path),
                )
                left.write(path.name)