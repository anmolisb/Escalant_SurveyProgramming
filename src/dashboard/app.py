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
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import networkx as nx
import streamlit as st
import graphviz
from graphviz.backend.execute import ExecutableNotFound


def _find_graphviz() -> str | None:
    """Put Graphviz on the path for this process only, if we can find it.

    The graphviz package is a wrapper around a separate program, and on a
    managed laptop the installer needs rights the user may not have. A
    portable copy unzipped anywhere works just as well, so look in the places
    someone would plausibly put one before giving up.

    Nothing outside this process is changed, so no administrator is involved
    and no environment variable is left behind.
    """
    if shutil.which("dot"):
        return shutil.which("dot")

    candidates = [
        Path.home() / "graphviz" / "bin",
        Path("C:/ISB-Capstone/graphviz/bin"),
        Path("C:/Program Files/Graphviz/bin"),
        Path("C:/Program Files (x86)/Graphviz/bin"),
        Path(__file__).resolve().parents[2] / "tools" / "graphviz" / "bin",
    ]
    for folder in candidates:
        for binary in (folder / "dot.exe", folder / "dot"):
            if binary.exists():
                os.environ["PATH"] = f"{folder}{os.pathsep}{os.environ['PATH']}"
                return str(binary)

    # Unzipping usually leaves the version in a folder of its own, so
    # graphviz\bin becomes graphviz\Graphviz-16.1.0-win64\bin. Expecting
    # people to move it afterwards is a step that will be forgotten, so look
    # one level down as well.
    for parent in (Path.home() / "graphviz", Path("C:/ISB-Capstone/graphviz"),
                   Path(__file__).resolve().parents[2] / "tools" / "graphviz"):
        if not parent.is_dir():
            continue
        for binary in list(parent.glob("*/bin/dot.exe")) + \
                list(parent.glob("*/bin/dot")):
            os.environ["PATH"] = (f"{binary.parent}{os.pathsep}"
                                  f"{os.environ['PATH']}")
            return str(binary)
    return None


GRAPHVIZ = _find_graphviz()

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


st.set_page_config(page_title="Survey Programming", layout="wide")

