"""Everything the dashboard draws, shared by both apps.

Lifted wholesale out of the single-user app rather than rewritten, because
rewriting a thousand lines of working rendering to add a login would have
been the wrong trade and would have lost all the wording we settled on.

The single-user app is untouched and still carries its own copy. Once the
team app has earned its place, that one can go.

The three module globals below are the questionnaire, the routing rules and
the survey as read for whichever run is open. The views read them directly,
which is how the original was written; ``load_context`` is what sets them.
"""
from __future__ import annotations

import html as html_lib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
import time
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



# The stylesheet, held as a value rather than emitted here.
#
# It used to be a module-level st.markdown call. Python caches an import,
# and Streamlit re-runs the script on every interaction, so the styles went
# out once on the first load and never again: every card, pill and strip
# rendered as bare text from the second click onward. Whoever draws a page
# now emits this at the top of each run.
STYLE = """<style>@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
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
      .stMarkdown, div[data-testid="stMarkdownContainer"] { max-width: none; }
      .stMarkdown p, .stMarkdown li,
      div[data-testid="stMarkdownContainer"] p,
      div[data-testid="stMarkdownContainer"] li {
          font-size: 0.95rem !important; color: var(--ink); line-height: 1.55;
      }
      /* A measure belongs on running prose, not on cards and tables. */
      .sect p, .empty .ebody, .stCaption, div[data-testid="stCaptionContainer"] p
          { max-width: 76ch; }
      h1, h2, h3 { font-family: 'IBM Plex Sans', sans-serif; color: var(--ink);
                   letter-spacing: -0.015em; font-weight: 600; }
      h1 { font-size: 1.85rem; } h2 { font-size: 1.25rem; } h3 { font-size: 1.05rem; }
      header[data-testid="stHeader"] { height: 0; }
      .block-container { padding-top: 1.1rem !important; max-width: 100%;
                         padding-left: 2.2rem; padding-right: 2.2rem; }
      /* Streamlit wraps every element in a column that stops growing. These
         let the cards use the width the window actually has. */
      div[data-testid="stVerticalBlock"], div[data-testid="stVerticalBlock"] > div,
      div[data-testid="element-container"] { width: 100%; }
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
               padding:12px 15px; margin-bottom:7px; }
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
               background:var(--card); padding:11px 15px; margin-bottom:6px; }
      .qcard .qtop { display:flex; align-items:center; gap:9px; margin-bottom:6px; }
      .qcard .qid { font-family:'IBM Plex Mono',monospace; font-weight:500;
                    font-size:0.84rem; color:var(--ink-3); }
      .qcard .qtext { font-size:0.97rem; font-weight:500; line-height:1.4;
                      max-width:88ch; margin-bottom:7px; }
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
      /* ---- a run in progress --------------------------------------------- */
      .runbar { border:1px solid var(--rule); border-radius:8px;
                background:var(--card); padding:13px 16px; margin:8px 0 10px; }
      .runbar .rprog { height:6px; border-radius:3px; background:var(--rule-2);
                       overflow:hidden; margin-bottom:9px; }
      .runbar .rfill { height:100%; background:var(--accent);
                       transition:width .25s ease; }
      .runbar .rnums { display:flex; gap:16px; font-size:0.85rem;
                       font-variant-numeric:tabular-nums; margin-bottom:6px; }
      .runbar .rnums .ok{color:var(--ok);} .runbar .rnums .bad{color:var(--bad);}
      .runbar .rnums .warn{color:var(--warn);} .runbar .rnums .grey{color:var(--ink-3);margin-left:auto;}
      .runbar .rnow { font-family:'IBM Plex Mono',monospace; font-size:0.8rem;
                      color:var(--ink-3); white-space:nowrap; overflow:hidden;
                      text-overflow:ellipsis; }
      button[data-baseweb="tab"] p { font-size:0.95rem !important; font-weight:500; }
      button[data-baseweb="tab"][aria-selected="true"] p { color:var(--accent) !important; }
      .stButton button, .stDownloadButton button { font-size:0.9rem !important;
              border-radius:7px; font-weight:500; }
          .top{background:var(--shell);color:#fff;display:flex;align-items:center;gap:14px;padding:9px 18px;margin:-1.1rem -2.2rem 16px;font-size:.92rem}
      .top .mark{font-weight:600;letter-spacing:-.01em}
      .top .mark span{color:#9C93D8;font-weight:400}
      .top .who{margin-left:auto;width:26px;height:26px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:600}
      .crumb{color:var(--ink-3);font-size:.82rem;margin-bottom:2px}
      .railname{font-weight:600;font-size:.98rem;line-height:1.3;margin:2px 0 3px;color:var(--ink)}
      .railsub{font-size:.78rem;color:var(--ink-3);margin:0 0 12px}
      .railstate{display:flex;align-items:center;gap:7px;background:var(--card);border:1px solid var(--rule);border-radius:7px;padding:8px 11px;margin:0 0 14px;font-size:.8rem}
      .railstate .dot{width:8px;height:8px;border-radius:50%;flex:0 0 8px}
      .brand{display:flex;align-items:center;gap:9px;padding:2px 2px 14px;border-bottom:1px solid var(--rule);margin-bottom:12px}
      .brand .logo{width:28px;height:28px;border-radius:7px;background:var(--ink);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:.8rem;flex:0 0 28px}
      .brand .bn{font-weight:600;font-size:.9rem;line-height:1.15}
      .brand .bs{font-size:.72rem;color:var(--ink-3)}
      .railgrp{color:var(--ink-4);font-size:.74rem;font-weight:500;margin:14px 0 2px}
      /* ---- the rail ------------------------------------------------------
         Dark, so the working area reads as the page and the navigation reads
         as furniture. Each item is a card rather than floating text, because
         a row of centred labels on a flat background gives the eye nothing
         to land on. */
      section[data-testid="stSidebar"]{background:#16132B;border-right:0}
      section[data-testid="stSidebar"] *{color:#D9D5EC}
      /* Streamlit puts its own gap between vertical elements, which on a
         list of eight nav items adds up to a lot of drift. */
      section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.3rem}
      section[data-testid="stSidebar"] .stButton{margin-bottom:0}
      section[data-testid="stSidebar"] .stButton button{width:100%;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.045);padding:9px 13px;border-radius:8px;font-weight:400;min-height:0;line-height:1.3}
      section[data-testid="stSidebar"] .stButton button *{text-align:left!important;justify-content:flex-start!important;width:100%;margin:0;color:#D9D5EC!important;font-size:.88rem!important}
      section[data-testid="stSidebar"] .stButton button:hover{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.16)}
      section[data-testid="stSidebar"] .stButton button:hover *{color:#fff!important}
      section[data-testid="stSidebar"] .stButton button[kind="primary"]{background:#fff;border-color:#fff}
      section[data-testid="stSidebar"] .stButton button[kind="primary"] *{color:var(--accent)!important;font-weight:600!important}
      section[data-testid="stSidebar"] .stButton button:disabled{background:transparent;border-color:transparent}
      section[data-testid="stSidebar"] .stButton button:disabled *{color:#6B6690!important}
      section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]{background:rgba(255,255,255,.05);border:1px dashed rgba(255,255,255,.2)}
      section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] *{color:#B9B4D4!important}
      section[data-testid="stSidebar"] hr{margin:15px 0;border-color:rgba(255,255,255,.1)}
      section[data-testid="stSidebar"] .stAlert{background:rgba(163,44,54,.2);border:1px solid rgba(163,44,54,.4)}
      section[data-testid="stSidebar"] .stButton button[key="nav_back"]{background:transparent;border-color:transparent}
      .brand{display:flex;align-items:center;gap:10px;padding:0 2px 14px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:14px}
      .brand .logo{width:30px;height:30px;border-radius:8px;background:var(--accent);color:#fff!important;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:.82rem;flex:0 0 30px}
      .brand .bn{font-weight:600;font-size:.92rem;line-height:1.15;color:#fff!important}
      .brand .bs{font-size:.72rem;color:#8F89B5!important}
      .railgrp{color:#7F7AA6!important;font-size:.72rem;font-weight:500;margin:16px 0 7px;letter-spacing:.02em}
      .railname{font-weight:600;font-size:1rem;line-height:1.3;margin:2px 0 2px;color:#fff!important}
      .railsub{font-size:.76rem;color:#8F89B5!important;margin:0 0 12px;font-family:'IBM Plex Mono',monospace}
      .railstate{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.09);border-radius:8px;padding:9px 12px;margin:0 0 4px;font-size:.8rem}
      .railstate .dot{width:8px;height:8px;border-radius:50%;flex:0 0 8px}
      .railstate .ago{margin-left:auto;color:#8F89B5!important;font-size:.75rem}
      .runrow{display:flex;align-items:center;gap:14px;padding:11px 14px;border:1px solid var(--rule);border-radius:8px;margin-bottom:6px;font-size:.88rem;background:var(--card)}
      .runrow .nm{font-weight:600;flex:0 0 230px}
      .runrow .bar{display:flex;gap:3px;flex:0 0 140px}
      .seg{height:5px;flex:1;border-radius:2px;background:var(--rule)}
      .seg.done{background:var(--ok)}
      .seg.now{background:var(--accent)}
      .runrow .when{margin-left:auto;color:var(--ink-3);font-size:.8rem}
      .filters{display:flex;gap:7px;margin-bottom:10px;flex-wrap:wrap;align-items:center}
      .warnbox{border-style:solid;border-color:var(--warn);background:var(--warn-bg)}
      .qrun{border:1px solid var(--rule);border-radius:8px;background:var(--card);padding:11px 14px;margin-bottom:6px}
      .qrun.head{margin-bottom:2px}
      .qrfail{padding:2px 2px 2px 14px;border-left:2px solid var(--bad-bg);margin:0 0 2px}
      .qrun.trouble{border-left:3px solid var(--bad)}
      .qrhead{display:flex;align-items:center;gap:12px}
      .qrhead .qid{font-family:'IBM Plex Mono',monospace;font-weight:500;color:var(--ink);font-size:.86rem;flex:0 0 92px}
      .dots{display:flex;gap:4px;flex-wrap:wrap;flex:1}
      .dots .dot{width:11px;height:11px;border-radius:3px;background:var(--ok-bg);border:1px solid rgba(15,118,110,.25)}
      .dots .dot.bad{background:var(--bad-bg);border-color:rgba(163,44,54,.35)}
      .dots .dot.warn{background:var(--warn-bg);border-color:rgba(156,71,9,.3)}
      .dots .dot.info{background:var(--info-bg);border-color:rgba(67,56,168,.25)}
      .qrfail{margin-top:9px;padding-top:9px;border-top:1px solid var(--rule-2);font-size:.84rem}
      .qrfail b{font-family:'IBM Plex Mono',monospace;color:var(--bad);font-weight:600;margin-right:6px}
      .qrfail span{color:var(--ink-2)}
      .rca{border:1px solid var(--rule);border-left:3px solid var(--ink-4);border-radius:8px;background:var(--card);padding:13px 16px;margin-bottom:9px}
      .rca.bad{border-left-color:var(--bad)}
      .rca.warn{border-left-color:var(--warn)}
      .rca.info{border-left-color:var(--accent)}
      .rcagrid{display:grid;grid-template-columns:1fr 1fr;gap:12px 26px;margin-top:11px}
      .rca .rl{font-size:.76rem;color:var(--ink-3);margin-bottom:2px}
      .rca .rv{font-size:.87rem;line-height:1.5;color:var(--ink)}
      .rcalist{margin:5px 0 0;padding-left:18px;font-size:.84rem}
      .rcalist li{margin-bottom:5px}
      .rcalist b{font-family:'IBM Plex Mono',monospace;font-size:.8rem;margin-right:5px}
      .rcalist .obs{color:var(--ink-2)}
      /* .rhead was written for .route, so inside an RCA card it was not a
         flex row and the count ran straight into the question name. */
      .rca .rhead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:9px}
      .rca .rhead .rname{font-weight:600;font-size:.95rem}
      .rca .rhead .rmeta{margin-left:auto;color:var(--ink-3);font-size:.8rem}
      .rca .rv b{color:var(--ink);font-weight:600}
      .rca .rid{font-family:'IBM Plex Mono',monospace;font-size:.8rem;color:var(--ink-3);flex:0 0 auto}
      .rca .tag{display:inline-block;font-size:.72rem;font-weight:600;color:var(--ok);background:var(--ok-bg);border-radius:4px;padding:0 6px;margin-right:6px}
      .rca .tag.bad{color:var(--bad);background:var(--bad-bg)}
      .rca .tag.grey{color:var(--ink-2);background:var(--rule-2)}
      .rca .rv p{margin:0 0 7px;max-width:none}
      .rca .owner{margin-top:7px;font-size:.8rem;color:var(--accent);font-weight:500}
      .rca .owner:before{content:"Owner: ";color:var(--ink-3);font-weight:400}
      .jcard{padding:14px 16px}
      .jcard .track{margin:3px 0 0}
      .jcard .stop{min-width:38px;height:27px;font-size:.82rem}
      .jfoot{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:12px;padding-top:10px;border-top:1px solid var(--rule-2)}
      .kchips{display:flex;flex-wrap:wrap;gap:7px}
      .kchip{font-size:.76rem;padding:2px 9px;border-radius:5px;background:var(--rule-2);color:var(--ink-2)}
      .kchip b{color:var(--ink);font-weight:600}
      .jrules{margin-left:auto;font-size:.76rem;color:var(--ink-3);font-family:"IBM Plex Mono",monospace}
      .answ{font-size:.74rem;color:var(--accent);background:var(--accent-soft);padding:2px 8px;border-radius:4px;white-space:nowrap}
      .nextstep{border:1px solid var(--rule);border-left:3px solid var(--accent);border-radius:8px;background:var(--card);padding:14px 17px;margin:4px 0 10px}
      .nextstep .nl{font-size:.74rem;color:var(--accent);font-weight:600;margin-bottom:3px}
      .nextstep .nt{font-size:1.05rem;font-weight:600;margin-bottom:4px}
      .nextstep .nw{font-size:.88rem;color:var(--ink-2);max-width:70ch;line-height:1.5}
      /* The two views have to be switchable from code, so they are a radio
         rather than tabs. Dressed as tabs, because that is what they are. */
      div[data-testid="stRadio"][aria-label="View"] > div{gap:0;border-bottom:1px solid var(--rule);padding-bottom:0}
      div[data-testid="stRadio"] label{padding:8px 18px 9px;margin:0;border-bottom:2px solid transparent}
      div[data-testid="stRadio"] label:has(input:checked){border-bottom-color:var(--accent)}
      div[data-testid="stRadio"] label:has(input:checked) p{color:var(--accent)!important;font-weight:600}
      div[data-testid="stRadio"] label > div:first-child{display:none}
      div[data-testid="stRadio"] label p{font-size:.94rem!important;color:var(--ink-3)}
      .runrow{display:block}
      .rtop{display:flex;align-items:center;gap:12px}
      .rtop .nm{font-weight:600;flex:0 0 auto}
      .rtop .when{margin-left:auto;color:var(--ink-3);font-size:.8rem}
      .spills{display:flex;gap:8px;margin-top:12px;padding-top:11px;border-top:1px solid var(--rule-2)}
      .spill{flex:1;min-width:0}
      .spill .sbar{display:block;height:7px;border-radius:4px;background:var(--rule-2)}
      .spill.done .sbar{background:var(--ok)}
      .spill.now .sbar{background:var(--accent)}
      .spill .slab{display:block;font-size:.73rem;color:var(--ink-4);margin-top:6px;line-height:1.3}
      .spill.done .slab{color:var(--ink-2)}
      .spill.now .slab{color:var(--accent);font-weight:600}
      .sleft{margin-top:10px;font-size:.78rem;color:var(--ink-3)}
      .sleft.ok{color:var(--ok)}
      .runrow2{border:1px solid var(--rule);border-radius:8px;background:var(--card);padding:13px 16px;margin-bottom:7px}
      .r2top{display:flex;align-items:baseline;gap:11px;margin-bottom:11px}
      .r2top .nm{font-weight:600;font-size:.95rem}
      .r2top .when{margin-left:auto;color:var(--ink-3);font-size:.8rem}
      .stages{display:flex;flex-wrap:wrap;gap:0}
      .stg{display:flex;align-items:center;gap:7px;font-size:.8rem;padding-right:20px;position:relative}
      .stg:not(:last-child):after{content:"";position:absolute;right:8px;top:50%;width:12px;height:1px;background:var(--rule)}
      .stg i{width:13px;height:13px;border-radius:50%;flex:0 0 13px;display:inline-block}
      .stg.done{color:var(--ink)}
      .stg.done i{background:var(--ok);box-shadow:inset 0 0 0 2px #fff,0 0 0 1px var(--ok)}
      .stg.todo{color:var(--ink-4)}
      .stg.todo i{background:transparent;border:1px dashed var(--rule)}
      .r2note{margin-top:9px;font-size:.8rem;color:var(--accent)}
      .mapwrap{border:1px solid var(--rule);border-radius:10px;background:var(--card);padding:20px 16px;overflow-x:auto}
      .rca .rv .then{color:var(--accent);display:inline-block;margin-top:4px}
      .rca .rcagrid{border-top:1px solid var(--rule-2);padding-top:11px}
      @media (max-width:900px){.rcagrid{grid-template-columns:1fr}}</style>"""


