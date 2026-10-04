"""The team platform.

Everything the single-user app draws is drawn here too, by the same code:
views.py is that app's rendering, lifted out so both can use it. What this
app adds is the part that has no file behind it — who is looking, what they
may do, who owns each finding and what has happened to it.

    python -m streamlit run src/dashboard/app_team.py --server.port 8502

Both apps read the same out/ folder. Only this one writes to the database,
and it never writes anything an agent produces.
"""
from __future__ import annotations

import html as html_lib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Survey QA", page_icon="\u2713",
                   layout="wide", initial_sidebar_state="collapsed")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src" / "qa_platform"))
sys.path.insert(0, str(HERE))

import store      # noqa: E402
import views      # noqa: E402

OUT = views.OUT
DB = ROOT / "data" / "platform.db"


# ------------------------------------------------------------------ pieces
def esc(x) -> str:
    return html_lib.escape("" if x is None else str(x))


def ago(stamp) -> str:
    if not stamp:
        return "never"
    try:
        then = datetime.fromisoformat(str(stamp))
    except ValueError:
        return str(stamp)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - then).total_seconds()
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 172800:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"


def me() -> dict:
    return st.session_state["me"]


def can(permission: str) -> bool:
    return permission in st.session_state.get("rights", set())


def who(email) -> str:
    if not email:
        return "nobody"
    found = next((p for p in store.people(DB) if p["email"] == email), None)
    return found["name"] if found else email


def toast(message: str) -> None:
    st.session_state["toast"] = message


def strip(cells) -> None:
    st.markdown('<div class="strip">' + "".join(
        f'<div class="cell"><div class="k">{esc(k)}</div>'
        f'<div class="v {t}">{esc(v)}</div></div>' for k, v, t in cells)
        + "</div>", unsafe_allow_html=True)


def section(title, blurb="") -> None:
    st.markdown(f'<div class="sect"><h2>{esc(title)}</h2>'
                + (f"<p>{esc(blurb)}</p>" if blurb else "") + "</div>",
                unsafe_allow_html=True)


def tone_of(f) -> str:
    return {"SURVEY_DEFECT": "bad", "SPECIFICATION_ERROR": "warn",
            "NOT_BUILT_YET": "warn", "UNSETTLED_QUESTION": "info",
            "TEST_MODEL_GAP": "info"}.get(f["cause"], "")


# ------------------------------------------------------------------- login
def login_page() -> None:
    _, middle, _ = st.columns([1, 1.6, 1])
    with middle:
        st.markdown(
            '<div class="lbrand"><div class="logo">SP</div><div>'
            '<div class="bn">Survey QA</div><div class="bs">Escalent '
            '&middot; survey programming and quality</div></div></div>',
            unsafe_allow_html=True)
        st.markdown('<p class="blurb">Sign in with your work account. What '
                    'you can see and do follows from the role your '
                    'administrator gave you.</p>', unsafe_allow_html=True)
        email = st.text_input("Email", placeholder="you@escalent.co")
        password = st.text_input("Password", type="password")
        if st.button("Sign in", type="primary", use_container_width=True):
            found, problem = store.authenticate(email, password, DB)
            if problem:
                st.error(problem)
            else:
                st.session_state["me"] = found
                st.session_state["rights"] = store.permissions_of(
                    found["role"], DB)
                st.session_state["page"] = pages_for(found["role"])[0]
                st.rerun()
        with st.expander("Accounts in this database"):
            for p in store.people(DB):
                mark = "" if p["active"] else "   (suspended)"
                st.caption(f"{p['email']} \u2014 {p['role']}{mark}")
            st.caption("The starting password for everyone is: escalent")


# --------------------------------------------------------------- the shell
NAV = {"today": "Today", "corpus": "The corpus", "findings": "Findings",
       "platform": "Platform health", "rules": "House rules",
       "admin": "Users and roles"}


def pages_for(role: str) -> list[str]:
    rights = store.permissions_of(role, DB)
    pages = ["today", "corpus", "findings"]
    if "judge" in rights or "admin" in rights:
        pages.append("platform")
    if "rules" in rights:
        pages.append("rules")
    if "admin" in rights:
        pages.append("admin")
    return pages


def top_bar() -> None:
    allowed = pages_for(me()["role"])
    if st.session_state.get("page") not in allowed:
        st.session_state["page"] = allowed[0]

    # The dark strip is drawn, and the buttons sit in normal flow below it.
    # An earlier version fixed the whole row to the top of the window,
    # which took it out of the flow and let Streamlit's overlay cover it,
    # so none of the nav responded to a click.
    st.markdown(
        '<div class="appbar"><span class="mark">Escalent'
        '<i>&middot; Survey QA</i></span>'
        f'<span class="meline">{esc(me()["name"])} &middot; '
        f'{esc(me()["role"])}</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="navwrap">', unsafe_allow_html=True)
    bar = st.columns([0.8] * len(allowed) + [3, 0.9])
    for i, key in enumerate(allowed):
        on = st.session_state["page"] == key
        if bar[i].button(NAV[key], key=f"nav_{key}",
                         use_container_width=True,
                         type="primary" if on else "secondary"):
            open_page(key)
    if bar[-1].button("Sign out", key="nav_out",
                      use_container_width=True):
        for key in ("me", "rights", "page", "open_survey", "open_finding",
                    "backfilled"):
            st.session_state.pop(key, None)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def open_page(key) -> None:
    st.session_state["page"] = key
    st.session_state.pop("open_survey", None)
    st.session_state.pop("open_finding", None)
    st.rerun()


