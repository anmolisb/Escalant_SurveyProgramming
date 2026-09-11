"""Survey Programming dashboard.

    PYTHONPATH=. streamlit run src/dashboard/app.py

Three steps in order: interpret the QRE, build the survey, design the tests.
Each step reads what the one before it wrote, so each unlocks only once that
output exists.
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
import graphviz

UPLOADS = Path("data/inputs/qre_interpretation")
DESIGN_INPUTS = Path("data/inputs/test_design")
OUT = Path("out")

GROUPS = {
    "Survey specification (stage 4)": ("stage4_",),
    "Raw extraction (stage 3)": ("stage3_",),
    "Ingestion (stages 1 and 2)": ("stage1_", "stage2_"),
    "Audit (stage 5)": ("stage5_",),
    "Canonical and graph (part 2)": ("part2_",),
    "Graphs": ("route_graph", "dependency_graph"),
    "Decisions and gate": ("agent1_",),
}

NODE_STYLE = {
    "start": ("ellipse", "#dcefe1"),
    "question": ("box", "#e7eefb"),
    "ending": ("ellipse", "#fbe4dc"),
    "disposition": ("ellipse", "#fbe4dc"),
}

st.set_page_config(page_title="Survey Programming", layout="wide")

st.markdown(
    """
    <style>
      html { font-size: 21px; }
      section.main, section[data-testid="stSidebar"] { font-size: 1rem; }
      .stMarkdown, .stMarkdown p, .stMarkdown li,
      div[data-testid="stMarkdownContainer"] p,
      div[data-testid="stMarkdownContainer"] li { font-size: 1rem !important; }
      .stButton button, .stDownloadButton button,
      div[data-baseweb="select"], .stFileUploader { font-size: 1rem !important; }
      button[data-baseweb="tab"] p { font-size: 1.05rem !important; }

      /* Trim the gap above the title */
      header[data-testid="stHeader"] { height: 0; }
      .block-container { padding-top: 1rem !important; max-width: 100%; }

      /* Step list in the sidebar */
      .step { display:flex; gap:10px; align-items:flex-start;
              margin:16px 0 -6px 0; }
      .step .num {
          flex:0 0 23px; height:23px; border-radius:50%; font-size:12.5px;
          display:flex; align-items:center; justify-content:center;
          background:#d7dce3; color:#414852; font-weight:600;
      }
      .step.done .num { background:#2e7d4f; color:#fff; }
      .step.next .num { background:#c8492f; color:#fff; }
      .step .label { font-size:15px; padding-top:2px; }
      .step.waiting .label { color:#9aa1ab; }

      section[data-testid="stSidebar"] > div { padding-top: 1.2rem; }

      /* Header strip */
      .strip { display:flex; gap:0; border:1px solid #e4e7eb; border-radius:10px;
               overflow:hidden; margin:6px 0 18px 0; background:#fff; }
      .cell { flex:1; padding:14px 18px; border-right:1px solid #eef0f3; }
      .cell:last-child { border-right:none; }
      .cell .k { font-size:12.5px; letter-spacing:.04em; text-transform:uppercase;
                 color:#8a919b; margin-bottom:4px; }
      .cell .v { font-size:27px; font-weight:600; line-height:1.15; }
      .ok { color:#2e7d4f; } .warn { color:#b0521a; } .idle { color:#9aa1ab; }

      .graphwrap { overflow:auto; max-height:70vh; border:1px solid #e4e7eb;
                   border-radius:10px; background:#fff; padding:12px; }

      /* Tables */

      /* Tables */
      .tblwrap { overflow:auto; border:1px solid #e4e7eb; border-radius:10px;
                 background:#fff; }
      table.tbl { border-collapse:collapse; width:100%; table-layout:fixed;
                  font-size:18.5px; }
      table.tbl th {
          position:sticky; top:0; z-index:1; background:#f2f4f7; text-align:left;
          padding:12px 14px; font-weight:600; font-size:13px; color:#4a515b;
          letter-spacing:.03em; text-transform:uppercase;
          border-bottom:1px solid #dfe3e8;
      }
      table.tbl td { padding:12px 14px; border-bottom:1px solid #f0f2f4;
                     vertical-align:top; word-wrap:break-word; }
      table.tbl tr.odd td { background:#fafbfc; }
      table.tbl tr:hover td { background:#eef4fc; }
      table.tbl td.num { text-align:right; font-variant-numeric:tabular-nums; }
      .pill { display:inline-block; padding:2px 10px; border-radius:11px;
              font-size:13px; background:#eef0f3; color:#4a515b; }
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


def load_design_summary(design_dir: Path | None) -> dict | None:
    """The summary run.py prints, which it also writes to disk.

    Read back when reopening a run, so the figures survive a reload without
    re-running the designer.
    """
    if not design_dir or not design_dir.exists():
        return None
    return read_json(design_dir, "agent3_summary.json", None)


def sentence(value) -> str:
    text = str(value or "").strip()
    return text[:1].upper() + text[1:] if text else ""


def table(rows, widths=None, numeric=(), pills=(), height="62vh") -> None:
    """A striped, fixed-layout HTML table.

    Used instead of st.dataframe, which draws to a canvas and so ignores any
    font size or column width you set.
    """
    if not rows:
        st.info("Nothing to show here.")
        return
    widths = widths or {}
    columns = list(rows[0])
    head = "".join(
        f'<th style="width:{widths.get(c, "auto")}">{html_lib.escape(c)}</th>'
        for c in columns
    )

    body = []
    for index, row in enumerate(rows):
        cells = []
        for column in columns:
            raw = "" if row.get(column) is None else str(row.get(column))
            text = html_lib.escape(raw)
            if column in pills and raw:
                text = f'<span class="pill">{text}</span>'
            css = ' class="num"' if column in numeric else ""
            cells.append(f"<td{css}>{text}</td>")
        body.append(
            '<tr class="{}">{}</tr>'.format("odd" if index % 2 else "even", "".join(cells))
        )

    st.markdown(
        f'<div class="tblwrap" style="max-height:{height}">'
        f'<table class="tbl"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def strip(cells: list[tuple[str, str, str]]) -> None:
    """The header metrics. Each cell is (label, value, css class)."""
    html = "".join(
        f'<div class="cell"><div class="k">{html_lib.escape(k)}</div>'
        f'<div class="v {cls}">{html_lib.escape(v)}</div></div>'
        for k, v, cls in cells
    )
    st.markdown(f'<div class="strip">{html}</div>', unsafe_allow_html=True)


def file_rows(files: list[Path]) -> None:
    for path in files:
        left, right = st.columns([5, 1])
        left.write(path.name)
        right.download_button(
            "Download", data=path.read_bytes(), file_name=path.name, key=str(path)
        )

def to_dot(graph: nx.DiGraph, zoom: float, vertical: bool = False) -> str:
    lines = [
        "digraph {",
        f"  rankdir={'TB' if vertical else 'LR'};",
        "  pad=0.4;",
        f"  dpi={72 * zoom:.0f};",
        "  nodesep=0.35;",
        "  ranksep=0.7;",
        '  bgcolor="#ffffff";',
        '  node [fontname="Helvetica" fontsize=13 height=0.5 width=1.5 '
        'color="#c3ccd8" penwidth=1.2];',
        '  edge [fontname="Helvetica" fontsize=11 color="#8b95a3"];',
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


def step(number: int, label: str, state: str) -> None:
    """state is done, next or waiting."""
    st.markdown(
        f'<div class="step {state}"><div class="num">{number}</div>'
        f'<div class="label">{html_lib.escape(label)}</div></div>',
        unsafe_allow_html=True,
    )


def clear_downstream(*keys: str) -> None:
    for key in keys:
        st.session_state.pop(key, None)


# --- state -----------------------------------------------------------------

run_name = st.session_state.get("run_name")
directory = OUT / run_name if run_name else None
has_run = bool(directory and directory.exists())
lss = OUT / f"{run_name}_generated.lss" if run_name else None
has_lss = bool(lss and lss.exists())
design_dir = directory / "agent3" if directory else None
has_design = bool(design_dir and design_dir.exists())


def run_interpreter(source: Path) -> None:
    with st.spinner("Interpreting the QRE. This takes a few minutes."):
        result = subprocess.run(
            [sys.executable, "-m", "src.agents.qre_interpretation.orchestrator", str(source)],
            capture_output=True,
            text=True,
        )
    st.session_state["run_name"] = source.stem
    st.session_state["log"] = result.stdout + result.stderr
    st.session_state["run_failed"] = result.returncode != 0
    clear_downstream("build_log", "build_ok", "design", "design_log", "design_ok")


def build_survey() -> None:
    with st.spinner("Building the survey file."):
        result = subprocess.run(
            [sys.executable, "-m", "src.agents.survey_builder.build", str(directory)],
            capture_output=True,
            text=True,
        )
    st.session_state["build_log"] = result.stdout + result.stderr
    st.session_state["build_ok"] = result.returncode == 0
    clear_downstream("design", "design_log", "design_ok")


def design_tests() -> None:
    command = [sys.executable, "-m", "src.agents.test_design.run", str(directory)]
    if has_lss:
        command += ["--lss", str(lss)]
    inputs = DESIGN_INPUTS / f"{run_name}.json"
    if inputs.exists():
        command += ["--inputs", str(inputs)]
    with st.spinner("Designing tests."):
        result = subprocess.run(command, capture_output=True, text=True)
    st.session_state["design_log"] = result.stdout + result.stderr
    st.session_state["design_ok"] = result.returncode == 0
    try:
        st.session_state["design"] = json.loads(result.stdout)
    except json.JSONDecodeError:
        st.session_state["design"] = None


# --- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.markdown("### Pipeline")

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
        index = names.index(run_name) if run_name in names else 0
        picked = st.selectbox("Open a run", names, index=index)
        if picked != "(new upload)" and picked != run_name:
            st.session_state["run_name"] = picked
            clear_downstream("log", "build_log", "build_ok", "design", "design_log")
            st.rerun()

    uploaded = st.file_uploader("QRE document", type="docx")
    pending = Path(uploaded.name).stem if uploaded else None
    already = bool(pending and (OUT / pending).exists())

    st.divider()

    step(1, "Interpret the QRE", "done" if has_run else "next")
    if st.button(
        "Run QRE Interpreter",
        type="primary" if not has_run else "secondary",
        disabled=not uploaded or already,
        use_container_width=True,
    ):
        UPLOADS.mkdir(parents=True, exist_ok=True)
        source = UPLOADS / uploaded.name
        source.write_bytes(uploaded.getbuffer())
        run_interpreter(source)
        st.rerun()

    if already:
        st.caption("That document has been run. Open it above.")

    step(2, "Build the survey", "done" if has_lss else ("next" if has_run else "waiting"))
    st.button(
        "Run Survey Builder",
        disabled=not has_run or has_lss,
        on_click=build_survey,
        use_container_width=True,
        key="build_side",
    )

    step(3, "Design the tests", "done" if has_design else ("next" if has_lss else "waiting"))
    st.button(
        "Run Test Designer",
        disabled=not has_lss,
        on_click=design_tests,
        use_container_width=True,
        key="design_side",
    )

    if has_run:
        st.divider()
        if st.button("Delete this run", use_container_width=True):
            shutil.rmtree(directory, ignore_errors=True)
            if lss:
                lss.unlink(missing_ok=True)
            clear_downstream(
                "run_name", "log", "build_log", "build_ok", "design", "design_log", "design_ok"
            )
            st.rerun()

    if st.session_state.get("run_failed"):
        st.error("The interpreter reported problems. The artifacts may still be usable.")
    if "log" in st.session_state:
        with st.expander("Interpreter log"):
            st.code(st.session_state["log"])
    if st.session_state.get("design_ok") is False:
        st.error("The test design run failed.")
        st.code(st.session_state.get("design_log", ""))


# --- main ------------------------------------------------------------------

st.title("Survey Programming")

if not has_run:
    st.caption("Escalent capstone. QRE document in, tested LimeSurvey file out.")
    st.info("Upload a QRE document in the sidebar to begin.")
    st.stop()

survey = read_json(directory, "stage4_survey.json", {})
questions = read_json(directory, "stage4_questionnaire.json", [])
routing = read_json(directory, "stage4_routing.json", [])
design = st.session_state.get("design") or load_design_summary(design_dir)

title = survey.get("title") or run_name
st.subheader(title)

strip(
    [
        ("Questions", str(len(questions)), ""),
        ("Routing rules", str(len(routing)), ""),
        ("Survey file", "Built" if has_lss else "Not built", "ok" if has_lss else "idle"),
        ("Test cases", str(design.get("logical_tests", "—")) if design else "—", ""),
    ]
)


tab_q, tab_r, tab_g, tab_s, tab_t, tab_f = st.tabs(
    ["Questions", "Routing", "Flow graph", "Survey Builder", "Test Design", "Artifacts"]
)

with tab_q:
    table(
        [
            {
                "ID": q.get("id"),
                "Type": sentence(q.get("type")),
                "Question": q.get("wording"),
                "Options": len(q.get("options") or []),
                "Shown if": q.get("display_condition") or "",
            }
            for q in questions
        ],
        widths={
            "ID": "6%",
            "Type": "9%",
            "Question": "47%",
            "Options": "8%",
            "Shown if": "30%",
        },
        numeric=("Options",),
        pills=("Type",),
    )

with tab_r:
    table(
        [
            {
                "Rule": r.get("rule"),
                "Condition": r.get("condition_raw"),
                "Expression": r.get("condition_expression"),
                "Action": sentence(r.get("action")),
                "Goes to": r.get("destination"),
            }
            for r in routing
        ],
        widths={
            "Rule": "7%",
            "Condition": "32%",
            "Expression": "32%",
            "Action": "11%",
            "Goes to": "18%",
        },
        pills=("Action",),
    )

with tab_g:
    gexf = directory / "route_graph.gexf"
    if not gexf.exists():
        st.info("No route graph was produced for this run.")
    else:
        graph = nx.read_gexf(gexf)
        endings = sum(
            1
            for _, data in graph.nodes(data=True)
            if data.get("kind") in {"ending", "disposition"}
        )
        st.session_state.setdefault("zoom", 1.6)

        info, minus, plus, reset, full = st.columns([5, 1, 1, 1, 1])
        info.markdown(
            f"**{graph.number_of_nodes()}** nodes  ·  **{graph.number_of_edges()}** edges  ·  "
            f"**{endings}** endings"
        )

        if minus.button("🔍−", help="Zoom out", use_container_width=True):
            st.session_state["zoom"] = max(0.6, st.session_state["zoom"] - 0.3)
        if plus.button("🔍＋", help="Zoom in", use_container_width=True):
            st.session_state["zoom"] = min(4.0, st.session_state["zoom"] + 0.3)
        if reset.button("Fit", help="Reset zoom", use_container_width=True):
            st.session_state["zoom"] = 1.0
        vertical = full.toggle("Vertical", value=False, help="Stack top to bottom")

        svg = graphviz.Source(to_dot(graph, st.session_state["zoom"], vertical)).pipe(
            format="svg"
        ).decode()
        st.markdown(
            f'<div class="graphwrap">{svg}</div>',
            unsafe_allow_html=True,
        )

        st.caption(
            "Dashed edges are conditional and carry their rule ID. Green is the start, "
            "orange is an ending."
        )
        st.download_button(
            "Download the graph as SVG",
            data=svg,
            file_name=f"{run_name}_flow.svg",
            mime="image/svg+xml",
        )

with tab_s:
    if not has_lss:
        log = st.session_state.get("build_log", "")
        if not log:
            st.info("Not built yet. Use step 2 in the sidebar.")
        else:
            st.error("The survey could not be built.")
            st.markdown(
                "The builder stops rather than guessing. Each line below names a "
                "question it could not translate and what would let it through."
            )
            for line in log.splitlines():
                if line.strip() and not line.startswith("out/"):
                    st.markdown(f"- {line.strip()}")
            with st.expander("Full build log"):
                st.code(log)
    else:
        st.success(f"The survey file for {title} is built.")
        st.download_button(
            "Download the .lss file",
            data=lss.read_bytes(),
            file_name=lss.name,
            mime="application/xml",
        )
        st.markdown(
            "Import it in LimeSurvey under **Surveys → Create → Import**, then use "
            "**Preview** to walk the questionnaire as a respondent would see it."
        )
        if st.session_state.get("build_log"):
            with st.expander("Build log"):
                st.code(st.session_state["build_log"])

with tab_t:
    if not (directory / "part2_canonical.json").exists():
        st.warning("This run has no canonical specification, so tests cannot be designed.")
    elif not has_lss:
        st.info("Build the survey first. Step 3 unlocks once the survey file exists.")
    else:
        st.button("Re-run the Test Designer", on_click=design_tests, key="design_tab")

        if design:
            paths_report = (
                read_json(design_dir, "agent3_paths.json", {}) or {}
            ).get("report", {})
            branch = (
                f"{paths_report.get('branch_states_covered', '—')}/"
                f"{paths_report.get('branch_states_total', '—')}"
            )
            strip(
                [
                    ("Distinct paths", str(paths_report.get("paths_selected", "—")), ""),
                    ("Test cases", str(design.get("logical_tests", "—")), ""),
                    ("Runnable", str(design.get("executable_tests", "—")), ""),
                    ("Coverage floor", f"{design.get('coverage_floor_pct', 0)}%", ""),
                    ("Branch states", branch, ""),
                ]
            )
            st.caption(
                f"Verdict {design.get('conformance_verdict', 'unknown')}  ·  "
                f"{design.get('compilation_refused', 0)} refused to compile  ·  "
                f"replay {design.get('specification_replay', 'not recorded')}"
            )

            shadowed = paths_report.get("branch_states_shadowed") or []
            if shadowed:
                with st.expander(f"Shadowed branch states ({len(shadowed)})"):
                    for item in shadowed:
                        st.markdown(
                            f"**{item.get('question')}** guarded by "
                            f"`{item.get('guard')}`, shadowed by "
                            f"`{item.get('shadowed_by')}`\n\n{item.get('finding', '')}"
                        )

            vector = design.get("coverage_vector") or {}
            if vector:
                table(
                    [{"Dimension": k, "Coverage": v} for k, v in vector.items()],
                    widths={"Dimension": "18%", "Coverage": "82%"},
                    height="40vh",
                )

        if has_design:
            review = design_dir / "agent3_review.md"
            if review.exists():
                with st.expander("Full review"):
                    st.markdown(review.read_text())
            st.markdown("**Output files**")
            file_rows(sorted(p for p in design_dir.iterdir() if p.is_file()))

with tab_f:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory))
    st.download_button(
        "Download everything as a zip",
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