# --- helpers ---------------------------------------------------------------


def read_json(directory, name, default=None):
    if directory is None:
        return default
    path = Path(directory) / name
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return (data.get("content", data)
            if isinstance(data, dict) and "content" in data else data)


def sentence(value) -> str:
    text = str(value or "").strip()
    return text[:1].upper() + text[1:] if text else ""


#: A status is only useful at a glance if it is coloured by what it means.
#: Green is nothing to do. Red is someone would notice. Amber is unproven or
#: waiting on someone. Blue is a question rather than a fault.
_TONES = {
    "ok": ("PASSED", "WORKING", "READY", "CONFORMS", "BUILT"),
    "bad": ("FAILED", "BROKEN", "SURVEY_DEFECT", "NOT_CONFORMANT", "DEFECT"),
    "warn": ("NOT PROVEN", "BLOCKED", "SPECIFICATION_ERROR", "NOT_BUILT_YET",
             "UNDECIDED", "HARNESS_FAULT"),
    "info": ("INCONCLUSIVE", "SKIPPED", "UNSETTLED_QUESTION", "TEST_MODEL_GAP",
             "RUNNING"),
}


def tone(value) -> str:
    upper = str(value).upper()
    for name, words in _TONES.items():
        if any(w in upper for w in words):
            return name
    return ""


def strip(cells) -> None:
    """Four to six numbers that together say where something stands."""


#: How each kind of ending reads to a person. The code underneath is the
#: questionnaire's own name for it, which belongs in a tooltip rather than on
#: the page: nobody outside the project knows what TERM_INELIGIBLE means.
ENDING_WORDS = {
    "complete": "Finished the survey",
    "screenout": "Termination condition reached",
    "quota_full": "Termination condition reached: quota full",
    "terminate": "Termination condition reached",
}


def ending_name(code: str, kind: str = "") -> str:
    """A friendly name for an ending, falling back to a readable code."""
    if kind and kind.lower() in ENDING_WORDS:
        return ENDING_WORDS[kind.lower()]
    upper = str(code or "").upper()
    if upper.startswith("COMPLETE"):
        return "Finished the survey"
    if "QUOTA" in upper:
        return "Termination condition reached: quota full"
    if upper.startswith("TERM") or "INELIG" in upper or "SCREEN" in upper:
        if "AGE" in upper:
            return "Termination condition reached: too young"
        return "Termination condition reached"
    # An ending the questionnaire named itself: tidy it rather than invent one.
    return str(code or "").replace("_", " ").capitalize()


def section(title: str, blurb: str = "") -> None:
    st.markdown(
        f'<div class="sect"><h2>{html_lib.escape(title)}</h2>'
        + (f'<p>{html_lib.escape(blurb)}</p>' if blurb else "") + "</div>",
        unsafe_allow_html=True)


def waiting(what: str, why: str, then: str = "", warn: bool = False) -> None:
    """An empty screen is an invitation to act, so it says what to do."""
    st.markdown(
        f'<div class="empty{" warnbox" if warn else ""}">'
        f'<div class="etitle">{html_lib.escape(what)}</div>'
        f'<div class="ebody">{html_lib.escape(why)}</div>'
        + (f'<div class="ethen">{html_lib.escape(then)}</div>' if then else "")
        + "</div>", unsafe_allow_html=True)