def open_survey(name) -> None:
    st.session_state["open_survey"] = name
    st.session_state.pop("open_finding", None)
    st.rerun()


def open_finding(ref) -> None:
    st.session_state["open_finding"] = ref
    st.session_state["page"] = "findings"
    st.session_state.pop("open_survey", None)
    st.rerun()


# ------------------------------------------------------- keeping in step
def backfill() -> None:
    """Fold whatever is already on disk into the database.

    A stage run from the command line writes its files and knows nothing
    about this platform. Without this, somebody who has used the pipeline
    for weeks signs in to an empty board, which reads as the platform being
    broken rather than merely uninformed.
    """
    if st.session_state.get("backfilled"):
        return
    st.session_state["backfilled"] = True

    for d in sorted(p for p in OUT.iterdir() if p.is_dir()):
        store.upsert_questionnaire(d.name, code=d.name[:3], title=d.name,
                                   path=DB)

        findings_file = d / "agent5" / "agent5_findings.json"
        if findings_file.exists() and not store.findings(d.name, path=DB):
            try:
                doc = json.loads(findings_file.read_text(encoding="utf-8"))
            except Exception:
                doc = {}
            results = (views.read_json(d / "agent4", "agent4_results.json",
                                       {}) or {}).get("results", [])
            store.sync_findings(d.name, doc.get("groups", []), results, DB)

        # Any run folder not already recorded, rather than only when none
        # are recorded. A single stray row used to block all of them, and a
        # run started from the command line after signing in would never
        # have appeared.
        known = {r["folder"] for r in store.runs_of(d.name, 999, DB)}
        for folder in sorted((d / "agent4" / "runs").glob("*")):
            results_file = folder / "agent4_results.json"
            if not results_file.exists() or str(folder) in known:
                continue
            try:
                rows = json.loads(
                    results_file.read_text(encoding="utf-8")
                ).get("results", [])
            except Exception:
                continue
            rid = store.start_run(d.name, folder, None, DB)
            store.finish_run(
                rid, len(rows),
                sum(1 for x in rows if x.get("status") == "PASSED"),
                sum(1 for x in rows if x.get("status") == "FAILED"),
                sum(1 for x in rows
                    if x.get("status") not in ("PASSED", "FAILED")), DB)


def record_run(name: str) -> None:
    """Note that the bot has run, and fold in what the judge made of it."""
    state = views.survey_state(name)
    results = ((state or {}).get("results") or {}).get("results", [])
    folder = next(reversed(sorted(
        (OUT / name / "agent4" / "runs").glob("*"))), None)
    rid = store.start_run(name, folder or (OUT / name / "agent4"),
                          me()["email"], DB)
    store.finish_run(
        rid, len(results),
        sum(1 for r in results if r.get("status") == "PASSED"),
        sum(1 for r in results if r.get("status") == "FAILED"),
        sum(1 for r in results
            if r.get("status") not in ("PASSED", "FAILED")), DB)


def record_judgement(name: str) -> None:
    state = views.survey_state(name)
    groups = ((state or {}).get("findings") or {}).get("groups", [])
    results = ((state or {}).get("results") or {}).get("results", [])
    out = store.sync_findings(name, groups, results, DB)
    if out.get("held_open"):
        st.warning("Nothing was closed: " + out["held_open"])
    said = []
    for label, key in (("raised", "opened"), ("reopened", "reopened"),
                       ("closed by the run", "closed")):
        if out.get(key):
            said.append(f"{len(out[key])} {label}")
    toast(", ".join(said) or "No change to the findings.")


# ---------------------------------------------------------------- pages
def page_today() -> None:
    mine = [f for f in store.findings(owner=me()["email"], path=DB)
            if f["state"] != "Closed"]
    everything = store.findings(path=DB)
    blocking = [f for f in everything if f["blocks"] and f["state"] != "Closed"]
    unowned = [f for f in everything if not f["owner"] and f["state"] != "Closed"]

    st.markdown(f"# Good morning, {esc(me()['name'].split()[0])}")
    st.markdown('<p class="blurb">What is waiting on you, and what is '
                'waiting on nobody.</p>', unsafe_allow_html=True)
    strip([("Assigned to you", len(mine), "bad" if mine else "ok"),
           ("Blocking a questionnaire", len(blocking),
            "bad" if blocking else "ok"),
           ("Nobody has picked up", len(unowned), "warn" if unowned else "ok"),
           ("Questionnaires", len(store.questionnaires(DB)), ""),
           ("Open in total",
            sum(1 for f in everything if f["state"] != "Closed"), "")])

    section("Needs you")
    if mine:
        for f in mine:
            finding_row(f)
    else:
        views.waiting("Nothing is assigned to you",
                      "Everything raised so far belongs to someone else, or "
                      "to nobody.")
    if unowned:
        section("Nobody has picked these up",
                "A finding with no owner is the one most likely to be "
                "forgotten, so it is listed on its own rather than mixed in.")
        for f in unowned:
            finding_row(f)