st.markdown(
    """<style>@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
      /* ---- tokens -------------------------------------------------------
         Ink indigo carries the product. The four status colours are
         functional and cannot be brand colours, so they are held apart and
         match the workbooks the agents write, which makes the tool and its
         output read as one thing. */
      :root {
        --ink:      #1B1832;
        --ink-2:    #4A4566;
        --ink-3:    #7C7796;
        --paper:    #FBFAFD;
        --card:     #FFFFFF;
        --rule:     #E2DFEF;
        --rule-2:   #F1EFF8;
        --accent:   #4338A8;
        --ok:       #0F766E;  --ok-bg:   #DAEDEA;
        --bad:      #A32C36;  --bad-bg:  #F8E4E6;
        --warn:     #9C4709;  --warn-bg: #FAEBDE;
        --info:     #4338A8;  --info-bg: #E9E6F9;
      }
      html, body, [class*="css"] { font-family: 'IBM Plex Sans', system-ui, sans-serif; }
      html { font-size: 17px; }
      body { background: var(--paper); color: var(--ink); }
      .stApp { background: var(--paper); }
      .stMarkdown, .stMarkdown p, .stMarkdown li,
      div[data-testid="stMarkdownContainer"] p,
      div[data-testid="stMarkdownContainer"] li {
          font-size: 0.95rem !important; color: var(--ink); line-height: 1.55;
          max-width: 78ch;
      }
      h1, h2, h3 { font-family: 'IBM Plex Sans', sans-serif; color: var(--ink);
                   letter-spacing: -0.015em; font-weight: 600; }
      h1 { font-size: 1.85rem; } h2 { font-size: 1.25rem; } h3 { font-size: 1.05rem; }
      header[data-testid="stHeader"] { height: 0; }
      .block-container { padding-top: 1.1rem !important; max-width: 100%; }
      /* ---- the pipeline, in the sidebar ---------------------------------
         Numbered because it genuinely is a sequence: each stage reads what
         the one before it wrote. */
      .step { display:flex; gap:11px; align-items:flex-start; margin:15px 0 -5px; }
      .step .num {
          flex:0 0 22px; height:22px; border-radius:50%; font-size:12px;
          display:flex; align-items:center; justify-content:center;
          background:var(--rule); color:var(--ink-2); font-weight:600;
          font-variant-numeric: tabular-nums;
      }
      .step.done .num { background:var(--ok); color:#fff; }
      .step.next .num { background:var(--accent); color:#fff; }
      .step .label { font-size:0.88rem; padding-top:1px; color:var(--ink); }
      .step.waiting .label { color:var(--ink-3); }
      section[data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--rule); }
      section[data-testid="stSidebar"] > div { padding-top: 1.1rem; }
      /* ---- the figure strip ---------------------------------------------
         Sentence-case labels. Uppercase tracking on every label is the
         commonest dashboard tell and makes nothing easier to read. */
      .strip { display:flex; border:1px solid var(--rule); border-radius:8px;
               overflow:hidden; margin:4px 0 20px; background:var(--card); }
      .cell { flex:1; padding:13px 17px; border-right:1px solid var(--rule-2); }
      .cell:last-child { border-right:none; }
      .cell .k { font-size:0.8rem; color:var(--ink-3); margin-bottom:3px; }
      .cell .v { font-size:1.6rem; font-weight:600; line-height:1.1;
                 font-variant-numeric: tabular-nums; letter-spacing:-0.02em; }
      .ok { color:var(--ok); } .warn { color:var(--warn); }
      .bad { color:var(--bad); } .idle { color:var(--ink-3); }
      .graphwrap { overflow:auto; max-height:70vh; border:1px solid var(--rule);
                   border-radius:8px; background:var(--card); padding:12px; }
      /* ---- tables --------------------------------------------------------
         Headers in sentence case and normal weight colour, because a header
         row is already distinguished by position and background. */
      .tblwrap { overflow:auto; border:1px solid var(--rule); border-radius:8px;
                 background:var(--card); }
      table.tbl { border-collapse:collapse; width:100%; table-layout:fixed;
                  font-size:0.88rem; }
      table.tbl th {
          position:sticky; top:0; z-index:1; background:#F6F4FC; text-align:left;
          padding:11px 14px; font-weight:600; font-size:0.82rem;
          color:var(--ink-2); border-bottom:1px solid var(--rule);
      }
      table.tbl td { padding:11px 14px; border-bottom:1px solid var(--rule-2);
                     vertical-align:top; word-wrap:break-word; line-height:1.5; }
      table.tbl tr.odd td { background:#FCFBFE; }
      table.tbl tr:hover td { background:#F4F1FC; }
      table.tbl td.num { text-align:right; font-variant-numeric:tabular-nums; }
      .pill { display:inline-block; padding:2px 10px; border-radius:10px;
              font-size:0.8rem; font-weight:500;
              background:var(--rule-2); color:var(--ink-2); }
      .pill.ok   { background:var(--ok-bg);   color:var(--ok); }
      .pill.bad  { background:var(--bad-bg);  color:var(--bad); }
      .pill.warn { background:var(--warn-bg); color:var(--warn); }
      .pill.info { background:var(--info-bg); color:var(--info); }
      /* An identifier is a code, so it is set as one. */
      .code { font-family:'IBM Plex Mono', monospace; font-size:0.84rem;
              color:var(--ink-2); }
      /* ---- respondent journeys -------------------------------------------
         The one place this tool should not look like a dashboard. A journey
         is a route a person walks, so it is drawn as a route: the questions
         are stops, and the colour says what happened at each. Reading a
         table row to learn that P03 broke tells you less than seeing where. */
      .route { border:1px solid var(--rule); border-radius:8px; background:var(--card);
               padding:14px 16px; margin-bottom:10px; }
      .route.broken { border-left:3px solid var(--bad); }
      .route.working { border-left:3px solid var(--ok); }
      .route.unproven { border-left:3px solid var(--warn); }
      .route .rhead { display:flex; align-items:baseline; gap:10px;
                      margin-bottom:11px; flex-wrap:wrap; }
      .route .rid { font-family:'IBM Plex Mono', monospace; font-weight:500;
                    color:var(--ink-3); font-size:0.84rem; }
      .route .rname { font-weight:600; font-size:0.95rem; }
      .route .rmeta { color:var(--ink-3); font-size:0.84rem; margin-left:auto;
                      font-variant-numeric: tabular-nums; }
      .track { display:flex; align-items:center; flex-wrap:wrap; gap:0; }
      .stop { display:inline-flex; align-items:center; justify-content:center;
              min-width:38px; height:27px; padding:0 8px; border-radius:5px;
              font-size:0.8rem; font-weight:500; background:var(--ok-bg);
              color:var(--ok); font-family:'IBM Plex Mono', monospace; }
      .stop.fail { background:var(--bad-bg); color:var(--bad); font-weight:600; }
      .stop.unproven { background:var(--warn-bg); color:var(--warn); }
      .stop.quiet { background:var(--rule-2); color:var(--ink-3); }
      .stop.end { background:var(--ink); color:#fff; border-radius:13px;
                  padding:0 12px; }
      .link { width:11px; height:1px; background:var(--rule); flex:0 0 11px; }
      .route .rwhy { margin-top:10px; font-size:0.86rem; color:var(--ink-2);
                     line-height:1.5; }
      .route .rwhy b { font-weight:600; }
      .route.broken .rwhy b { color:var(--bad); }
      .route.unproven .rwhy b { color:var(--warn); }
      .legend { display:flex; gap:16px; flex-wrap:wrap; margin:2px 0 14px;
                font-size:0.82rem; color:var(--ink-3); align-items:center; }
      .legend .swatch { display:inline-block; width:11px; height:11px;
                        border-radius:3px; margin-right:5px; vertical-align:-1px; }
      /* ---- section headings ---------------------------------------------- */
      .sect { margin:4px 0 14px; }
      .sect h2 { margin:0 0 3px; font-size:1.18rem; }
      .sect p { margin:0; color:var(--ink-3); font-size:0.9rem; max-width:74ch;
                line-height:1.5; }
      /* ---- empty states --------------------------------------------------
         An empty screen is an invitation to act, so it says what to do. */
      .empty { border:1px dashed var(--rule); border-radius:8px;
               background:var(--card); padding:26px 28px; margin:6px 0 4px; }
      .empty .etitle { font-weight:600; font-size:1rem; margin-bottom:5px; }
      .empty .ebody  { color:var(--ink-2); font-size:0.92rem; max-width:68ch;
                       line-height:1.55; }
      .empty .ethen  { color:var(--accent); font-size:0.9rem; margin-top:9px;
                       font-weight:500; }
      /* ---- coverage meters ------------------------------------------------ */
      .meters { border:1px solid var(--rule); border-radius:8px;
                background:var(--card); padding:6px 16px; }
      .meter { display:flex; align-items:center; gap:14px; padding:9px 0;
               border-bottom:1px solid var(--rule-2); }
      .meter:last-child { border-bottom:none; }
      .meter .mlabel { flex:0 0 220px; font-size:0.88rem; }
      .meter .mtrack { flex:1; height:7px; border-radius:4px;
                       background:var(--rule-2); overflow:hidden; }
      .meter .mfill  { height:100%; border-radius:4px; background:var(--ok); }
      .meter .mfill.warn { background:var(--warn); }
      .meter .mfill.bad  { background:var(--bad); }
      .meter .mval { flex:0 0 66px; text-align:right; font-weight:600;
                     font-size:0.88rem; font-variant-numeric:tabular-nums; }
      .meter .mval span { color:var(--ink-3); font-weight:400; }
      .meter .mstat { flex:0 0 94px; color:var(--ink-3); font-size:0.8rem; }
      /* ---- questions as a questionnaire ---------------------------------- */
      .qcard { border:1px solid var(--rule); border-radius:8px;
               background:var(--card); padding:14px 16px; margin-bottom:9px; }
      .qcard .qtop { display:flex; align-items:center; gap:9px; margin-bottom:6px; }
      .qcard .qid { font-family:'IBM Plex Mono',monospace; font-weight:500;
                    font-size:0.84rem; color:var(--ink-3); }
      .qcard .qtext { font-size:1rem; font-weight:500; line-height:1.45;
                      max-width:76ch; margin-bottom:9px; }
      .opts { display:flex; flex-wrap:wrap; gap:6px; }
      .opt { font-size:0.82rem; padding:2px 9px; border-radius:5px;
             background:var(--rule-2); color:var(--ink-2); }
      .opt.more { background:transparent; color:var(--ink-3); }
      .qguard { margin-top:9px; font-size:0.85rem; color:var(--accent); }
      /* ---- routing rules -------------------------------------------------- */
      .rule { display:flex; align-items:baseline; gap:11px; flex-wrap:wrap;
              border:1px solid var(--rule); border-radius:8px;
              background:var(--card); padding:11px 15px; margin-bottom:7px;
              font-size:0.9rem; }
      .rule .rid { font-family:'IBM Plex Mono',monospace; font-size:0.84rem;
                   color:var(--ink-3); flex:0 0 46px; }
      .rule .when { color:var(--ink); }
      .rule .arrow { color:var(--ink-3); }
      .rule .act { font-weight:600; color:var(--accent); }
      button[data-baseweb="tab"] p { font-size:0.95rem !important; font-weight:500; }
      button[data-baseweb="tab"][aria-selected="true"] p { color:var(--accent) !important; }
      .stButton button, .stDownloadButton button { font-size:0.9rem !important;
              border-radius:7px; font-weight:500; }
    </style>""",
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


#: A status is only useful at a glance if it is coloured by what it means.
#: Green is nothing to do. Red is someone would notice. Amber is unproven or
#: waiting on someone. Blue is a question rather than a fault.
_TONES = {
    "ok": ("PASSED", "WORKING", "CONFORMS", "BUILT"),
    "bad": ("FAILED", "BROKEN", "SURVEY_DEFECT", "NOT_CONFORMANT"),
    "warn": ("NOT PROVEN", "BLOCKED", "SPECIFICATION_ERROR", "NOT_BUILT_YET",
             "UNDECIDED", "HARNESS_FAULT"),
    "info": ("INCONCLUSIVE", "SKIPPED", "UNSETTLED_QUESTION",
             "TEST_MODEL_GAP", "COVERAGE_GAP", "NEEDS_SAMPLE"),
}


def _tone(value: str) -> str:
    upper = str(value).upper()
    for tone, words in _TONES.items():
        if any(w in upper for w in words):
            return tone
    return ""


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
                text = f'<span class="pill {_tone(raw)}">{text}</span>'
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


def section(title: str, blurb: str = "") -> None:
    """A stage heading and, where it earns its place, one line saying why.

    Every stage of this pipeline reads what the one before it wrote, and a
    person arriving at a tab cannot see that from the numbers alone.
    """
    st.markdown(
        f'<div class="sect"><h2>{html_lib.escape(title)}</h2>'
        + (f'<p>{html_lib.escape(blurb)}</p>' if blurb else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def waiting(what: str, why: str, then: str = "") -> None:
    """An empty screen should say what to do next, not merely that it is empty."""
    st.markdown(
        f'<div class="empty"><div class="etitle">{html_lib.escape(what)}</div>'
        f'<div class="ebody">{html_lib.escape(why)}</div>'
        + (f'<div class="ethen">{html_lib.escape(then)}</div>' if then else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def meter(label: str, covered: int, total: int, status: str = "") -> str:
    """One coverage reading as a bar.

    Nine numbers in a column are nine numbers. Nine bars are a shape, and the
    short one is the answer to the only question anyone asks of this table.
    """
    pct = (covered / total * 100) if total else 0
    tone = "ok" if pct >= 100 else ("warn" if pct >= 50 else "bad")
    return (
        f'<div class="meter">'
        f'  <div class="mlabel">{html_lib.escape(label)}</div>'
        f'  <div class="mtrack"><div class="mfill {tone}" '
        f'style="width:{pct:.0f}%"></div></div>'
        f'  <div class="mval">{covered}<span>/{total}</span></div>'
        f'  <div class="mstat">{html_lib.escape(status.lower())}</div>'
        f'</div>'
    )


def question_card(q: dict) -> str:
    """A question as it reads in the questionnaire, not as a database row."""
    options = q.get("options") or []
    shown = q.get("display_condition") or ""
    chips = "".join(
        f'<span class="opt">{html_lib.escape(str(o.get("label", o)))}</span>'
        for o in options[:8])
    if len(options) > 8:
        chips += f'<span class="opt more">+{len(options) - 8} more</span>'
    guard = (f'<div class="qguard">Shown only when '
             f'{html_lib.escape(shown)}</div>') if shown else ""
    return (
        f'<div class="qcard">'
        f'  <div class="qtop"><span class="qid">'
        f'{html_lib.escape(str(q.get("id","")))}</span>'
        f'  <span class="pill">{html_lib.escape(sentence(q.get("type")))}</span>'
        f'  </div>'
        f'  <div class="qtext">{html_lib.escape(str(q.get("wording","")))}</div>'
        f'  <div class="opts">{chips}</div>{guard}'
        f'</div>'
    )


def rule_card(r: dict) -> str:
    """A routing rule read as the sentence it is: when this, do that."""
    action = sentence(r.get("action"))
    dest = r.get("destination") or ""
    # Built outside the f-string: Python before 3.12 refuses a backslash
    # inside an f-string expression, and an escape for the dash counts.
    condition = html_lib.escape(str(r.get("condition_raw") or "\u2014"))
    return (
        f'<div class="rule">'
        f'  <span class="rid">{html_lib.escape(str(r.get("rule","")))}</span>'
        f'  <span class="when">when {condition}</span>'
        f'  <span class="arrow">\u2192</span>'
        f'  <span class="act">{html_lib.escape(action)}'
        + (f' {html_lib.escape(dest)}' if dest else "")
        + f'</span>'
        f'</div>'
    )


def journey(path: dict, verdict: dict, failures_at: dict) -> None:
    """Draw one respondent journey as the route it is.

    A table row can tell you that P03 broke. It cannot tell you where, and
    where is the thing a survey programmer needs. So the questions are drawn
    as stops along a track, coloured by what happened at each, ending in the
    disposition the respondent reached.
    """
    # A verdict with no status says nothing, so it must not read as healthy.
    status = verdict.get("status", "NOT PROVEN")
    klass = {"WORKING": "working", "BROKEN": "broken"}.get(status, "unproven")

    stops = []
    for qid in path.get("sequence") or []:
        trouble = failures_at.get(qid)
        if trouble == "real":
            tone, title = "fail", "something went wrong here"
        elif trouble:
            tone, title = "unproven", "could not be proved here"
        else:
            tone, title = "", "passed"
        stops.append(f'<span class="stop {tone}" title="{title}">'
                     f'{html_lib.escape(qid)}</span>')

    ending = path.get("disposition") or "COMPLETE"
    track = '<span class="link"></span>'.join(stops)
    track += (f'<span class="link"></span>'
              f'<span class="stop end">{html_lib.escape(ending)}</span>')

    # "Came unstuck" claims something went wrong. On a journey where nothing
    # is known to be wrong and something merely could not be checked, that
    # would overstate it, and the status pill would contradict the sentence
    # beside it.
    why = ""
    if verdict.get("broke_at"):
        lead = ("First came unstuck at" if status == "BROKEN"
                else "Could not be proved at")
        why = (f'<div class="rwhy">{lead} '
               f'<b>{html_lib.escape(verdict["broke_at"])}</b> \u2014 '
               f'{html_lib.escape(verdict.get("first_failure") or "")}</div>')

    st.markdown(
        f'<div class="route {klass}">'
        f'  <div class="rhead">'
        f'    <span class="rid">{html_lib.escape(path.get("path_id",""))}</span>'
        f'    <span class="rname">{html_lib.escape(path.get("name",""))}</span>'
        f'    <span class="pill {_tone(status)}">{status}</span>'
        f'    <span class="rmeta">{verdict.get("passed",0)} of '
        f'{verdict.get("tests",0)} checks passed</span>'
        f'  </div>'
        f'  <div class="track">{track}</div>'
        f'  {why}'
        f'</div>',
        unsafe_allow_html=True,
    )


def graphviz_missing() -> None:
    """Say what is missing and how to get it, rather than crashing the page.

    The graphviz package is only a wrapper around a separate program. Having
    one without the other is easy to do and gives an error that reads as
    though the app is broken, when every other tab would work perfectly well.
    """
    st.warning(
        "**Diagrams need Graphviz**, which is a separate program rather than "
        "the Python package of the same name. Everything else on this page "
        "works without it.\n\n"
        "No administrator rights are needed. Download the Windows **zip** "
        "from gitlab.com/graphviz/graphviz/-/releases, unzip it to "
        "`C:\\ISB-Capstone\\graphviz`, and restart this app. It looks there "
        "on startup, so nothing else has to be set."
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
        '  node [fontname="Helvetica" fontsize=13 height=0.45 width=1.3];',
        '  edge [fontname="Helvetica" fontsize=10];',
    ]

    for name, data in graph.nodes(data=True):
        label = data.get("label") or name
        kind = data.get("kind")
        if kind == "start":
            attrs = 'shape=ellipse style=filled fillcolor="#dcefe1" color="#6aa583"'
        elif kind == "disposition":
            fill = DISPOSITION_FILL.get(data.get("disposition_kind"), "#fbe4dc")
            attrs = f'shape=ellipse style=filled fillcolor="{fill}" color="#c58d7a"'
        else:
            outline = "dashed" if str(data.get("has_guard")).lower() == "true" else "solid"
            attrs = (
                f'shape=box style="filled,{outline}" fillcolor="#e7eefb" '
                'color="#8fa8cc"'
            )
        tip = data.get("guard") or ""
        tooltip = f' tooltip="{tip}"' if tip else ""
        lines.append(f'  "{name}" [label="{label}" {attrs}{tooltip}];')

    for source, target, data in graph.edges(data=True):
        colour, style, arrow, prefix = EDGE_STYLE.get(
            data.get("kind"), ("#8b95a3", "solid", "normal", "")
        )
        rule = data.get("rule_id") or ""
        label = f"{prefix} ({rule})" if prefix and rule else prefix or rule
        tip = (data.get("condition") or "").replace('"', "'")
        lines.append(
            f'  "{source}" -> "{target}" [label="{label}" color="{colour}" '
            f'fontcolor="{colour}" style={style} arrowhead={arrow}'
            + (f' tooltip="{tip}"' if tip else "")
            + "];"
        )

    lines.append("}")
    return "\n".join(lines)

def path_dot(path: dict) -> str:
    """One path drawn as a left-to-right chain, ending at its disposition."""
    sequence = list(path.get("sequence") or [])
    disposition = path.get("disposition")
    #skipped = set(path.get("skipped") or [])

    lines = [
        "digraph {",
        "  rankdir=LR;",
        "  pad=0.2;",
        "  nodesep=0.25;",
        "  ranksep=0.45;",
        "  bgcolor=transparent;",
        '  node [fontname="Helvetica" fontsize=12 shape=box height=0.4 '
        'width=1.1 style=filled fillcolor="#e7eefb" color="#c3ccd8"];',
        '  edge [color="#8b95a3" arrowsize=0.7];',
    ]
    for name in sequence:
        lines.append(f'  "{name}";')

    fill = "#dcefe1" if path.get("route_class") == "MAIN" else "#fbe4dc"
    if disposition:
        lines.append(
            f'  "{disposition}" [shape=ellipse fillcolor="{fill}" width=1.4];'
        )
    chain = sequence + ([disposition] if disposition else [])
    for source, target in zip(chain, chain[1:]):
        lines.append(f'  "{source}" -> "{target}";')
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
bot_dir = directory / "agent4" if directory else None
qc_dir = directory / "agent5" if directory else None
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


def run_bot() -> None:
    """Agent 4: drive the survey and record what happened."""
    command = [sys.executable, "-m", "src.agents.respondent_bot.run_browser",
               str(directory), "--sid", st.session_state.get("sid", "900001"),
               "--base", st.session_state.get("base", "http://localhost:8080")]
    if st.session_state.get("watch"):
        command += ["--headed", "--slow", "150"]
    with st.spinner("Running the tests against the live survey."):
        result = subprocess.run(command, capture_output=True, text=True)
    st.session_state["bot_log"] = result.stdout + result.stderr
    st.session_state["bot_ok"] = result.returncode == 0
    clear_downstream("qc_log", "qc_ok")


def run_adjudicator() -> None:
    """Agent 5: decide what the results mean."""
    with st.spinner("Working out what the results mean."):
        result = subprocess.run(
            [sys.executable, "-m", "src.agents.qa_adjudication.adjudicate",
             str(directory)], capture_output=True, text=True)
    st.session_state["qc_log"] = result.stdout + result.stderr
    st.session_state["qc_ok"] = result.returncode == 0


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
    st.markdown(
        '<p style="color:var(--ink-3);font-size:1rem;margin:-6px 0 22px;'
        'max-width:70ch">A questionnaire goes in. A built survey comes out, '
        'together with the evidence that it does what the questionnaire '
        'says.</p>', unsafe_allow_html=True)
    waiting("Nothing open yet",
            "Five stages run in order, each reading what the one before it "
            "wrote: read the questionnaire, build the survey, design the "
            "tests, run them as a respondent, then work out what the results "
            "mean.",
            "Upload a questionnaire in the sidebar, or open a previous run")
    st.stop()

survey = read_json(directory, "stage4_survey.json", {})
questions = read_json(directory, "stage4_questionnaire.json", [])
routing = read_json(directory, "stage4_routing.json", [])
design = st.session_state.get("design") or load_design_summary(design_dir)

title = survey.get("title") or run_name
qc = read_json(qc_dir, "agent5_findings.json") if qc_dir else None
ran = read_json(bot_dir, "agent4_results.json") if bot_dir else None

st.markdown(f'<h2 style="margin:-4px 0 14px;font-size:1.3rem">'
            f'{html_lib.escape(title)}</h2>', unsafe_allow_html=True)

#: Where this run stands, left to right in the order the stages happen, so
#: the header is also the progress.
verdict = "\u2014"
verdict_tone = "idle"
if qc:
    js = qc.get("journeys", [])
    good = sum(1 for j in js if j.get("status") == "WORKING")
    broken = any(j.get("status") == "BROKEN" for j in js)
    verdict = f"{good} of {len(js)} journeys"
    # Red only when something a respondent would meet is wrong. Journeys that
    # could not be fully proved are amber: they are not known to be broken.
    verdict_tone = "ok" if good == len(js) else ("bad" if broken else "warn")

strip([
    ("Questions", str(len(questions)), ""),
    ("Routing rules", str(len(routing)), ""),
    ("Survey file", "Built" if has_lss else "Not built",
     "ok" if has_lss else "idle"),
    ("Tests designed",
     str(design.get("logical_tests", "\u2014")) if design else "\u2014", ""),
    ("Tests run",
     str(sum((ran or {}).get("counts", {}).values())) if ran else "\u2014", ""),
    ("Verdict", verdict, verdict_tone),
])


tab_q, tab_r, tab_g, tab_s, tab_t, tab_b, tab_c, tab_f = st.tabs(
    ["Questions", "Routing", "Flow graph", "Survey Builder", "Test Design",
     "Respondent Bot", "QC Report", "Artifacts"]
)

with tab_q:
    section("The questionnaire as the interpreter read it",
            f"{len(questions)} questions extracted from the document. Anything "
            f"shown only under a condition says so underneath.")
    st.markdown("".join(question_card(q) for q in questions),
                unsafe_allow_html=True)

with tab_r:
    section("Where the survey sends people",
            f"{len(routing)} rules. Each reads as a sentence: when this is "
            f"true, do that.")
    if not routing:
        waiting("No routing rules", "This questionnaire has no skips or "
                "screen-outs, so every respondent sees every question.")
    else:
        st.markdown("".join(rule_card(r) for r in routing),
                    unsafe_allow_html=True)
        with st.expander("The expressions these become in LimeSurvey"):
            table([{"Rule": r.get("rule"),
                    "Expression": r.get("condition_expression")}
                   for r in routing],
                  widths={"Rule": "9%"}, height="40vh")

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

        try:
            svg = graphviz.Source(
                to_dot(graph, st.session_state["zoom"], vertical)
            ).pipe(format="svg").decode()
        except ExecutableNotFound:
            graphviz_missing()
            svg = ""

        if svg:
            st.markdown(
                f'<div class="graphwrap">{svg}</div>',
                unsafe_allow_html=True,
            )
        st.caption(
            "Grey is document order. Teal is a skip, red a termination, blue a "
            "visibility guard, purple a quota. A dashed question box is shown "
            "only when its guard holds. Hover an edge for its condition."
        )

        st.download_button(
            "Download the graph as SVG",
            data=svg,
            file_name=f"{run_name}_flow.svg",
            mime="image/svg+xml",
        )

with tab_s:
    section("The survey file",
            "The builder turns the specification into a .lss that LimeSurvey "
            "can import. It stops rather than guessing, so a question it "
            "cannot translate is named rather than approximated.")

    if not has_lss:
        log = st.session_state.get("build_log", "")
        if not log:
            waiting("Not built yet",
                    "The specification is ready. Building it produces the "
                    ".lss file that everything downstream is tested against.",
                    "Run Survey Builder, step 2 in the sidebar")
        else:
            st.error("The survey could not be built.")
            st.markdown("Each line names a question the builder could not "
                        "translate, and what would let it through.")
            for line in log.splitlines():
                if line.strip() and not line.startswith("out/"):
                    st.markdown(f"- {line.strip()}")
            with st.expander("Full build log"):
                st.code(log)
    else:
        size = lss.stat().st_size / 1024
        strip([("Survey file", "Built", "ok"),
               ("Size", f"{size:.0f} KB", ""),
               ("Questions carried", str(len(questions)), "")])
        st.download_button("Download the .lss file", data=lss.read_bytes(),
                           file_name=lss.name, mime="application/xml",
                           type="primary")
        st.markdown(
            "Import it under **Surveys \u2192 Create \u2192 Import**, then "
            "activate it. An inactive survey will not serve respondents, so "
            "the bot cannot test it."
        )
        if st.session_state.get("build_log"):
            with st.expander("Build log"):
                st.code(st.session_state["build_log"])

#: The nine kinds of behaviour a survey can get wrong, in words rather than
#: codes. D1 means nothing to a reader; "showing, hiding and flow" does.
DIMENSION_NAMES = {
    "D1": "Showing, hiding and flow", "D2": "Endings",
    "D3": "Answer rules", "D4": "Compulsory questions",
    "D5": "Carried-forward options", "D6": "Carried-forward wording",
    "D7": "Shuffled questions", "D8": "Quotas", "D9": "Combinations",
}

with tab_t:
    section("What will be tested",
            "The designer works out every distinct journey through the survey "
            "and writes a test for each behaviour the questionnaire claims. "
            "It never opens the survey; that comes next.")

    if not (directory / "part2_canonical.json").exists():
        waiting("No specification to work from",
                "The interpreter has not produced a canonical specification "
                "for this run, so there is nothing to design tests against.")
    elif not has_lss:
        waiting("Waiting on the survey file",
                "Tests can be designed without it, but none of them would be "
                "runnable: there would be no field to bind an answer to.",
                "Build the survey first, step 2 in the sidebar")
    else:
        st.button("Design the tests again", on_click=design_tests,
                  key="design_tab")

        if design:
            report = (read_json(design_dir, "agent3_paths.json", {}) or {}
                      ).get("report", {})
            strip([
                ("Journeys", str(report.get("paths_selected", "\u2014")), ""),
                ("Test cases", str(design.get("logical_tests", "\u2014")), ""),
                ("Runnable", str(design.get("executable_tests", "\u2014")), ""),
                ("Weakest reading",
                 f"{design.get('coverage_floor_pct', 0)}%",
                 "ok" if design.get("coverage_floor_pct", 0) >= 100 else "warn"),
            ])

            vector = design.get("coverage_vector") or {}
            if vector:
                section("Nine kinds of behaviour, counted separately",
                        "They are never added together, because they count "
                        "different things. The shortest bar is the answer to "
                        "the only question anyone asks of this.")
                bars = []
                for key in sorted(vector):
                    raw = str(vector[key])
                    got, _, rest = raw.partition("/")
                    total = rest.split(" ")[0] if rest else "0"
                    status = raw.split(")")[-1].strip() if ")" in raw else ""
                    try:
                        bars.append(meter(DIMENSION_NAMES.get(key, key),
                                          int(got), int(total), status))
                    except ValueError:
                        continue
                st.markdown(f'<div class="meters">{"".join(bars)}</div>',
                            unsafe_allow_html=True)

            st.caption(
                f"Build agrees with the questionnaire: "
                f"{sentence(design.get('conformance_verdict','unknown')).replace('_',' ').lower()}"
                f"  ·  {design.get('compilation_refused', 0)} test(s) refused "
                f"to compile  ·  replayed against the questionnaire's own "
                f"worked examples: {design.get('specification_replay','not recorded')}"
            )

            shadowed = report.get("branch_states_shadowed") or []
            if shadowed:
                section("Findings for whoever wrote the questionnaire",
                        "Rules that say the same thing twice, so one of them "
                        "can never be observed on its own.")
                for item in shadowed:
                    st.warning(f"**{item.get('question')}** — "
                               f"{item.get('finding','')}")

            paths = (read_json(design_dir, "agent3_paths.json", {}) or {}
                     ).get("paths", [])
            if paths:
                section("The journeys these tests run on",
                        "Exclusive, and every branch taken in both directions "
                        "by at least one of them.")
                for path in paths:
                    label = f"{path['path_id']}  ·  {path['name']}"
                    with st.expander(label):
                        st.markdown(
                            '<div class="track">'
                            + '<span class="link"></span>'.join(
                                f'<span class="stop quiet">{html_lib.escape(q)}</span>'
                                for q in path.get("sequence") or [])
                            + '<span class="link"></span>'
                            f'<span class="stop end">'
                            f'{html_lib.escape(path.get("disposition") or "COMPLETE")}'
                            '</span></div>', unsafe_allow_html=True)
                        st.markdown(f"**Why this one.** "
                                    f"{path.get('why_selected','')}")
                        if path.get("what_it_adds"):
                            st.caption(f"What it adds: {path['what_it_adds']}")
                        if path.get("skipped"):
                            st.caption("Skipped: " + ", ".join(path["skipped"]))

        if has_design:
            with st.expander("Output files"):
                file_rows(sorted(p for p in design_dir.iterdir() if p.is_file()))

with tab_b:
    section("Running the tests against the real survey",
            "The bot answers as a respondent would, one fresh session per "
            "test, and records what it saw. It does not decide what a failure "
            "means \u2014 that is the next tab.")

    if not has_lss:
        waiting("Nothing to run against",
                "The tests need a live survey. Build the .lss, import it into "
                "LimeSurvey and activate it first.",
                "Build the survey, step 2 in the sidebar")
    elif not (design_dir and (design_dir / "agent3_executable_tests.json").exists()):
        waiting("No tests to run",
                "The designer has not produced a test package for this run.",
                "Design the tests, step 3 in the sidebar")
    else:
        left, middle, right = st.columns([2, 2, 3])
        st.session_state.setdefault("sid", "900001")
        st.session_state.setdefault("base", "http://localhost:8080")
        left.text_input("Survey id in LimeSurvey", key="sid",
                        help="The number in the participant link.")
        middle.text_input("LimeSurvey address", key="base")
        right.checkbox("Watch it in a browser", key="watch",
                       help="Slower, and worth it when showing someone. "
                            "Leave off to run in the background.")
        st.button("Run the tests", type="primary", on_click=run_bot,
                  key="run_bot")

    if st.session_state.get("bot_log"):
        with st.expander("Run log",
                         expanded=not st.session_state.get("bot_ok")):
            st.code(st.session_state["bot_log"])

    results = read_json(bot_dir, "agent4_results.json") if bot_dir else None
    if results:
        counts = results.get("counts", {})
        could_not = counts.get("BLOCKED", 0) + counts.get("SKIPPED", 0)
        inconclusive = counts.get("INCONCLUSIVE", 0)
        # The four outcomes add up to Tests run, so nothing is left unaccounted for.
        strip([
            ("Tests run", str(sum(counts.values())), ""),
            ("Passed", str(counts.get("PASSED", 0)), "ok"),
            ("Failed", str(counts.get("FAILED", 0)),
             "bad" if counts.get("FAILED") else "idle"),
            ("Inconclusive", str(inconclusive),
             "warn" if inconclusive else "idle"),
            ("Could not run", str(could_not), "warn" if could_not else "idle"),
            ("Last run",
             (results.get("run_at") or "")[:16].replace("T", " "), ""),
        ])
        st.caption(
            "Passed, failed, inconclusive and could not run add up to the tests "
            "run. Inconclusive means the test ran but the bot cannot yet "
            "observe what it claims. Could not run means it never finished "
            "its journey, or needs several respondents. Neither says anything "
            "about the survey, and counting them as failures would send "
            "someone looking for a defect that may not be there."
        )

        table([
            {
                "Test": r.get("case_id") or r.get("test_id"),
                "Question": r.get("question") or "\u2014",
                "What was tested": r.get("title"),
                "Outcome": r.get("status"),
                "What the bot saw": " ".join(
                    str(c.get("actually", "")) for c in r.get("checks", [])
                    if c.get("matched") is False)
                    or r.get("blocked_reason", "") or "what was expected",
            }
            for r in sorted(results.get("results", []),
                            key=lambda x: (x.get("order") or 9999))
        ], widths={"Test": "9%", "Question": "7%", "Outcome": "10%",
                   "What was tested": "36%"}, pills=("Outcome",))
    elif has_lss:
        st.caption("No run recorded yet for this survey.")

with tab_c:
    section("What it all means",
            "A failing test is not a defect. It may be the survey, a "
            "misreading of the questionnaire, something not built yet, or a "
            "gap in the tests themselves. Telling those apart needs the whole "
            "run, which is why it is a separate step.")

    if not (bot_dir and (bot_dir / "agent4_results.json").exists()):
        waiting("No run to judge yet",
                "The adjudicator reads a completed run and decides what each "
                "failure means and who should act on it.",
                "Run the tests on the previous tab")
    else:
        st.button("Work out what it means", type="primary",
                  on_click=run_adjudicator, key="run_qc")

    if st.session_state.get("qc_log") and not st.session_state.get("qc_ok"):
        st.error("The adjudicator reported a problem.")
        st.code(st.session_state["qc_log"])

    findings = read_json(qc_dir, "agent5_findings.json") if qc_dir else None
    if findings:
        journeys = findings.get("journeys", [])
        working = sum(1 for j in journeys if j.get("status") == "WORKING")
        broken = [j for j in journeys if j.get("status") == "BROKEN"]
        real = [g for g in findings.get("groups", [])
                if g.get("cause") in ("SURVEY_DEFECT", "SPECIFICATION_ERROR",
                                      "NOT_BUILT_YET")]
        strip([
            ("Journeys working", f"{working} of {len(journeys)}",
             "ok" if working == len(journeys) else "warn"),
            ("A respondent would notice", str(len(broken)),
             "bad" if broken else "ok"),
            ("Things to fix", str(len(findings.get("groups", []))), ""),
            ("Of those, real defects", str(len(real)),
             "bad" if real else "ok"),
        ])

        section("Can a respondent get through?",
                "One track per journey. The stops are the questions, coloured "
                "by what happened at each.")
        st.markdown(
            '<div class="legend">'
            '<span><span class="swatch" style="background:#DAEDEA"></span>'
            'checked and fine</span>'
            '<span><span class="swatch" style="background:#F8E4E6"></span>'
            'something went wrong</span>'
            '<span><span class="swatch" style="background:#FAEBDE"></span>'
            'could not be proved</span>'
            '<span><span class="swatch" style="background:#1B1832"></span>'
            'where the journey ends</span>'
            '</div>', unsafe_allow_html=True)

        # Which question each failure landed on, and whether it is the kind a
        # respondent would notice. A gap in our own tests should not paint a
        # journey red.
        REAL = {"SURVEY_DEFECT", "SPECIFICATION_ERROR", "NOT_BUILT_YET"}
        failures_at: dict[str, str] = {}
        for j in findings.get("judgements", []):
            q = j.get("question")
            if not q:
                continue
            if j.get("cause") in REAL:
                failures_at[q] = "real"
            else:
                failures_at.setdefault(q, "soft")

        shapes = {p.get("path_id"): p for p in (
            read_json(design_dir, "agent3_paths.json", {}) or {}
        ).get("paths", [])}

        for v in sorted(journeys, key=lambda x: x.get("path_id", "")):
            shape = shapes.get(v.get("path_id"))
            if shape:
                journey(shape, v, failures_at)

        groups = findings.get("groups", [])
        section("What needs correcting",
                "Failures sharing a cause and a question appear once. One "
                "mistake upstream can fail nine tests, and nine entries would "
                "invite nine investigations of one problem.")
        if not groups:
            st.success("Nothing. Every test passed.")
        else:
            table([
                {
                    "Cause": g.get("cause", "").replace("_", " ").title(),
                    "Question": g.get("question"),
                    "Tests": ", ".join(g.get("tests", [])),
                    "Who should act": g.get("owner"),
                    "What it means": g.get("means"),
                    "What to do": g.get("to_fix"),
                }
                for g in groups
            ], widths={"Cause": "13%", "Question": "7%", "Tests": "12%",
                       "Who should act": "13%"}, pills=("Cause",),
               height="40vh")

        book = (qc_dir / "agent5_qc_report.xlsx") if qc_dir else None
        if book and book.exists():
            st.download_button("Download the QC report",
                               data=book.read_bytes(),
                               file_name=f"{run_name}_qc_report.xlsx",
                               mime=("application/vnd.openxmlformats-"
                                     "officedocument.spreadsheetml.sheet"),
                               type="primary")


with tab_f:
    section("Everything this run produced",
            f"{sum(1 for x in directory.rglob('*') if x.is_file())} files. "
            f"The audit trail exists so that when a test fails you can tell "
            f"whether the survey is wrong, the answers chosen were wrong, or "
            f"the prediction was wrong.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory))
    st.download_button("Download everything as a zip", data=buffer.getvalue(),
                       file_name=f"{run_name}_artifacts.zip",
                       mime="application/zip")
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