def table(rows, widths=None, numeric=(), pills=(), height="60vh") -> None:
    """A fixed-layout HTML table.

    Used instead of st.dataframe, which draws to a canvas and so ignores any
    font size or column width you set.
    """
    if not rows:
        st.markdown('<div class="empty"><div class="ebody">Nothing to show '
                    'here.</div></div>', unsafe_allow_html=True)
        return
    widths = widths or {}
    columns = list(rows[0])
    head = "".join(
        f'<th style="width:{widths.get(c, "auto")}">{html_lib.escape(c)}</th>'
        for c in columns)
    body = []
    for index, row in enumerate(rows):
        cells = []
        for column in columns:
            raw = "" if row.get(column) is None else str(row.get(column))
            text = html_lib.escape(raw)
            if column in pills and raw:
                text = f'<span class="pill {tone(raw)}">{text}</span>'
            css = ' class="num"' if column in numeric else ""
            cells.append(f"<td{css}>{text}</td>")
        body.append('<tr class="{}">{}</tr>'.format(
            "odd" if index % 2 else "even", "".join(cells)))
    st.markdown(
        f'<div class="tblwrap" style="max-height:{height}">'
        f'<table class="tbl"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>',
        unsafe_allow_html=True)


def file_rows(files) -> None:
    for path in files:
        if not path.is_file():
            continue
        left, right = st.columns([5, 1])
        left.write(path.name)
        right.download_button("Download", data=path.read_bytes(),
                              file_name=path.name, key=str(path))


def question_card(q: dict) -> str:
    """A question as it reads in the questionnaire, not as a database row."""
    options = q.get("options") or []
    shown = q.get("display_condition") or ""
    chips = "".join(
        f'<span class="opt">{html_lib.escape(str(o.get("label", o) if isinstance(o, dict) else o))}</span>'
        for o in options[:9])
    if len(options) > 9:
        chips += f'<span class="opt more">and {len(options) - 9} more</span>'
    guard = (f'<div class="qguard">Shown only when {html_lib.escape(shown)}</div>'
             if shown else "")
    return (
        f'<div class="qcard"><div class="qtop">'
        f'<span class="qid">{html_lib.escape(str(q.get("id","")))}</span>'
        f'<span class="pill">{html_lib.escape(sentence(q.get("type")))}</span>'
        f'</div><div class="qtext">'
        f'{html_lib.escape(str(q.get("wording","")))}</div>'
        f'<div class="opts">{chips}</div>{guard}</div>')


def rule_card(r: dict) -> str:
    """A routing rule read as the sentence it is: when this, do that."""
    action = sentence(r.get("action"))
    dest = r.get("destination") or ""
    # Built outside the f-string: Python before 3.12 refuses a backslash
    # inside an f-string expression, and an escape for the dash counts.
    condition = html_lib.escape(str(r.get("condition_raw") or "not stated"))
    return (
        f'<div class="rule">'
        f'<span class="rid">{html_lib.escape(str(r.get("rule","")))}</span>'
        f'<span class="when">when {condition}</span>'
        f'<span class="arrow">\u2192</span>'
        f'<span class="act">{html_lib.escape(action)}'
        + (f' {html_lib.escape(dest)}' if dest else "") + "</span></div>")


def meter(label: str, covered: int, total: int, status: str = "") -> str:
    """One coverage reading as a bar.

    Nine numbers in a column are nine numbers. Nine bars are a shape, and the
    short one is the answer to the only question anyone asks of this table.
    """
    pct = (covered / total * 100) if total else 0
    shade = "ok" if pct >= 100 else ("warn" if pct >= 50 else "bad")
    return (
        f'<div class="meter"><div class="mlabel">{html_lib.escape(label)}</div>'
        f'<div class="mtrack"><div class="mfill {shade}" '
        f'style="width:{pct:.0f}%"></div></div>'
        f'<div class="mval">{covered}<span>/{total}</span></div>'
        f'<div class="mstat">{html_lib.escape(status.lower())}</div></div>')


def answer_label(spec_questions: list, qid: str, option_id: str) -> str:
    """The words a respondent would see for the option this journey takes."""
    for q in spec_questions:
        if q.get("id") != qid:
            continue
        for o in (q.get("options") or []):
            if isinstance(o, dict) and o.get("option_id") == option_id:
                return str(o.get("label") or option_id)
    return str(option_id)


def journey_steps(path: dict, questions: list) -> str:
    """The route with the answer that sends it that way, at each fork.

    A list of question names says which questions were asked and nothing
    about why. What makes a journey distinct is the answers that define it,
    so those are shown at the points where they matter.
    """
    decisions = path.get("decisions") or {}
    parts = []
    for qid in path.get("sequence") or []:
        parts.append(f'<span class="stop quiet">{html_lib.escape(qid)}</span>')
        chosen = decisions.get(qid)
        if chosen:
            words = answer_label(questions, qid, chosen)
            parts.append(f'<span class="answ">answers '
                         f'&ldquo;{html_lib.escape(words)}&rdquo;</span>')
    ending = path.get("disposition") or "COMPLETE"
    parts.append(f'<span class="stop end" title="{html_lib.escape(ending)}">'
                 f'{html_lib.escape(ending_name(ending))}</span>')
    return '<span class="link"></span>'.join(parts)


def journey_card(path: dict, verdict: dict, failures_at: dict) -> str:
    """One respondent journey drawn as the route it is.

    A table row can say P03 broke. It cannot say where, and where is the thing
    a survey programmer needs. So the questions are stops along a track,
    coloured by what happened at each.
    """
    status = verdict.get("status", "WORKING")
    klass = {"WORKING": "working", "BROKEN": "broken"}.get(status, "unproven")
    # The answers that define the journey belong here too, not only on the
    # Tests page. Without them a screen-out reads as a single question and
    # nothing about why the respondent stopped there.
    decisions = path.get("decisions") or {}
    stops = []
    for qid in path.get("sequence") or []:
        trouble = failures_at.get(qid)
        cls = "fail" if trouble == "real" else ("unproven" if trouble else "")
        stops.append(f'<span class="stop {cls}">{html_lib.escape(qid)}</span>')
        chosen = decisions.get(qid)
        if chosen:
            words = answer_label(QUESTIONS, qid, chosen)
            stops.append(f'<span class="answ">answered '
                         f'&ldquo;{html_lib.escape(words)}&rdquo;</span>')
    ending = path.get("disposition") or "COMPLETE"
    track = '<span class="link"></span>'.join(stops)
    track += ('<span class="link"></span>'
              f'<span class="stop end" title="{html_lib.escape(ending)}">'
              f'{html_lib.escape(ending_name(ending))}</span>')
    why = ""
    if verdict.get("broke_at"):
        # "Came unstuck" claims something went wrong. On a journey where
        # nothing is known to be wrong it would contradict the status beside it.
        lead = ("First came unstuck at" if status == "BROKEN"
                else "Could not be proved at")
        why = (f'<div class="rwhy">{lead} '
               f'<b>{html_lib.escape(verdict["broke_at"])}</b> \u2014 '
               f'{html_lib.escape(verdict.get("first_failure") or "")}</div>')
    return (
        f'<div class="route {klass}"><div class="rhead">'
        f'<span class="rid">{html_lib.escape(path.get("path_id",""))}</span>'
        f'<span class="rname">{html_lib.escape(path.get("name",""))}</span>'
        f'<span class="pill {tone(status)}">{status}</span>'
        f'<span class="rmeta">{verdict.get("passed",0)} of '
        f'{verdict.get("tests",0)} checks passed</span></div>'
        f'<div class="track">{track}</div>{why}</div>')


def graphviz_missing() -> None:
    """Say what is missing and how to get it, rather than crashing the page."""
    st.warning(
        "**Diagrams need Graphviz**, which is a separate program rather than "
        "the Python package of the same name. Everything else on this page "
        "works without it. No administrator rights are needed: download the "
        "Windows zip from gitlab.com/graphviz/graphviz/-/releases, unzip it to "
        "`C:\\ISB-Capstone\\graphviz`, and restart. It looks there on startup.")


def clear_downstream(*keys: str) -> None:
    for key in keys:
        st.session_state.pop(key, None)


PAGES = [("overview", "Overview"), ("questionnaire", "Questionnaire"),
         ("survey", "Survey"), ("tests", "Tests"),
         ("run", "Respondent Bot"), ("quality", "Quality report"),
         ("files", "Files")]


def survey_state(name: str) -> dict:
    """How far one survey has got, and what it needs next.

    Read from what is on disk rather than from session state, so the workspace
    is right even for runs this session has never opened.
    """
    directory = OUT / name
    lss = OUT / f"{name}_generated.lss"
    design = directory / "agent3"
    bot = directory / "agent4"
    qc = directory / "agent5"

    summary = read_json(design, "agent3_summary.json", {}) or {}
    results = read_json(bot, "agent4_results.json", {}) or {}
    findings = read_json(qc, "agent5_findings.json", {}) or {}

    stage = 1
    if lss.exists():
        stage = 2
    if summary:
        stage = 3
    if results:
        stage = 4
    if findings:
        stage = 5

    journeys = findings.get("journeys", [])
    broken = [j for j in journeys if j.get("status") == "BROKEN"]
    groups = findings.get("groups", [])
    real = [g for g in groups
            if g.get("cause") in ("SURVEY_DEFECT", "SPECIFICATION_ERROR",
                                  "NOT_BUILT_YET")]
    questions_for_client = [g for g in groups
                            if g.get("cause") == "UNSETTLED_QUESTION"]

    if findings:
        label, shade = (("Ready", "ok") if not broken
                        else (f"{len(real)} to fix", "bad"))
    elif results:
        label, shade = "Not judged yet", ""
    elif summary:
        label, shade = "Tests not run", ""
    elif lss.exists():
        label, shade = "Tests not designed", ""
    else:
        label, shade = "Survey not built", ""

    when = "\u2014"
    for candidate in (qc / "agent5_findings.json",
                      bot / "agent4_results.json",
                      design / "agent3_summary.json",
                      directory / "part2_canonical.json"):
        if candidate.exists():
            age = time.time() - candidate.stat().st_mtime
            if age < 3600:
                when = f"{int(age // 60)} minutes ago"
            elif age < 86400:
                when = f"{int(age // 3600)} hours ago"
            else:
                when = f"{int(age // 86400)} days ago"
            break

    return {
        "name": name, "directory": directory, "lss": lss,
        "design_dir": design, "bot_dir": bot, "qc_dir": qc,
        "has_lss": lss.exists(), "summary": summary, "results": results,
        "findings": findings, "stage": stage, "label": label, "shade": shade,
        "when": when, "journeys": journeys, "broken": broken,
        "groups": groups, "real": real,
        "questions_for_client": questions_for_client,
    }