def finding_row(f) -> None:
    left, right = st.columns([8, 1])
    left.markdown(
        f'<div class="work {"urgent" if f["blocks"] else ""}">'
        f'<div class="wtop"><span class="wid">{esc(f["ref"])}</span>'
        f'<span class="wtitle">{esc(f["headline"])}</span></div>'
        f'<div class="wmeta"><span class="wclient">'
        f'{esc((f["run_name"] or "")[:3])} {esc(f["question"])}</span>'
        f'<span>&middot;</span>'
        f'<span class="pill {tone_of(f)}">{esc(f["label"])}</span>'
        f'<span>&middot;</span><span>{esc(f["state"])}</span>'
        f'<span>&middot;</span><span>{esc(who(f["owner"]))}</span>'
        f'<span>&middot;</span><span>raised {ago(f["first_seen"])}</span>'
        + ('<span class="flag">blocks this questionnaire</span>'
           if f["blocks"] else "") + "</div></div>",
        unsafe_allow_html=True)
    if right.button("Open", key=f"o_{f['ref']}", use_container_width=True):
        open_finding(f["ref"])


def page_corpus() -> None:
    st.markdown("# The corpus")
    st.markdown('<p class="blurb">Every questionnaire the platform knows '
                'about. Add one and it is read, built, checked and judged '
                'from here.</p>', unsafe_allow_html=True)

    if can("run"):
        with st.expander("Add a questionnaire", expanded=False):
            # The upload and the interpreter run are the single-user app's
            # own, so a new questionnaire arrives exactly as it always did.
            views.upload_panel()

    rows = []
    for d in sorted(p for p in OUT.iterdir() if p.is_dir()):
        state = views.survey_state(d.name)
        if state:
            rows.append(state)
    if not rows:
        views.waiting("Nothing here yet",
                      "Add a questionnaire above and the platform reads it, "
                      "builds the survey, writes the checks and runs them.")
        return

    strip([("Questionnaires", len(rows), ""),
           ("Run end to end", sum(1 for s in rows if s["stage"] >= 5), ""),
           ("Checks written",
            sum((s["summary"] or {}).get("logical_tests", 0) for s in rows), ""),
           ("Open findings", sum(1 for f in store.findings(path=DB)
                                 if f["state"] != "Closed"), "bad")])

    for s in rows:
        open_here = [f for f in store.findings(s["name"], path=DB)
                     if f["state"] != "Closed"]
        # The single-user app already works out a label and a colour for
        # each stage. Reusing them keeps the two apps saying the same thing
        # about the same run.
        words, tone = s["label"], s["shade"]
        if any(f["blocks"] for f in open_here):
            words, tone = "Needs fixing", "bad"
        elif open_here and s["stage"] >= 5:
            words, tone = f"{len(open_here)} open", "warn"
        row = st.columns([3, 1.3, 3.2, 1.4, 0.8])
        row[0].markdown(f'<div class="wvname">{esc(s["name"])}</div>',
                        unsafe_allow_html=True)
        row[1].markdown(f'<span class="pill {tone}">{esc(words)}</span>',
                        unsafe_allow_html=True)
        row[2].markdown(stage_bar(s["stage"]), unsafe_allow_html=True)
        counts = (s["results"] or {}).get("counts", {})
        total = sum(counts.values())
        row[3].markdown(
            '<div class="wvmeta">'
            + (f'{counts.get("PASSED", 0)} of {total} passing' if total
               else "no checks yet") + "</div>", unsafe_allow_html=True)
        if row[4].button("Open", key=f"c_{s['name']}",
                         use_container_width=True):
            open_survey(s["name"])


# --------------------------------------------------------------- a survey
SURVEY_TABS = [
    ("overview",      "Overview",       None),
    ("questionnaire", "Questionnaire",  views.page_questionnaire),
    ("survey",        "Survey",         views.page_survey),
    ("tests",         "Checks",         views.page_tests),
    ("run",           "Respondent Bot", views.page_run),
    ("quality",       "QC report",      views.page_quality),
    ("history",       "Run history",    None),
    ("files",         "Files",          views.page_files),
]


def page_survey() -> None:
    name = st.session_state["open_survey"]
    state = views.survey_state(name)
    if state is None:
        st.session_state.pop("open_survey", None)
        st.rerun()
    views.load_context(state)

    back, _, danger = st.columns([1.3, 6, 1.3])
    if back.button("\u2190  The corpus", key="back_corpus",
                   use_container_width=True):
        open_page("corpus")
    if can("run") and danger.button("Delete this run", key="del_run",
                                    use_container_width=True):
        st.session_state["confirm_delete"] = name
        st.rerun()

    if st.session_state.get("confirm_delete") == name:
        st.warning(f"Delete everything under out/{name}? The questionnaire "
                   f"document is kept; every stage after it is thrown away "
                   f"and would have to run again.")
        yes, no, _ = st.columns([1.2, 1.2, 6])
        if yes.button("Delete it", key="del_yes", type="primary"):
            delete_run(name)
            st.session_state.pop("confirm_delete", None)
            open_page("corpus")
        if no.button("Keep it", key="del_no"):
            st.session_state.pop("confirm_delete", None)
            st.rerun()

    st.markdown(f"# {esc(name)}")
    open_here = [f for f in store.findings(name, path=DB)
                 if f["state"] != "Closed"]
    counts = (state["results"] or {}).get("counts", {})
    total = sum(counts.values())
    strip([("State", state["label"], state["shade"]),
           ("Checks", (state["summary"] or {}).get("logical_tests")
            or "\u2014", ""),
           ("Passing", f'{counts.get("PASSED", 0)} of {total}' if total
            else "\u2014", ""),
           ("Open findings", len(open_here), "bad" if open_here else "ok"),
           ("Runs", len(store.runs_of(name, 99, DB)), ""),
           ("Last run", state["when"], "sm")])

    labels = [label for _, label, _ in SURVEY_TABS]
    tabs = st.tabs(labels)
    for tab, (key, _, view) in zip(tabs, SURVEY_TABS):
        with tab:
            if key == "overview":
                survey_overview(state, name)
            elif key == "history":
                survey_history(name)
            elif key == "quality":
                view(state)
                survey_findings(name)
            else:
                view(state)


def delete_run(name: str) -> None:
    """Throw away everything the pipeline produced for a questionnaire.

    The uploaded document is left alone, so the run can start again without
    anyone hunting for the Word file. The findings go with it, because a
    finding about a run that no longer exists is noise.
    """
    import shutil
    shutil.rmtree(OUT / name, ignore_errors=True)
    for stray in OUT.glob(f"{name}_generated.lss"):
        stray.unlink(missing_ok=True)
    with store.connect(DB) as conn:
        conn.execute("DELETE FROM finding_event WHERE finding_key IN "
                     "(SELECT key FROM finding WHERE run_name=?)", (name,))
        conn.execute("DELETE FROM finding WHERE run_name=?", (name,))
        conn.execute("DELETE FROM run WHERE run_name=?", (name,))
        conn.execute("DELETE FROM questionnaire WHERE run_name=?", (name,))
    toast(f"{name} deleted. The questionnaire document is still in uploads.")


def stage_bar(stage: int) -> str:
    names = ["Extraction", "Survey Build", "Test Cases", "Bot Run",
             "QC Report"]
    return ('<div class="spills">' + "".join(
        f'<div class="spill {"done" if i < stage else ("now" if i == stage else "")}">'
        f'<span class="sbar"></span><span class="slab">{n}</span></div>'
        for i, n in enumerate(names)) + "</div>")


def survey_overview(state, name) -> None:
    """Where this questionnaire has got to, and the one thing to do next.

    The stage itself is run from its own tab. This page names the next
    thing and takes you there, so there is one place for each action and
    the overview says which.
    """
    st.markdown(stage_bar(state["stage"]), unsafe_allow_html=True)
    next_step = {1: ("survey", "Build the survey"),
                 2: ("tests", "Design the checks"),
                 3: ("run", "Run the Respondent Bot"),
                 4: ("quality", "Work out what it means")}.get(state["stage"])
    if next_step:
        where, label = next_step
        st.markdown(
            f'<div class="nextstep"><div class="nl">Next step</div>'
            f'<div class="nt">{esc(label)}</div>'
            f'<div class="nw">Open the {esc(where)} tab above. Each stage '
            f'has its own tab and the button to run it lives there.</div>'
            f"</div>", unsafe_allow_html=True)
    else:
        st.success("Every stage has run. The QC report has the verdict.")

    diff = store.compare_runs(name, DB)
    if diff.get("have") and diff["broke"]:
        st.warning(
            f"{len(diff['broke'])} check(s) that passed last time are "
            f"failing now: {', '.join(diff['broke'][:6])}. Worth looking at "
            f"before anything else.")


def survey_history(name) -> None:
    runs = store.runs_of(name, 30, DB)
    if not runs:
        views.waiting("No runs recorded yet",
                      "A run is recorded when the bot finishes. Runs already "
                      "on disk were folded in when you signed in.")
        return

    diff = store.compare_runs(name, DB)
    if diff.get("have"):
        section("What changed in the last run",
                "The question after every fix is whether it worked and "
                "whether it broke something else.")
        a, b, c = st.columns(3)
        a.markdown(
            f'<div class="dcell good"><div class="dn">+{len(diff["fixed"])}'
            f'</div><div class="dl">now passing</div><div class="dd">'
            f'{esc(", ".join(diff["fixed"][:5])) or "nothing was fixed"}'
            f"</div></div>", unsafe_allow_html=True)
        b.markdown(
            f'<div class="dcell {"worse" if diff["broke"] else ""}">'
            f'<div class="dn">{len(diff["broke"])}</div>'
            f'<div class="dl">newly failing</div><div class="dd">'
            f'{esc(", ".join(diff["broke"][:5])) or "nothing broke"}'
            f"</div></div>", unsafe_allow_html=True)
        c.markdown(
            f'<div class="dcell"><div class="dn">{len(diff["still"])}</div>'
            f'<div class="dl">still failing</div>'
            f'<div class="dd">unchanged</div></div>', unsafe_allow_html=True)
    else:
        st.info("Two runs are needed before anything can be compared. This "
                "questionnaire has one.")

    section("Every run")
    st.dataframe(
        [{"Run": f"#{len(runs) - i}", "When": ago(r["started"]),
          "By": who(r["by_email"]) if r["by_email"] else "before sign-in",
          "Checks": r["checks"], "Passed": r["passed"],
          "Failed": r["failed"], "Could not run": r["blocked"]}
         for i, r in enumerate(runs)],
        use_container_width=True, hide_index=True)