#: How each kind of route is drawn. Extracted with to_dot rather than left
#: behind, which is what broke the flow graph the first time.
#: Each kind of route in the product's own colours, so the diagram belongs
#: to the same thing as the rest of the pages.
EDGE_STYLE = {
    "advance": ("#A8A3BE", "solid", "normal", ""),
    "jump": ("#0F766E", "dashed", "normal", "skip to"),
    "terminate": ("#A32C36", "solid", "normal", "end"),
    "visibility": ("#4338A8", "dotted", "empty", "shown if"),
    "quota": ("#9C4709", "dotted", "normal", "quota"),
}

#: fill, border, text
DISPOSITION_FILL = {
    "complete": ("#DAEDEA", "#0F766E", "#0F766E"),
    "screenout": ("#F8E4E6", "#A32C36", "#A32C36"),
    "quota_full": ("#FAEBDE", "#9C4709", "#9C4709"),
}


def to_dot(graph, zoom: float, vertical: bool = True) -> str:
    """The survey drawn as a route map rather than a node diagram.

    Three decisions do most of the work. The main line of questions is
    weighted heavily so it draws as one straight spine, and everything that
    leaves it reads as a departure from that spine. Endings are drawn as
    stadium shapes in their own colours, so they never look like questions.
    And each question carries its own name in full rather than a code, with
    the condition that reveals it shown beneath.
    """
    lines = [
        "digraph {",
        f"  rankdir={'TB' if vertical else 'LR'};",
        "  pad=0.4;",
        f"  dpi={72 * zoom:.0f};",
        "  nodesep=0.5;",
        "  ranksep=0.62;",
        "  splines=spline;",
        '  bgcolor="transparent";',
        '  node [fontname="IBM Plex Sans,Helvetica" fontsize=11.5 '
        'penwidth=1.3 margin="0.22,0.12" style="filled,rounded" shape=box '
        'height=0.44];',
        '  edge [fontname="IBM Plex Sans,Helvetica" fontsize=9 penwidth=1.3 '
        'arrowsize=0.7 color="#C7C2DC"];',
    ]

    for name, data in graph.nodes(data=True):
        if data.get("kind") == "start":
            continue
        label = data.get("label") or name
        if data.get("kind") in ("disposition", "ending"):
            fill, edge, ink = DISPOSITION_FILL.get(
                data.get("disposition_kind"), ("#F8E4E6", "#A32C36", "#A32C36"))
            # A stadium, so an ending never reads as one more question.
            lines.append(
                f'  "{name}" [label="{ending_name(name, data.get("disposition_kind"))}" '
                f'shape=box style="filled,rounded" fillcolor="{fill}" '
                f'color="{edge}" fontcolor="{ink}" penwidth=1.7 '
                f'fontsize=11 height=0.5 margin="0.3,0.14" '
                f'tooltip="{name}"];')
        else:
            conditional = str(data.get("has_guard")).lower() == "true"
            tip = data.get("guard") or ""
            plain = (tip.replace(" eq ", " is ").replace(" ne ", " is not ")
                     .replace(" == ", " is ").replace(" != ", " is not "))
            shown = (f'<<b>{label}</b><br/><font color="#4338A8" '
                     f'point-size="9">only if {plain[:36]}</font>>'
                     if conditional and plain else f'"{label}"')
            lines.append(
                f'  "{name}" [label={shown} '
                f'style="filled,rounded{",dashed" if conditional else ""}" '
                f'fillcolor="{"#F6F4FC" if conditional else "#FFFFFF"}" '
                f'color="{"#4338A8" if conditional else "#D6D1E8"}" '
                f'fontcolor="#1B1832"'
                + (f' tooltip="{tip}"' if tip else "") + "];")

    for source, target, data in graph.edges(data=True):
        if graph.nodes[source].get("kind") == "start":
            continue
        colour, style, arrow, prefix = EDGE_STYLE.get(
            data.get("kind"), ("#C7C2DC", "solid", "normal", ""))
        rule = data.get("rule_id") or ""
        label = f" {prefix} {rule} ".strip() if (prefix or rule) else ""
        tip = (data.get("condition") or "").replace('"', "'")
        # The ordinary forward path is weighted so it draws as one spine and
        # everything else reads as leaving it.
        weight = 20 if data.get("kind") == "advance" else 1
        lines.append(
            f'  "{source}" -> "{target}" [label="{label}" color="{colour}" '
            f'fontcolor="{colour}" style={style} arrowhead={arrow} '
            f'weight={weight}'
            + (f' tooltip="{tip}"' if tip else "") + "];")
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



# --- pages -----------------------------------------------------------------


def upload_panel() -> None:
    """Starting a new survey belongs on the list of surveys.

    It was in the rail, where it sat beneath the navigation for whichever
    survey happened to be open, which is not where anyone would look for it.
    """
    uploaded = st.file_uploader(
        "Add a questionnaire", type="docx",
        help="A Word document. The platform reads it, builds the survey, "
             "designs the checks, runs them and reports what is wrong.")
    if not uploaded:
        return
    pending = Path(uploaded.name).stem
    if (OUT / pending).exists():
        st.caption(f"{pending} has already been read. Open it below, or "
                   f"delete that run to start again.")
        return
    if st.button("Read the questionnaire", type="primary", key="go_interp"):
        UPLOADS.mkdir(parents=True, exist_ok=True)
        source = UPLOADS / uploaded.name
        source.write_bytes(uploaded.getbuffer())
        run_interpreter(source)
        st.rerun()


def page_workspace() -> None:
    names = sorted((p.name for p in OUT.iterdir() if p.is_dir()),
                   key=lambda n: (OUT / n).stat().st_mtime, reverse=True) \
        if OUT.exists() else []
    states = [survey_state(n) for n in names]

    st.markdown("# Surveys")
    upload_panel()
    if not states:
        waiting("Nothing here yet",
                "Upload a questionnaire in the sidebar. The platform reads it, "
                "builds the survey, designs the tests, runs them as a "
                "respondent, and tells you what is wrong.",
                "Upload a .docx to begin")
        return

    ready = [s for s in states if s["findings"] and not s["broken"]]
    attention = [s for s in states if s["broken"]]
    st.markdown(f'<p class="blurb">{len(states)} in progress. '
                f'{len(attention)} need attention.</p>', unsafe_allow_html=True)
    strip([("Ready to field", len(ready), "ok" if ready else "idle"),
           ("Need attention", len(attention), "bad" if attention else "ok"),
           ("Not yet run", len(states) - len(ready) - len(attention), ""),
           ("Surveys in the workspace", len(states), "")])

    # Five anonymous bars said how far a survey had got without saying what
    # any of the stages were. Naming them means a reader can see what is left
    # rather than counting segments.
    STAGES = [("Questionnaire read", "questionnaire"),
              ("Survey built", "survey"),
              ("Checks designed", "tests"),
              ("Checks run", "run"),
              ("Results judged", "quality")]
    for s in states:
        steps = "".join(
            f'<span class="stg {"done" if i < s["stage"] else "todo"}">'
            f'<i></i>{html_lib.escape(label)}</span>'
            for i, (label, _) in enumerate(STAGES))
        remaining = [label for i, (label, _) in enumerate(STAGES)
                     if i >= s["stage"]]
        note = ("everything done" if not remaining
                else "next: " + remaining[0].lower())
        row = (f'<div class="runrow2">'
               f'<div class="r2top"><span class="nm">'
               f'{html_lib.escape(s["name"])}</span>'
               f'<span class="pill {s["shade"]}">{s["label"]}</span>'
               f'<span class="when">{s["when"]}</span></div>'
               f'<div class="stages">{steps}</div>'
               f'<div class="r2note">{html_lib.escape(note)}</div></div>')
        left, right = st.columns([9, 1])
        left.markdown(row, unsafe_allow_html=True)
        if right.button("Open", key=f"open_{s['name']}"):
            st.session_state["run_name"] = s["name"]
            st.session_state["page"] = "overview"
            st.rerun()


def next_step(s: dict) -> None:
    """Say what happens next, and take them there.

    The Overview is where someone lands, so it should not merely describe
    the state. Naming the next stage and offering the button removes a step
    of working out which page to open.
    """
    if not s["has_lss"]:
        where, label, why = "survey", "Build the survey", (
            "Turns the questionnaire into a LimeSurvey file. Nothing after "
            "this can run without it.")
    elif not s["summary"]:
        where, label, why = "tests", "Design the checks", (
            "Works out every journey through the survey and writes a check "
            "for each thing the questionnaire claims.")
    elif not s["results"]:
        where, label, why = "run", "Run the Respondent Bot", (
            "Answers the survey as a respondent would, once per check, and "
            "records what happened.")
    elif not s["findings"]:
        where, label, why = "quality", "Work out what it means", (
            "Decides what each failure means and who should act on it.")
    else:
        return

    st.markdown(f'<div class="nextstep"><div class="nl">Next step</div>'
                f'<div class="nt">{html_lib.escape(label)}</div>'
                f'<div class="nw">{html_lib.escape(why)}</div></div>',
                unsafe_allow_html=True)
    if st.button(label, type="primary", key=f"next_{where}"):
        st.session_state["page"] = where
        st.rerun()