def survey_findings(name) -> None:
    """The findings for this questionnaire, with their owners and states.

    Sits under the QC report, which shows what the run found. This shows
    what has been decided about it since.
    """
    open_here = [f for f in store.findings(name, path=DB)
                 if f["state"] != "Closed"]
    section("Who is fixing what",
            "The report above is what this run found. This is what has "
            "happened to it since, and it survives the next run.")
    if not open_here:
        st.success("Nothing outstanding on this questionnaire.")
        return
    for f in open_here:
        finding_row(f)


# --------------------------------------------------------------- findings
def page_findings() -> None:
    if st.session_state.get("open_finding"):
        finding_detail(st.session_state["open_finding"])
        return

    everything = store.findings(path=DB)
    st.markdown("# Findings")
    st.markdown('<p class="blurb">Everything the platform has raised, with '
                'an owner and a state. A finding that is reported and then '
                'forgotten is the same as one never found.</p>',
                unsafe_allow_html=True)
    strip([("Open", sum(1 for f in everything if f["state"] == "Open"), "bad"),
           ("Blocking", sum(1 for f in everything
                            if f["blocks"] and f["state"] != "Closed"), "bad"),
           ("Assigned to you",
            sum(1 for f in everything if f["owner"] == me()["email"]
                and f["state"] != "Closed"), ""),
           ("Nobody owns",
            sum(1 for f in everything if not f["owner"]
                and f["state"] != "Closed"), "warn"),
           ("Closed", sum(1 for f in everything
                          if f["state"] == "Closed"), "ok")])

    pick = st.radio("Show", ["Everything", "Assigned to me", "Nobody owns",
                             "Blocking", "Closed"], horizontal=True,
                    label_visibility="collapsed")
    shown = {
        "Everything": [f for f in everything if f["state"] != "Closed"],
        "Assigned to me": [f for f in everything
                           if f["owner"] == me()["email"]
                           and f["state"] != "Closed"],
        "Nobody owns": [f for f in everything if not f["owner"]
                        and f["state"] != "Closed"],
        "Blocking": [f for f in everything
                     if f["blocks"] and f["state"] != "Closed"],
        "Closed": [f for f in everything if f["state"] == "Closed"],
    }[pick]
    if not shown:
        views.waiting("Nothing here", "No finding matches that filter.")
        return

    columns = st.columns(len(store.STATES))
    for column, state_name in zip(columns, store.STATES):
        here = [f for f in shown if f["state"] == state_name]
        column.markdown(f'<div class="fhead">{esc(state_name)}'
                        f'<span class="fcount">{len(here)}</span></div>',
                        unsafe_allow_html=True)
        for f in here:
            column.markdown(
                f'<div class="fcard"><div class="ftop">'
                f'<span class="fid">{esc(f["ref"])}</span>'
                f'<span class="pill {tone_of(f)}">{esc(f["label"])}</span>'
                f'</div><div class="fwhat">{esc(f["headline"][:110])}</div>'
                f'<div class="fmeta">{esc((f["run_name"] or "")[:3])} '
                f'{esc(f["question"])}</div>'
                f'<div class="ffoot">{esc(who(f["owner"]))}'
                f'<span class="fage">{ago(f["first_seen"])}</span></div>'
                f"</div>", unsafe_allow_html=True)
            if column.button("Open", key=f"b_{f['ref']}",
                             use_container_width=True):
                open_finding(f["ref"])


def finding_detail(ref) -> None:
    f = store.finding_by_ref(ref, DB)
    if f is None:
        st.session_state.pop("open_finding", None)
        st.rerun()
    g = f["payload"] or {}

    back, _, to_survey = st.columns([1.2, 6, 1.6])
    if back.button("\u2190  Findings", key="back_findings",
                   use_container_width=True):
        st.session_state.pop("open_finding", None)
        st.rerun()
    if to_survey.button(f"Open {f['run_name'][:3]} \u2192",
                        key=f"tosurvey_{ref}", use_container_width=True):
        open_survey(f["run_name"])

    st.markdown(f"# {esc(f['ref'])}")
    st.markdown(f'<p class="blurb">{esc(f["headline"])}</p>',
                unsafe_allow_html=True)
    strip([("Questionnaire", (f["run_name"] or "")[:3], ""),
           ("Question", f["question"] or "\u2014", ""),
           ("State", f["state"], "bad" if f["state"] == "Open" else ""),
           ("Owner", who(f["owner"]), ""),
           ("First seen", ago(f["first_seen"]), "sm"),
           ("Last seen", ago(f["last_seen"]), "sm")])

    moves = (store.STATES if can("triage")
             else ["In progress", "Fixed, awaiting re-run"]
             if can("markfixed") else [])
    moves = [m for m in moves if m != f["state"]]
    if moves:
        row = st.columns([0.9] + [1] * len(moves))
        row[0].markdown('<div class="alab">Move to</div>',
                        unsafe_allow_html=True)
        for i, m in enumerate(moves, start=1):
            if row[i].button(m, key=f"mv_{ref}_{m}",
                             use_container_width=True):
                store.move_finding(f["key"], m, me()["email"], DB)
                toast(f"{ref} moved to {m}")
                st.rerun()
    if can("assign"):
        left, right = st.columns([2, 6])
        names = {p["name"]: p["email"] for p in store.people(DB)
                 if p["active"]}
        choice = left.selectbox("Assign to", ["\u2014"] + list(names),
                                key=f"as_{ref}")
        if choice != "\u2014" and names[choice] != f["owner"]:
            store.assign_finding(f["key"], names[choice], me()["email"], DB)
            toast(f"{ref} assigned to {choice}")
            st.rerun()
    if not moves and not can("assign"):
        st.caption("Your role can comment on a finding but not change its "
                   "state or its owner.")

    section("What the platform said")
    left, right = st.columns(2)
    left.markdown(
        f'<div class="rl">1 &middot; What went wrong</div>'
        f'<div class="rv">{esc(g.get("reason"))}</div>'
        f'<div class="rl" style="margin-top:14px">3 &middot; What to change,'
        f' and where</div><div class="rv">'
        f'<b>{esc(g.get("where_to_fix"))}</b></div>', unsafe_allow_html=True)
    right.markdown(
        f'<div class="rl">2 &middot; Why it happened</div>'
        f'<div class="rv">{esc(g.get("means"))}</div>'
        f'<div class="rl" style="margin-top:14px">4 &middot; How to fix it'
        f'</div><div class="rv">{esc(g.get("to_fix"))}'
        f'<div class="owner">{esc(g.get("owner"))}</div></div>',
        unsafe_allow_html=True)

    if g.get("tests"):
        section("The checks this covers")
        st.dataframe([{"Check": t} for t in g["tests"]],
                     use_container_width=True, hide_index=True)

    section("History")
    for event in store.history(f["key"], DB):
        st.markdown(
            f'<div class="note"><div><div class="ntext">'
            f'{esc(event["text"])}</div><div class="nwhen">'
            + esc(who(event["by_email"]) if event["by_email"]
                  else "the platform")
            + f' &middot; {ago(event["at"])}</div></div></div>',
            unsafe_allow_html=True)
    if can("comment"):
        note = st.text_area("Add a note",
                            placeholder="For whoever picks this up",
                            key=f"n_{ref}")
        if st.button("Add note", key=f"nb_{ref}") and note.strip():
            store.add_note(f["key"], note.strip(), me()["email"], DB)
            st.rerun()


# ------------------------------------------------------- platform health
def page_platform() -> None:
    everything = store.findings(path=DB)
    ours = [f for f in everything
            if f["cause"] in ("TEST_MODEL_GAP", "HARNESS_FAULT")]
    asked = [f for f in everything if f["cause"] == "UNSETTLED_QUESTION"]
    st.markdown("# The platform itself")
    st.markdown('<p class="blurb">Findings blamed on our own checks rather '
                'than on a questionnaire. Nobody outside this team will '
                'notice these, so if the platform does not count them, '
                'nothing does.</p>', unsafe_allow_html=True)
    share = f"{len(ours) / len(everything):.0%}" if everything else "\u2014"
    strip([("Our checks at fault", len(ours), "warn" if ours else "ok"),
           ("As a share of everything found", share, "warn" if ours else ""),
           ("Waiting on a client answer", len(asked),
            "warn" if asked else "ok"),
           ("Raised in total", len(everything), ""),
           ("Closed", sum(1 for f in everything
                          if f["state"] == "Closed"), "ok")])

    section("Where our checks are wrong")
    if ours:
        for f in ours:
            finding_row(f)
    else:
        st.success("Nothing currently blamed on our own checks.")

    section("Readings nobody has settled",
            "Points a questionnaire leaves open. A check resting on a guess "
            "is not evidence until somebody rules on it.")
    if asked:
        for f in asked:
            finding_row(f)
    else:
        st.info("No open questions for a client.")


# ------------------------------------------------------------ house rules
def page_rules() -> None:
    st.markdown("# House rules")
    st.markdown('<p class="blurb">Checks applied to every questionnaire, '
                'whatever it says. This is where an agency\u2019s own '
                'standards live, and it is what makes this a platform '
                'rather than a tool one person runs.</p>',
                unsafe_allow_html=True)
    rules = store.house_rules(DB)
    if not rules:
        views.waiting("No rules yet",
                      "Run the seed script to put the starting set in.")
        return
    strip([("Rules on", sum(1 for r in rules if r["enabled"]), ""),
           ("Rules off", sum(1 for r in rules if not r["enabled"]), ""),
           ("Questionnaires covered", len(store.questionnaires(DB)), "")])
    for rule in rules:
        left, right = st.columns([7, 1])
        left.markdown(f'<div class="rulerow">{esc(rule["name"])}</div>',
                      unsafe_allow_html=True)
        on = right.toggle("on", value=bool(rule["enabled"]),
                          key=f"rule_{rule['key']}",
                          label_visibility="collapsed")
        if on != bool(rule["enabled"]):
            store.set_rule(rule["key"], on, DB)
            st.rerun()