def page_overview(s: dict) -> None:
    if not s["has_lss"]:
        st.markdown("# Survey not built")
        st.markdown('<p class="blurb">The questionnaire has been read. Nothing '
                    'else can happen until the survey file exists.</p>',
                    unsafe_allow_html=True)
        strip([("Questions", len(QUESTIONS), ""), ("Routing rules", len(ROUTING), ""),
               ("Survey file", "Not built", "idle"), ("Tests", "\u2014", "idle")])
        next_step(s)
        return

    if not s["findings"]:
        st.markdown("# Not judged yet")
        st.markdown('<p class="blurb">The pipeline has not been taken all the '
                    'way through for this survey.</p>', unsafe_allow_html=True)
        strip([("Questions", len(QUESTIONS), ""),
               ("Routing rules", len(ROUTING), ""),
               ("Tests designed", s["summary"].get("logical_tests", "\u2014"), ""),
               ("Tests run", sum(s["results"].get("counts", {}).values())
                if s["results"] else "\u2014", "")])
        next_step(s)
        return

    good = [j for j in s["journeys"] if j.get("status") == "WORKING"]
    ready = not s["broken"]
    st.markdown(f"# {'Ready to field' if ready else 'Needs attention'}")
    st.markdown(
        '<p class="blurb">'
        + ("Every journey works and no defect is outstanding."
           if ready else
           "A respondent would meet something wrong on at least one journey.")
        + "</p>", unsafe_allow_html=True)

    counts = s["results"].get("counts", {})
    strip([
        ("Journeys", f"{len(good)} of {len(s['journeys'])}",
         "ok" if ready else "bad"),
        ("Tests passed",
         f"{counts.get('PASSED', 0)} of {sum(counts.values())}", ""),
        ("Defects", len(s["real"]), "bad" if s["real"] else "ok"),
        ("Waiting on the client", len(s["questions_for_client"]),
         "warn" if s["questions_for_client"] else "ok"),
        ("Last run", s["when"], ""),
    ])

    section("The journeys")
    for card in journey_cards(s):
        st.markdown(card, unsafe_allow_html=True)

    if s["questions_for_client"]:
        waiting(f"{len(s['questions_for_client'])} questions for the client",
                "Points the questionnaire never settled. Neither a defect nor "
                "a pass until someone decides.",
                "See the quality report", warn=True)


def journey_cards(s: dict):
    """The journeys, with each failure placed on the question it landed on."""
    REAL = {"SURVEY_DEFECT", "SPECIFICATION_ERROR", "NOT_BUILT_YET"}
    failures_at: dict = {}
    for j in s["findings"].get("judgements", []):
        q = j.get("question")
        if not q:
            continue
        if j.get("cause") in REAL:
            failures_at[q] = "real"
        else:
            failures_at.setdefault(q, "soft")
    shapes = {p.get("path_id"): p
              for p in (read_json(s["design_dir"], "agent3_paths.json", {})
                        or {}).get("paths", [])}
    out = []
    for v in sorted(s["journeys"], key=lambda x: x.get("path_id", "")):
        shape = shapes.get(v.get("path_id"))
        if shape:
            out.append(journey_card(shape, v, failures_at))
    return out


def page_questionnaire(s: dict) -> None:
    st.markdown("# The questionnaire as the platform read it")
    st.markdown(
        f'<p class="blurb">{len(QUESTIONS)} questions and {len(ROUTING)} '
        f'rules. Check these against your document before trusting anything '
        f'after this point.</p>', unsafe_allow_html=True)

    tab_q, tab_r, tab_g = st.tabs(["Questions", "Routing rules", "Flow"])

    with tab_q:
        if not QUESTIONS:
            waiting("Nothing was read from the document",
                    "This run produced no questionnaire. The document may not "
                    "have been readable, or the run may have stopped early.")
        else:
            st.markdown("".join(question_card(q) for q in QUESTIONS),
                        unsafe_allow_html=True)

    with tab_r:
        if not ROUTING:
            waiting("No routing rules",
                    "Every respondent sees every question, because nothing in "
                    "the questionnaire skips or screens anyone out.")
        else:
            st.markdown("".join(rule_card(r) for r in ROUTING),
                        unsafe_allow_html=True)
            with st.expander("The expressions these become in LimeSurvey"):
                table([{"Rule": r.get("rule"),
                        "Expression": r.get("condition_expression")}
                       for r in ROUTING], widths={"Rule": "9%"}, height="34vh")

    with tab_g:
        draw_flow(s)


def survey_map(graph, spec_questions: list) -> str:
    """The survey drawn as a line a respondent travels down.

    Graphviz lays out a general graph, and a questionnaire is not a general
    graph: it is a spine with a few exits. Drawing it directly lets the spine
    be a straight line, the exits be short branches off it, and a skip be a
    curve that visibly bypasses the questions it skips.

    It also removes the dependency on a separate Graphviz install, which was
    a barrier on a managed laptop.
    """
    order, seen = [], set()
    for node, data in graph.nodes(data=True):
        if data.get("kind") == "question" and node not in seen:
            order.append(node)
            seen.add(node)
    if not order:
        return ""

    exits, skips = [], []
    for source, target, data in graph.edges(data=True):
        kind = data.get("kind")
        if kind == "terminate" and source in seen:
            exits.append((source, target, data.get("rule_id") or ""))
        elif kind == "jump" and source in seen and target in seen:
            skips.append((source, target, data.get("rule_id") or ""))

    STEP, TOP, LEFT = 58, 34, 210
    height = TOP + STEP * len(order) + 74
    width = 680
    conditional = {n for n, d in graph.nodes(data=True)
                   if str(d.get("has_guard")).lower() == "true"}
    y = {q: TOP + i * STEP for i, q in enumerate(order)}

    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'style="max-width:{width}px" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="IBM Plex Sans, system-ui, sans-serif">']

    # the spine
    out.append(f'<line x1="{LEFT}" y1="{TOP}" x2="{LEFT}" '
               f'y2="{TOP + STEP * (len(order) - 1)}" stroke="#C7C2DC" '
               f'stroke-width="3" stroke-linecap="round"/>')

    # a skip curves out to the left, so it visibly goes around
    for source, target, rule in skips:
        y1, y2 = y[source], y[target]
        bulge = LEFT - 62
        out.append(
            f'<path d="M {LEFT} {y1} C {bulge} {y1 + 14}, {bulge} {y2 - 14}, '
            f'{LEFT} {y2}" fill="none" stroke="#0F766E" stroke-width="2.5" '
            f'stroke-dasharray="6 4" stroke-linecap="round"/>')
        out.append(
            f'<text x="{bulge - 8}" y="{(y1 + y2) / 2 + 4}" font-size="11.5" '
            f'fill="#0F766E" text-anchor="end">skips ahead</text>')
        if rule:
            out.append(
                f'<text x="{bulge - 8}" y="{(y1 + y2) / 2 + 19}" '
                f'font-size="10" fill="#7C7796" text-anchor="end">'
                f'rule {rule}</text>')

    # each exit branches right to its own terminus
    used_y = {}
    for source, target, rule in exits:
        y1 = y[source]
        ty = y1 + used_y.get(y1, 0) * 26
        used_y[y1] = used_y.get(y1, 0) + 1
        tx = LEFT + 250
        out.append(
            f'<path d="M {LEFT} {y1} C {LEFT + 90} {y1}, {tx - 90} {ty}, '
            f'{tx} {ty}" fill="none" stroke="#A32C36" stroke-width="2"/>')
        label = ending_name(target)
        out.append(
            f'<rect x="{tx}" y="{ty - 13}" width="196" height="26" rx="13" '
            f'fill="#F8E4E6" stroke="#A32C36" stroke-width="1.2"/>')
        out.append(
            f'<text x="{tx + 98}" y="{ty + 4.5}" font-size="11.5" '
            f'fill="#A32C36" text-anchor="middle">'
            f'{_x(label)}</text>')

    # the stations
    for q in order:
        yy = y[q]
        is_cond = q in conditional
        out.append(
            f'<circle cx="{LEFT}" cy="{yy}" r="9" fill="#FFFFFF" '
            f'stroke="{"#4338A8" if is_cond else "#7C7796"}" '
            f'stroke-width="{3 if is_cond else 2.5}"'
            + (' stroke-dasharray="3 2"' if is_cond else "") + '/>')
        out.append(
            f'<text x="{LEFT - 20}" y="{yy + 5}" font-size="13" '
            f'font-weight="600" fill="#1B1832" text-anchor="end">{_x(q)}</text>')
        wording = next((w.get("wording", "") for w in spec_questions
                        if w.get("id") == q), "")
        if wording:
            short = wording if len(wording) < 58 else wording[:56] + "\u2026"
            out.append(
                f'<text x="{LEFT + 20}" y="{yy + 4.5}" font-size="11.5" '
                f'fill="#4A4566">{_x(short)}</text>')
        if is_cond:
            out.append(
                f'<text x="{LEFT - 20}" y="{yy + 18}" font-size="10" '
                f'fill="#4338A8" text-anchor="end">only sometimes shown</text>')

    # the end of the line
    last_y = TOP + STEP * (len(order) - 1) + 44
    out.append(f'<line x1="{LEFT}" y1="{TOP + STEP * (len(order) - 1)}" '
               f'x2="{LEFT}" y2="{last_y - 14}" stroke="#C7C2DC" '
               f'stroke-width="3"/>')
    out.append(f'<rect x="{LEFT - 92}" y="{last_y - 14}" width="184" '
               f'height="28" rx="14" fill="#DAEDEA" stroke="#0F766E" '
               f'stroke-width="1.4"/>')
    out.append(f'<text x="{LEFT}" y="{last_y + 4.5}" font-size="12" '
               f'fill="#0F766E" text-anchor="middle" font-weight="500">'
               f'Finished the survey</text>')
    out.append("</svg>")
    return "".join(out)


def _x(text) -> str:
    return html_lib.escape(str(text or ""))


def flow_diagram(s: dict) -> None:
    graph_file = s["directory"] / "route_graph.graphml"
    if not graph_file.exists():
        waiting("No route map in this run",
                "The interpreter writes route_graph.graphml alongside the "
                "questionnaire. This run does not have one.")
        return
    try:
        graph = nx.read_graphml(graph_file)
    except Exception as exc:
        st.error(f"The route map could not be read: {exc}")
        return

    endings = sum(1 for _, data in graph.nodes(data=True)
                  if data.get("kind") in {"ending", "disposition"})
    strip([("Questions", graph.number_of_nodes() - endings - 1, ""),
           ("Routes between them", graph.number_of_edges(), ""),
           ("Ways to finish", endings, "")])
    st.markdown('<p class="blurb">The line a respondent travels down. A ring '
                'that is dashed and indigo is a question only some people '
                'see. A curve to the left skips ahead. A branch to the right '
                'is a way out of the survey.</p>', unsafe_allow_html=True)

    st.markdown(f'<div class="mapwrap">{survey_map(graph, QUESTIONS)}</div>',
                unsafe_allow_html=True)

    with st.expander("The same thing as a conventional diagram"):
        try:
            svg = graphviz.Source(
                to_dot(graph, 1.2, True)).pipe(format="svg").decode()
            st.markdown(f'<div class="graphwrap">{svg}</div>',
                        unsafe_allow_html=True)
        except ExecutableNotFound:
            graphviz_missing()


def draw_flow(s: dict) -> None:
    """The whole survey as one picture."""
    st.markdown('<p class="blurb">Every question and every route between '
                'them. A dashed outline is a question shown only under a '
                'condition.</p>', unsafe_allow_html=True)

    graph_file = s["directory"] / "route_graph.graphml"
    if not graph_file.exists():
        waiting("No picture for this run",
                "The interpreter writes route_graph.graphml alongside the "
                "questionnaire. This run does not have one.")
        return
    try:
        graph = nx.read_graphml(graph_file)
    except Exception as exc:
        st.error(f"The picture could not be drawn: {exc}")
        return

    endings = sum(1 for _, data in graph.nodes(data=True)
                  if data.get("kind") in {"ending", "disposition"})
    strip([("Questions", graph.number_of_nodes() - endings - 1, ""),
           ("Routes between them", graph.number_of_edges(), ""),
           ("Ways to finish", endings, "")])

    st.session_state.setdefault("zoom", 1.4)
    minus, plus, reset, vert, _ = st.columns([1, 1, 1, 2, 5])
    if minus.button("Smaller", key="zo", use_container_width=True):
        st.session_state["zoom"] = max(0.6, st.session_state["zoom"] - 0.3)
    if plus.button("Bigger", key="zi", use_container_width=True):
        st.session_state["zoom"] = min(4.0, st.session_state["zoom"] + 0.3)
    if reset.button("Fit", key="zf", use_container_width=True):
        st.session_state["zoom"] = 1.0
    sideways = vert.toggle("Left to right", value=False, key="zv")

    try:
        svg = graphviz.Source(
            to_dot(graph, st.session_state["zoom"], not sideways)
        ).pipe(format="svg").decode()
    except ExecutableNotFound:
        graphviz_missing()
        svg = ""
    if svg:
        st.markdown(f'<div class="graphwrap">{svg}</div>',
                    unsafe_allow_html=True)
    st.markdown(
        '<div class="legend">'
        '<span><span class="swatch" style="background:#FFFFFF;'
        'border:1px solid #D6D1E8"></span>a question</span>'
        '<span><span class="swatch" style="background:#F4F1FC;'
        'border:1px dashed #4338A8"></span>shown only under a condition</span>'
        '<span><span class="swatch" style="background:#DAEDEA"></span>'
        'finished the survey</span>'
        '<span><span class="swatch" style="background:#F8E4E6"></span>'
        'screened out</span></div>', unsafe_allow_html=True)


def page_survey(s: dict) -> None:
    st.markdown("# The survey file")
    st.markdown('<p class="blurb">The builder turns the specification into a '
                '.lss that LimeSurvey can import. It stops rather than '
                'guessing, so a question it cannot translate is named rather '
                'than approximated.</p>', unsafe_allow_html=True)

    if not s["has_lss"]:
        if st.button("Build the survey", type="primary", key="build_here"):
            build_survey(s)
            st.rerun()
        log = st.session_state.get(f"build_log::{s['name']}", "")
        if not log:
            waiting("Not built yet",
                    "The questionnaire has been read. Building it produces the "
                    "file everything after this is tested against.")
        else:
            st.error("The survey could not be built.")
            for line in log.splitlines():
                if line.strip() and not line.startswith("out/"):
                    st.markdown(f"- {line.strip()}")
            with st.expander("Full build log"):
                st.code(log)
        return

    size = s["lss"].stat().st_size / 1024
    strip([("Survey file", "Built", "ok"), ("Size", f"{size:.0f} KB", ""),
           ("Questions carried", len(QUESTIONS), ""),
           ("Survey id in LimeSurvey",
            st.session_state.get("sid", "900001"), "sm")])
    left, right = st.columns([1, 3])
    left.download_button("Download the .lss file", data=s["lss"].read_bytes(),
                         file_name=s["lss"].name, mime="application/xml",
                         type="primary")
    if right.button("Build it again", key="rebuild_here"):
        s["lss"].unlink(missing_ok=True)
        build_survey(s)
        st.rerun()
    st.markdown("Import it under **Surveys \u2192 Create \u2192 Import**, then "
                "activate it. An inactive survey will not serve respondents, "
                "so the bot cannot test it.")


DIMENSION_NAMES = {
    "D1": "Showing, hiding and flow", "D2": "Endings", "D3": "Answer rules",
    "D4": "Compulsory questions", "D5": "Carried-forward options",
    "D6": "Carried-forward wording", "D7": "Shuffled questions",
    "D8": "Quotas", "D9": "Combinations",
}


def page_tests(s: dict) -> None:
    st.markdown("# What will be checked")
    if not s["has_lss"]:
        waiting("Waiting on the survey file",
                "Tests can be designed without it, but none would be runnable: "
                "there would be no field to bind an answer to.",
                "Build the survey first")
        return
    if not s["summary"]:
        if st.button("Design the tests", type="primary", key="design_here"):
            design_tests(s)
            st.rerun()
        waiting("No tests designed yet",
                "The designer works out every distinct journey and writes a "
                "check for each behaviour the questionnaire claims.")
        return
    if st.button("Design the tests again", key="redesign_here"):
        design_tests(s)
        st.rerun()

    d = s["summary"]
    report = (read_json(s["design_dir"], "agent3_paths.json", {}) or {}
              ).get("report", {})
    paths = (read_json(s["design_dir"], "agent3_paths.json", {}) or {}
             ).get("paths", [])
    index = (read_json(s["design_dir"], "agent3_test_case_index.json", {})
             or {}).get("tests", [])

    st.markdown(
        f'<p class="blurb">{d.get("logical_tests", 0)} tests across '
        f'{len(paths)} journeys. Every test runs on one of these routes, '
        f'because a test that cannot be reached proves nothing.</p>',
        unsafe_allow_html=True)
    strip([("Journeys", len(paths), ""),
           ("Test cases", d.get("logical_tests", "\u2014"), ""),
           ("Runnable", d.get("executable_tests", "\u2014"), ""),
           ("Weakest reading", f"{d.get('coverage_floor_pct', 0)}%",
            "ok" if d.get("coverage_floor_pct", 0) >= 100 else "warn")])

    # ---- journeys first, because that is how the tests are organised ----
    section("The journeys, and what is checked along each",
            "Exclusive, and every branch taken in both directions by at least "
            "one of them. Open a journey to see its checks.")

    by_path: dict = {}
    for row in index:
        by_path.setdefault(row.get("path_id") or "\u2014", []).append(row)

    KINDS = {
        "D1": "Showing and hiding", "D2": "Endings", "D3": "Answer rules",
        "D4": "Compulsory", "D5": "Carried-forward options",
        "D6": "Carried-forward wording", "D7": "Shuffling", "D8": "Quotas",
        "D9": "Combinations",
    }

    for path in paths:
        pid = path.get("path_id")
        tests_here = by_path.get(pid, [])
        kinds = {}
        for t in tests_here:
            name = KINDS.get(t.get("dimension"), t.get("dimension"))
            kinds[name] = kinds.get(name, 0) + 1
        # Quiet chips, not a full-width bar. The track is what a reader is
        # here for, and a stripe across the card competes with it while
        # saying less than the counts did.
        chips = "".join(f'<span class="kchip">{html_lib.escape(k)} '
                        f'<b>{v}</b></span>'
                        for k, v in sorted(kinds.items(), key=lambda x: -x[1]))
        rules = ", ".join(path.get("rules_exercised") or [])
        ending = path.get("disposition") or "COMPLETE"
        # The name already carries the ending in brackets and the pill says
        # it too, so one of them has to go.
        name = re.sub(r"\s*\([A-Z_]+\)\s*$", "",
                      path.get("name", "")).strip()
        steps_n = len(path.get("sequence") or [])
        tone_end = ("ok" if ending == "COMPLETE"
                    else "warn" if "QUOTA" in ending else "bad")
        stops = journey_steps(path, QUESTIONS)
        st.markdown(
            f'<div class="route jcard"><div class="rhead">'
            f'<span class="rid">{pid}</span>'
            f'<span class="rname">{html_lib.escape(path.get("name",""))}</span>'
            f'<span class="pill {tone_end}">{html_lib.escape(ending)}</span>'
            f'<span class="rmeta">{len(path.get("sequence") or [])} questions '
            f'\u00b7 {len(tests_here)} checks</span></div>'
            f'<div class="track">{stops}</div>'
            f'<div class="jfoot"><div class="kchips">{chips}</div>'
            + (f'<div class="jrules">exercises {html_lib.escape(rules)}</div>'
               if rules else "")
            + "</div></div>", unsafe_allow_html=True)
        with st.expander(f"The {len(tests_here)} checks on {pid}"):
            st.caption(path.get("why_selected", ""))
            table([{"Test": t.get("test_case_id"),
                    "Question": t.get("question") or "\u2014",
                    "Kind": KINDS.get(t.get("dimension"), t.get("dimension")),
                    "What is checked": t.get("test_name")}
                   for t in sorted(tests_here,
                                   key=lambda x: x.get("order", 0))],
                  widths={"Test": "11%", "Question": "9%", "Kind": "17%"},
                  height="34vh")

    # ---- then the coverage reading ----
    vector = d.get("coverage_vector") or {}
    if vector:
        section("Nine kinds of behaviour, counted separately",
                "Never added together: adding them would let a survey with "
                "many answer rules hide untested branching. The shortest bar "
                "is the answer to the only question anyone asks of this.")
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

    shadowed = report.get("branch_states_shadowed") or []
    if shadowed:
        section("Findings for whoever wrote the questionnaire",
                "Rules that say the same thing twice, so one can never be "
                "observed on its own.")
        for item in shadowed:
            st.warning(f"**{item.get('question')}** \u2014 "
                       f"{item.get('finding', '')}")