# ------------------------------------------------------------------ admin
def page_admin() -> None:
    st.markdown("# Users and roles")
    st.markdown('<p class="blurb">Who is on the platform, what role they '
                'carry, and what each role may do. A role is a set of '
                'permissions, so changing one here changes it for everybody '
                'who holds it.</p>', unsafe_allow_html=True)

    section("People")
    roles = store.all_roles(DB)
    for p in store.people(DB):
        row = st.columns([2.8, 1.7, 1.9, 1.1, 1])
        row[0].markdown(f'<div class="rulerow">{esc(p["email"])}</div>',
                        unsafe_allow_html=True)
        row[1].markdown(f'<div class="rulerow">{esc(p["name"])}</div>',
                        unsafe_allow_html=True)
        index = roles.index(p["role"]) if p["role"] in roles else 0
        choice = row[2].selectbox("role", roles, index=index,
                                  key=f"role_{p['email']}",
                                  label_visibility="collapsed")
        if choice != p["role"]:
            store.set_role(p["email"], choice, DB)
            toast(f"{p['email']} is now a {choice}")
            st.rerun()
        row[3].markdown(
            f'<span class="pill {"ok" if p["active"] else "warn"}">'
            f'{"active" if p["active"] else "suspended"}</span>',
            unsafe_allow_html=True)
        if row[4].button("Suspend" if p["active"] else "Re-enable",
                         key=f"act_{p['email']}", use_container_width=True):
            store.set_active(p["email"], not p["active"], DB)
            st.rerun()

    with st.expander("Add somebody"):
        a, b, c, d = st.columns(4)
        email = a.text_input("Email", key="new_email")
        name = b.text_input("Name", key="new_name")
        role = c.selectbox("Role", roles, key="new_role")
        d.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
        if d.button("Add", key="add_person",
                    use_container_width=True) and email and name:
            initials = "".join(w[0] for w in name.split()[:2]).upper()
            store.add_person(email, name, initials, role, "escalent", DB)
            toast(f"{email} added. Their password is escalent.")
            st.rerun()

    section("What each role may do",
            "Tick to grant. The change applies to everyone holding that "
            "role the next time they load a page.")
    header = st.columns([2.6] + [1] * len(roles))
    header[0].markdown("**Permission**")
    for i, role in enumerate(roles, start=1):
        header[i].markdown(f"**{role}**")
    for key, label in store.PERMISSIONS.items():
        row = st.columns([2.6] + [1] * len(roles))
        row[0].markdown(f'<div class="rulerow">{esc(label)}</div>',
                        unsafe_allow_html=True)
        for i, role in enumerate(roles, start=1):
            has = key in store.permissions_of(role, DB)
            new = row[i].checkbox(key, value=has, key=f"p_{role}_{key}",
                                  label_visibility="collapsed")
            if new == has:
                continue
            if role == me()["role"] and key == "admin" and not new:
                # Letting somebody remove their own way back in is a trap,
                # not a feature.
                toast("Refused: that would lock you out of this screen.")
                st.rerun()
            (store.grant if new else store.revoke)(role, key, DB)
            if role == me()["role"]:
                st.session_state["rights"] = store.permissions_of(role, DB)
            st.rerun()


# ------------------------------------------------- keeping the two in step
def wrap_runners() -> None:
    """Make the shared runners tell the database what they did.

    The views call stream_bot and run_adjudicator directly, as they always
    have. Rather than fork them, each is wrapped so that after it finishes
    the run is recorded and the findings folded in. The view does not know
    this is happening, which is what lets both apps use the same code.
    """
    if getattr(views, "_wrapped_for_team", False):
        return
    views._wrapped_for_team = True

    original_bot = views.stream_bot
    original_judge = views.run_adjudicator

    def bot(state, *args, **kwargs):
        result = original_bot(state, *args, **kwargs)
        try:
            record_run(state["name"])
        except Exception as exc:                       # never lose a run
            st.caption(f"The run finished but was not recorded: {exc}")
        return result

    def judge(state, *args, **kwargs):
        result = original_judge(state, *args, **kwargs)
        try:
            record_judgement(state["name"])
        except Exception as exc:
            st.caption(f"The judgement finished but was not recorded: {exc}")
        return result

    views.stream_bot = bot
    views.run_adjudicator = judge