def _saw(r: dict) -> str:
    """What the bot saw, in one line, whatever shape the record is in."""
    failed = " ".join(str(c.get("actually", "")) for c in (r.get("checks") or [])
                      if c.get("matched") is False)
    return failed or str(r.get("blocked_reason") or "") or "what was expected"


def page_run(s: dict) -> None:
    st.markdown("# The Respondent Bot")
    st.markdown('<p class="blurb">Each test is a fresh respondent. A test '
                'inheriting the last one\u2019s answers would prove nothing. '
                'The bot records what it saw; what a failure means is the '
                'quality report.</p>', unsafe_allow_html=True)

    if not s["has_lss"]:
        waiting("Nothing to run against",
                "The tests need a live survey. Build the file, import it into "
                "LimeSurvey and activate it. An inactive survey will not serve "
                "respondents, so the bot cannot reach it.",
                "Build the survey first")
        return
    if not (s["design_dir"] / "agent3_executable_tests.json").exists():
        waiting("No tests to run",
                "The designer has not produced a test package for this run.",
                "Design the tests on the Tests page")
        return

    left, middle, right = st.columns([2, 2, 3])
    st.session_state.setdefault("sid", "900001")
    st.session_state.setdefault("base", "http://localhost:8080")
    left.text_input("Survey id in LimeSurvey", key="sid",
                    help="The number in the participant link.")
    middle.text_input("LimeSurvey address", key="base")
    right.checkbox("Watch it in a browser", key="watch",
                   help="Slower, and worth it when showing someone. Watching "
                        "runs one test at a time.")
    st.session_state.setdefault("workers", 8)
    st.slider("Checks to run at once", 1, 24, key="workers",
              help="Most of a check is spent waiting for a page, so running "
                   "several at once is much faster. Each one is a browser, "
                   "so past about twice your processor cores the machine "
                   "becomes the limit rather than the waiting. Lower it if "
                   "checks start reporting that they could not run.",
              disabled=bool(st.session_state.get("watch")))
    # Not an on_click callback: a callback finishes before the page paints, so
    # nothing could be shown while the run happens.
    if st.button("Run the tests", type="primary", key="run_bot"):
        stream_bot(s)
        st.rerun()

    if st.session_state.get(f"bot_log::{s['name']}"):
        with st.expander("Run log",
                         expanded=not st.session_state.get(f"bot_ok::{s['name']}", True)):
            st.code(st.session_state[f"bot_log::{s['name']}"])

    results = s["results"]
    if not results:
        return

    counts = results.get("counts", {})
    could_not = counts.get("BLOCKED", 0) + counts.get("SKIPPED", 0)
    strip([("Tests run", sum(counts.values()), ""),
           ("Passed", counts.get("PASSED", 0), "ok"),
           ("Failed", counts.get("FAILED", 0),
            "bad" if counts.get("FAILED") else "idle"),
           ("Could not run", could_not, "warn" if could_not else "idle"),
           ("Last run", (results.get("run_at") or "")[:16].replace("T", " "),
            "sm")])
    st.caption("Could not run is kept apart from failed on purpose. A test "
               "that never finished its journey checked nothing, so it says "
               "nothing about the survey, and counting it as a failure would "
               "send someone looking for a defect that may not be there.")

    waiting("The results are on the Quality report",
            "What the bot saw only means something once it has been judged, "
            "so the outcome and the reasons sit together rather than in two "
            "places.",
            "Open the Quality report")


def results_by_question(s: dict, judgements: list | None = None) -> None:
    """Every check, grouped by the question it was about.

    A survey programmer fixes one question at a time, so a flat list of 184
    rows makes them find the question themselves.
    """
    rows = s["results"].get("results", [])
    if not rows:
        return
    choice = st.radio("Show", ["Everything", "Needs attention", "Passed only"],
                      horizontal=True, label_visibility="collapsed",
                      key="res_filter")
    keep = {"Needs attention": {"FAILED", "BLOCKED", "SKIPPED",
                                "INCONCLUSIVE"},
            "Passed only": {"PASSED"}}.get(choice)
    shown = [r for r in rows if not keep or r.get("status") in keep]
    st.caption(f"{len(shown)} of {len(rows)} shown")
    if not shown:
        waiting("Nothing matches", "No check in this run has that outcome.")
        return

    order: dict = {}
    for r in sorted(shown, key=lambda x: (x.get("order") or 9999)):
        order.setdefault(r.get("question") or "the whole survey", []).append(r)

    judged = {j.get("test_case_id"): j for j in (judgements or [])}
    for question, group in order.items():
        bad = [r for r in group if r.get("status") != "PASSED"]
        dots = "".join(
            f'<span class="dot {tone(r.get("status"))}" '
            f'title="{html_lib.escape(str(r.get("title") or ""))}"></span>'
            for r in group)
        st.markdown(
            f'<div class="qrun{" trouble" if bad else ""} head">'
            f'<div class="qrhead">'
            f'<span class="qid">{html_lib.escape(question)}</span>'
            f'<span class="dots">{dots}</span>'
            f'<span class="rmeta">{len(group) - len(bad)} of {len(group)} '
            f'passed</span></div></div>', unsafe_allow_html=True)

        # Each failure and its link sit together, in the card, without
        # opening anything. The link was inside the expander before, which
        # is the one place nobody looking at a failure would think to open.
        for r in bad:
            case = r.get("case_id") or r.get("test_id") or ""
            left, right = st.columns([5, 1])
            left.markdown(
                f'<div class="qrfail"><b>{html_lib.escape(str(case))}</b> '
                f'{html_lib.escape(str(r.get("title") or ""))}<br>'
                f'<span>{html_lib.escape(_saw(r))}</span></div>',
                unsafe_allow_html=True)
            if case in judged:
                if right.button("Why?", key=f"rca_{case}",
                                help=f"Open the reason for {case}"):
                    st.session_state["qc_view"] = "Failure RCA"
                    st.session_state["rca_focus"] = case
                    st.rerun()

        with st.expander(f"All {len(group)} checks on {question}"):
            table([{"Test": r.get("case_id") or r.get("test_id"),
                    "What was checked": r.get("title"),
                    "Outcome": r.get("status"),
                    "What the bot saw": _saw(r)}
                   for r in group],
                  widths={"Test": "11%", "Outcome": "11%",
                          "What was checked": "38%"},
                  pills=("Outcome",), height="30vh")


def rca_card(j: dict) -> None:
    """One failed check, and the four things an analyst needs to act on it.

    Four sections and no more. What the survey is configured to do belongs
    inside the section it explains, not beside them as a fifth thing to read.
    """
    shade = {"SURVEY_DEFECT": "bad", "SPECIFICATION_ERROR": "warn",
             "NOT_BUILT_YET": "warn", "UNSETTLED_QUESTION": "info",
             "TEST_MODEL_GAP": "info", "HARNESS_FAULT": ""}.get(
                 j.get("cause"), "")
    e = html_lib.escape
    label = (j.get("label")
             or str(j.get("cause", "")).replace("_", " ").title())
    st.markdown(
        f'<div class="rca {shade}"><div class="rhead">'
        f'<span class="rid">{e(str(j.get("test_case_id") or ""))}</span>'
        f'<span class="rname">{e(str(j.get("title") or ""))}</span>'
        f'<span class="pill {shade}">{e(str(label))}</span>'
        f'<span class="rmeta">{e(str(j.get("question") or ""))} \u00b7 '
        f'{e(str(j.get("path_id") or ""))}</span></div>'

        f'<div class="rcagrid">'
        f'<div><div class="rl">1 \u00b7 What went wrong</div><div class="rv">'
        + (f'<span class="tag grey">Bot did</span> '
           f'{e(str(j.get("bot_did")))}<br>' if j.get("bot_did") else "")
        + f'<span class="tag">Expected</span> '
          f'{e(str(j.get("expected_text") or ""))}<br>'
          f'<span class="tag bad">Observed</span> '
          f'{e(str(j.get("observed_text") or ""))}</div></div>'

        f'<div><div class="rl">2 \u00b7 Why it happened</div>'
        f'<div class="rv"><b>{e(str(j.get("component") or ""))}</b><br>'
        f'{e(str(j.get("component_why") or ""))}</div></div>'

        f'<div><div class="rl">3 \u00b7 What to change, and where</div>'
        f'<div class="rv"><b>{e(str(j.get("fix_where") or ""))}</b><br>'
        f'{e(str(j.get("fix_what") or ""))}</div></div>'

        f'<div><div class="rl">4 \u00b7 How to fix it</div>'
        f'<div class="rv">{e(str(j.get("fix_how") or ""))}'
        f'<div class="owner">{e(str(j.get("owner") or ""))}</div>'
        f'</div></div></div></div>', unsafe_allow_html=True)


def page_quality(s: dict) -> None:
    st.markdown("# What it all means")
    st.markdown('<p class="blurb">A failing test is not a defect. It may be '
                'the survey, a misreading of the questionnaire, something not '
                'built yet, or a gap in the tests themselves. Telling those '
                'apart needs the whole run, which is why it is a separate '
                'step.</p>', unsafe_allow_html=True)

    if not s["results"]:
        waiting("No run to judge yet",
                "The adjudicator reads a completed run and decides what each "
                "failure means and who should act on it.",
                "Run the tests first")
        return

    if st.button("Work out what it means", type="primary", key="run_qc"):
        run_adjudicator(s)
        st.rerun()

    if st.session_state.get(f"qc_log::{s['name']}") and not st.session_state.get(f"qc_ok::{s['name']}", True):
        st.error("The adjudicator reported a problem.")
        st.code(st.session_state[f"qc_log::{s['name']}"])

    if not s["findings"]:
        return

    good = [j for j in s["journeys"] if j.get("status") == "WORKING"]
    strip([("Journeys working", f"{len(good)} of {len(s['journeys'])}",
            "ok" if len(good) == len(s["journeys"]) else "warn"),
           ("A respondent would notice", len(s["broken"]),
            "bad" if s["broken"] else "ok"),
           ("Things to fix", len(s["groups"]), ""),
           ("Of those, real defects", len(s["real"]),
            "bad" if s["real"] else "ok")])

    # Not st.tabs, because a tab cannot be switched from code and the link
    # from a failed check has to land on one. Not a radio either: Streamlit
    # refuses to let anything write to a widget's own key once the widget
    # exists, which is what broke the link. Two buttons have neither
    # problem, and the state is ours.
    st.session_state.setdefault("qc_view", "Report")
    tab_a, tab_b, _ = st.columns([1, 1, 5])
    if tab_a.button("Report", use_container_width=True,
                    type="primary" if st.session_state["qc_view"] == "Report"
                    else "secondary", key="qc_tab_report"):
        st.session_state["qc_view"] = "Report"
        st.session_state.pop("rca_focus", None)
        st.rerun()
    if tab_b.button("Failure RCA", use_container_width=True,
                    type="primary"
                    if st.session_state["qc_view"] == "Failure RCA"
                    else "secondary", key="qc_tab_rca"):
        st.session_state["qc_view"] = "Failure RCA"
        st.rerun()
    view = st.session_state["qc_view"]

    if view == "Report":
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
            'where the journey ends</span></div>', unsafe_allow_html=True)
        for card in journey_cards(s):
            st.markdown(card, unsafe_allow_html=True)

        section("Every check, question by question",
                "The detail behind the journeys above. A question with a red "
                "edge has something that did not pass.")
        results_by_question(s, s["findings"].get("judgements", []))

    else:
        if not s["groups"]:
            st.success("Nothing to correct. Every check passed.")
        else:
            bad_checks = [j for j in s["findings"].get("judgements", [])]
            section("Every check that did not pass",
                    f"{len(bad_checks)} of them, in questionnaire order. Each "
                    f"says what was expected, what the bot saw, which part of "
                    f"the platform caused it, and how to put it right.")
            SHADE = {"SURVEY_DEFECT": "#F8E4E6",
                     "SPECIFICATION_ERROR": "#FAEBDE",
                     "NOT_BUILT_YET": "#FAEBDE",
                     "UNSETTLED_QUESTION": "#E9E6F9",
                     "TEST_MODEL_GAP": "#E9E6F9"}
            counts: dict = {}
            for j in bad_checks:
                # Counted by the words on the card, not by the code behind
                # them, so the legend and the cards can never disagree.
                key = (j.get("label")
                       or str(j.get("cause", "")).replace("_", " ").lower(),
                       j.get("cause", ""))
                counts[key] = counts.get(key, 0) + 1
            st.markdown(
                '<div class="legend">' + "".join(
                    f'<span><span class="swatch" style="background:'
                    f'{SHADE.get(cause, "#F1EFF8")}"></span>'
                    f'{html_lib.escape(str(words).lower())} {n}</span>'
                    for (words, cause), n in sorted(counts.items(),
                                                    key=lambda x: -x[1]))
                + "</div>", unsafe_allow_html=True)
            focus = st.session_state.get("rca_focus")
            if focus:
                picked = [j for j in bad_checks
                          if j.get("test_case_id") == focus
                          or j.get("question") == focus]
                if picked:
                    st.caption(f"Showing {focus}.")
                    if st.button("Show every check", key="rca_all"):
                        st.session_state.pop("rca_focus", None)
                        st.rerun()
                    bad_checks = picked
            for j in sorted(bad_checks,
                            key=lambda x: (x.get("order") or 999,
                                           x.get("test_case_id") or "")):
                rca_card(j)

    book = s["qc_dir"] / "agent5_qc_report.xlsx"
    if book.exists():
        st.download_button("Download the QC report", data=book.read_bytes(),
                           file_name=f"{s['name']}_qc_report.xlsx",
                           mime=("application/vnd.openxmlformats-officedocument"
                                 ".spreadsheetml.sheet"), type="primary")


def page_files(s: dict) -> None:
    directory = s["directory"]
    total = sum(1 for x in directory.rglob("*") if x.is_file())
    st.markdown("# Everything this run produced")
    st.markdown(
        f'<p class="blurb">{total} files. The audit trail exists so that when '
        f'a test fails you can tell whether the survey is wrong, the answers '
        f'chosen were wrong, or the prediction was wrong.</p>',
        unsafe_allow_html=True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory))
    st.download_button("Download everything as a zip", data=buffer.getvalue(),
                       file_name=f"{s['name']}_artifacts.zip",
                       mime="application/zip", type="primary")
    st.caption(str(directory))

    headline = [
        ("Quality report", s["qc_dir"], "Causes, owners and what to fix"),
        ("Test run", s["bot_dir"], "What the bot did and saw, step by step"),
        ("Tests", s["design_dir"], "Journeys, test cases, and coverage"),
    ]
    for label, folder, what in headline:
        if folder.exists():
            files = sorted(p for p in folder.iterdir() if p.is_file())
            with st.expander(f"{label} \u2014 {what}  ({len(files)})"):
                file_rows(files)

    top_level = [p for p in directory.iterdir() if p.is_file()]
    shown: set = set()
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


# --- running the agents ----------------------------------------------------


def _run(command, spinner: str):
    with st.spinner(spinner):
        return subprocess.run(command, capture_output=True, text=True)


def run_interpreter(source: Path) -> None:
    result = _run([sys.executable, "-m",
                   "src.agents.qre_interpretation.orchestrator", str(source)],
                  "Reading the questionnaire. This takes a few minutes.")
    st.session_state["log"] = result.stdout + result.stderr
    st.session_state["run_failed"] = result.returncode != 0
    st.session_state["run_name"] = source.stem
    st.session_state["page"] = "overview"


def build_survey(s: dict) -> None:
    result = _run([sys.executable, "-m", "src.agents.survey_builder.build",
                   str(s["directory"])], "Building the survey file.")
    # Keyed by survey. A single shared key meant opening one survey showed
    # the log from whichever was built last, which reads as a failure that
    # never happened.
    st.session_state[f"build_log::{s['name']}"] = result.stdout + result.stderr
    st.session_state[f"build_ok::{s['name']}"] = result.returncode == 0


def design_tests(s: dict) -> None:
    command = [sys.executable, "-m", "src.agents.test_design.run",
               str(s["directory"])]
    if s["has_lss"]:
        command += ["--lss", str(s["lss"])]
    inputs = DESIGN_INPUTS / f"{s['name']}.json"
    if inputs.exists():
        command += ["--inputs", str(inputs)]
    result = _run(command, "Designing the tests.")
    st.session_state[f"design_log::{s['name']}"] = result.stdout + result.stderr
    st.session_state[f"design_ok::{s['name']}"] = result.returncode == 0


def run_adjudicator(s: dict) -> None:
    result = _run([sys.executable, "-m",
                   "src.agents.qa_adjudication.adjudicate",
                   str(s["directory"])], "Working out what the results mean.")
    st.session_state[f"qc_log::{s['name']}"] = result.stdout + result.stderr
    st.session_state[f"qc_ok::{s['name']}"] = result.returncode == 0


def stream_bot(s: dict) -> None:
    """Agent 4, with the run shown as it happens.

    subprocess.run hands everything back at the end, which for a two-minute
    run means two minutes of nothing. Reading line by line lets the page say
    which test is running and how it went, which is the difference between a
    tool that looks stuck and one that looks busy.
    """
    command = [sys.executable, "-u", "-m",
               "src.agents.respondent_bot.run_browser", str(s["directory"]),
               "--sid", st.session_state.get("sid", "900001"),
               "--base", st.session_state.get("base", "http://localhost:8080")]
    if st.session_state.get("watch"):
        command += ["--headed", "--slow", "150"]
    else:
        command += ["--workers", str(st.session_state.get("workers", 8))]

    ticker, live = st.empty(), st.empty()
    lines: list = []
    done = 0
    counts = {"PASSED": 0, "FAILED": 0, "BLOCKED": 0, "SKIPPED": 0}
    package = read_json(s["design_dir"], "agent3_executable_tests.json", {}) or {}
    total = sum(1 for t in package.get("tests", []) if t.get("executable"))

    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in process.stdout:
        text = line.rstrip()
        lines.append(text)
        bare = text.strip()
        # Two shapes of line reach us. Running one check at a time, the
        # outcome sits on its own line. Running several at once, the parent
        # prefixes it with a counter. Both have to move the same figures, or
        # the bar sits at zero while the run works perfectly.
        outcome = bare
        if bare.startswith("["):
            _, _, rest = bare.partition("]")
            outcome = rest.strip()
        counted = False
        for word in counts:
            if outcome.startswith(word):
                counts[word] += 1
                done += 1
                counted = True
                break
        if not counted and bare.startswith("##DONE "):
            status = bare[7:].split(" ", 1)[0]
            if status in counts:
                counts[status] += 1
                done += 1
        if bare.startswith("[") or any(bare.startswith(w) for w in counts):
            pct = (done / total * 100) if total else 0
            current = next((l.strip() for l in reversed(lines)
                            if l.strip().startswith("[")), bare)
            left = int((total - done) * 1.9) if total else 0
            ticker.markdown(
                f'<div class="runbar"><div class="rprog">'
                f'<div class="rfill" style="width:{pct:.0f}%"></div></div>'
                f'<div class="rnums">'
                f'<span class="ok">{counts["PASSED"]} passed</span>'
                f'<span class="bad">{counts["FAILED"]} failed</span>'
                f'<span class="warn">{counts["BLOCKED"]} could not run</span>'
                f'<span class="grey">{done} of {total or "?"}'
                + (f" \u00b7 about {left} seconds left" if left > 0 else "")
                + f'</span></div>'
                f'<div class="rnow">{html_lib.escape(current[:110])}</div>'
                f'</div>', unsafe_allow_html=True)
        live.code("\n".join(lines[-12:]))

    process.wait()
    ticker.empty()
    live.empty()
    st.session_state[f"bot_log::{s['name']}"] = "\n".join(lines)
    st.session_state[f"bot_ok::{s['name']}"] = process.returncode == 0




QUESTIONS: list = []
ROUTING: list = []
SURVEY: dict = {}


def load_context(state) -> None:
    """Point the views at a particular run.

    Must be called before drawing any page, and again whenever the open run
    changes. The original set these at the top of the script, which works
    for one page per load and not for an app that can switch run without a
    reload.
    """
    global QUESTIONS, ROUTING, SURVEY
    if not state:
        QUESTIONS, ROUTING, SURVEY = [], [], {}
        return
    QUESTIONS = read_json(state["directory"], "stage4_questionnaire.json", [])
    ROUTING = read_json(state["directory"], "stage4_routing.json", [])
    SURVEY = read_json(state["directory"], "stage4_survey.json", {})