STYLE = """<style>
      /* The bar is a drawn strip. Nothing is positioned, so nothing can
         cover the navigation, which is what went wrong when it was fixed
         to the top of the window. */
      .block-container{padding-top:1.2rem!important;max-width:100%!important}
      header[data-testid="stHeader"]{background:transparent;height:0}
      div[data-testid="stDecoration"]{display:none}
      .appbar{background:#16132B;border-radius:10px;padding:13px 18px;display:flex;align-items:center;margin-bottom:10px}
      .appbar .mark{color:#fff;font-weight:600;font-size:.96rem}
      .appbar .mark i{color:#9C93D8;font-style:normal;font-weight:400;margin-left:6px}
      .appbar .meline{margin-left:auto;color:#B9B4D4;font-size:.83rem}
      /* the nav row, as pills rather than default buttons */
      .navwrap + div div[data-testid="stHorizontalBlock"] .stButton button,
      div[data-testid="stHorizontalBlock"]:has(+ div .navend) .stButton button{min-height:0}
      .stButton button{border-radius:8px!important;border:1px solid var(--rule)!important;background:var(--card)!important;color:var(--ink-2)!important;font-weight:500!important;font-size:.88rem!important;box-shadow:none!important}
      .stButton button:hover{border-color:var(--accent)!important;color:var(--accent)!important}
      .stButton button p{color:inherit!important;font-weight:inherit!important}
      .stButton button[kind="primary"]{background:var(--ink)!important;border-color:var(--ink)!important}
      .stButton button[kind="primary"] p{color:#fff!important;font-weight:600!important}
      .stDownloadButton button{border-radius:8px!important;border:1px solid var(--rule)!important;background:var(--card)!important;color:var(--accent)!important}
      /* tabs, dressed like the mock-up */
      div[data-baseweb="tab-list"]{gap:2px;border-bottom:1px solid var(--rule)}
      button[data-baseweb="tab"]{font-size:.9rem!important;padding:9px 16px!important}
      button[data-baseweb="tab"][aria-selected="true"] p{color:var(--accent)!important;font-weight:600!important}
      div[data-baseweb="tab-highlight"]{background:var(--accent)!important}
      /* the segmented control */
      div[data-testid="stRadio"] > div{gap:0;border-bottom:1px solid var(--rule);margin-bottom:14px}
      div[data-testid="stRadio"] label{padding:8px 15px 9px;margin:0;border-bottom:2px solid transparent}
      div[data-testid="stRadio"] label:has(input:checked){border-bottom-color:var(--accent)}
      div[data-testid="stRadio"] label:has(input:checked) p{color:var(--accent)!important;font-weight:600}
      div[data-testid="stRadio"] label > div:first-child{display:none}
      div[data-testid="stRadio"] label p{font-size:.9rem!important;color:var(--ink-3)}
      /* the login card */
      .lbrand{display:flex;align-items:center;gap:12px;margin:40px 0 14px}
      .lbrand .logo{width:38px;height:38px;border-radius:10px;background:var(--ink);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600}
      .lbrand .bn{font-weight:600;font-size:1.15rem}
      .lbrand .bs{font-size:.8rem;color:var(--ink-3)}
      /* a piece of work waiting on somebody */
      .work{border:1px solid var(--rule);border-radius:8px;background:var(--card);padding:11px 14px;margin-bottom:6px}
      .work.urgent{border-left:3px solid var(--bad)}
      .wtop{display:flex;align-items:baseline;gap:10px}
      .wid{font-family:'IBM Plex Mono',monospace;font-size:.78rem;color:var(--ink-3);flex:0 0 44px}
      .wtitle{font-weight:500;font-size:.9rem;line-height:1.45}
      .wmeta{display:flex;align-items:center;gap:8px;margin-top:7px;font-size:.78rem;color:var(--ink-3);flex-wrap:wrap;padding-left:54px}
      .wclient{color:var(--ink);font-weight:600;font-family:'IBM Plex Mono',monospace}
      .flag{background:var(--bad-bg);color:var(--bad);padding:1px 8px;border-radius:4px;font-weight:600;font-size:.72rem}
      .wvname{font-size:.89rem;padding-top:8px;font-weight:500}
      .wvmeta{color:var(--ink-3);font-size:.78rem;padding-top:9px}
      /* the findings board */
      .fhead{display:flex;align-items:center;gap:7px;font-size:.8rem;font-weight:600;color:var(--ink-2);margin-bottom:8px}
      .fcount{margin-left:auto;color:var(--ink-3);font-weight:400}
      .fcard{background:var(--card);border:1px solid var(--rule);border-radius:7px;padding:9px 10px;margin-bottom:4px}
      .ftop{display:flex;align-items:center;gap:6px;margin-bottom:5px;flex-wrap:wrap}
      .fid{font-family:'IBM Plex Mono',monospace;font-size:.72rem;color:var(--ink-3)}
      .fwhat{font-size:.8rem;line-height:1.45;margin-bottom:6px}
      .fmeta{font-size:.73rem;color:var(--ink-3);margin-bottom:6px;font-family:'IBM Plex Mono',monospace}
      .ffoot{display:flex;align-items:center;font-size:.76rem;color:var(--ink-2)}
      .fage{margin-left:auto;color:var(--ink-4)}
      div[data-testid="stColumn"]:has(.fhead){background:#F4F2FA;border-radius:9px;padding:10px 10px 4px}
      /* what changed between runs */
      .dcell{border:1px solid var(--rule);border-radius:8px;background:var(--card);padding:13px 16px}
      .dcell.good{border-left:3px solid var(--ok)}
      .dcell.worse{border-left:3px solid var(--bad)}
      .dcell .dn{font-size:1.5rem;font-weight:600;line-height:1.1}
      .dcell.good .dn{color:var(--ok)}
      .dcell.worse .dn{color:var(--bad)}
      .dcell .dl{font-size:.82rem;color:var(--ink-2);margin-top:2px}
      .dcell .dd{font-size:.75rem;color:var(--ink-3);margin-top:5px}
      .note{padding:10px 0;border-bottom:1px solid var(--rule-2)}
      .ntext{font-size:.87rem;line-height:1.5}
      .nwhen{font-size:.74rem;color:var(--ink-4);margin-top:2px}
      .rulerow{font-size:.87rem;padding-top:9px;line-height:1.4}
      .alab{font-size:.8rem;color:var(--ink-3);padding-top:10px}
</style>"""


def main() -> None:
    store.setup(DB)
    # Both stylesheets, on every run. An import happens once and a
    # Streamlit script runs again on every click, so anything emitted at
    # import time is gone the moment somebody presses a button.
    st.markdown(views.STYLE, unsafe_allow_html=True)
    st.markdown(STYLE, unsafe_allow_html=True)

    if "me" not in st.session_state:
        login_page()
        return
    wrap_runners()
    backfill()
    top_bar()

    message = st.session_state.pop("toast", None)
    if message:
        st.toast(message)

    if st.session_state.get("open_survey"):
        page_survey()
        return

    {"today": page_today, "corpus": page_corpus, "findings": page_findings,
     "platform": page_platform, "rules": page_rules,
     "admin": page_admin}[st.session_state["page"]]()


main()
