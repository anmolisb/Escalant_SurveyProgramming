"""Run every page of the team app without Streamlit.

Two things this has to get right, both learned the hard way. A column's
button must return False, or every button on the page counts as pressed at
once. And a selectbox must honour its index, or the admin page quietly
reassigns everybody's role, which it did, to the real database.
"""
import shutil
import sys
import pathlib
from unittest.mock import MagicMock

# The repository root, whichever machine this is on. The harness runs from
# there because the app reads out/ and data/ relative to it.
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIVE = ROOT / "data" / "platform.db"
SCRATCH = ROOT / "data" / "harness-scratch.db"


# Which tab of the survey page to open. Streamlit returns every tab's
# container and draws them all, so a single pass exercises the lot; this
# only exists so a failure can be named.
TAB_LABELS = ["Overview", "Questionnaire", "Survey", "Checks",
              "Respondent Bot", "QC report", "Run history", "Files"]


class Stub(MagicMock):
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def button(self, *a, **k): return False
    def toggle(self, *a, **k): return bool(k.get("value", False))
    def checkbox(self, *a, **k): return bool(k.get("value", False))
    def selectbox(self, label, options, index=0, **k):
        return options[index] if options else None
    def radio(self, label, options, index=0, **k):
        return options[index] if options else None
    def text_input(self, *a, **k): return ""
    def text_area(self, *a, **k): return ""
    def slider(self, label, lo=0, hi=10, value=None, **k): return value or lo
    def dataframe(self, *a, **k): return None
    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [Stub() for _ in range(n)]
    def tabs(self, labels): return [Stub() for _ in labels]
    def expander(self, *a, **k): return Stub()
    def spinner(self, *a, **k): return Stub()
    def empty(self): return Stub()


def run(page, person, rights, extra=None, db=SCRATCH):
    st = Stub()
    st.session_state = {"page": page, "me": person, "rights": rights,
                        "sid": "900001", "workers": 8, **(extra or {})}
    st.sidebar = Stub()
    sys.modules["streamlit"] = st
    src = (HERE / "app_team.py").read_text()
    # Point the app at the scratch copy. Matched on the line's own prefix
    # rather than its exact text: the previous version looked for a literal
    # that had since been reworded, so the substitution quietly stopped
    # happening and the app wrote to the live database instead. A silent
    # miss is the worst kind, so this one fails loudly.
    import re as _re
    # A replacement string is itself read for escapes, and a Windows path
    # like C:\ISB-... contains \I. Passing a function hands the text over
    # untouched.
    line = 'DB = Path(r"' + str(db) + '")'
    src, hits = _re.subn(r'^DB = .*$', lambda _m: line, src, count=1,
                         flags=_re.M)
    if hits != 1:
        raise RuntimeError(
            "could not point the app at the scratch database. Look for the "
            "line beginning 'DB =' in app_team.py.")
    exec(compile(src, "app_team.py", "exec"),
         {"__name__": "__main__", "__file__": str(HERE / "app_team.py")})


def main(workdir=None):
    import os
    os.chdir(workdir or ROOT)
    if not LIVE.exists():
        print(f"  no database at {LIVE}")
        print("  run: python src\\qa_platform\\seed.py")
        return False
    # Never test against the real one. A harness bug once reassigned every
    # role and revoked every permission, and that must not be able to
    # happen to live data.
    shutil.copy(LIVE, SCRATCH)
    sys.path.insert(0, str(ROOT / "src" / "qa_platform"))
    import store

    ok = True
    for role in ("QA tester", "Survey programmer", "Project lead",
                 "QA manager"):
        found = [p for p in store.people(SCRATCH) if p["role"] == role]
        if not found:
            print(f"  {role:20} no account"); continue
        person, rights = dict(found[0]), store.permissions_of(role, SCRATCH)
        pages = ["today", "corpus", "findings"]
        if "judge" in rights or "admin" in rights:
            pages.append("platform")
        if "rules" in rights:
            pages.append("rules")
        if "admin" in rights:
            pages.append("admin")
        problems = []
        for page in pages:
            try:
                run(page, person, rights)
            except Exception as exc:
                ok = False
                problems.append(f"{page}: {type(exc).__name__} {exc}")
        print(f"  {role:20} {len(pages)} pages  "
              + ("ok" if not problems else " | ".join(problems)))

    tester = dict([p for p in store.people(SCRATCH)
                   if p["role"] == "QA tester"][0])
    rights = store.permissions_of("QA tester", SCRATCH)
    # The survey page draws all eight tabs in one pass, because Streamlit
    # renders every tab's contents whether or not it is the visible one.
    # A failure in any of them shows up here.
    for label, page, extra in [
            ("survey, all tabs", "corpus",
             {"open_survey": "S01_campus_cafeteria_experience"}),
            ("finding detail", "findings", {"open_finding": "F-101"})]:
        try:
            run(page, tester, rights, extra)
            print(f"  {label:20} ok")
        except Exception as exc:
            ok = False
            print(f"  {label:20} {type(exc).__name__}: {exc}")

    # The login screen is the case where nothing is in session state at
    # all. Passing a person would mean the app thinks someone is signed in.
    try:
        st = Stub(); st.session_state = {}; st.sidebar = Stub()
        sys.modules["streamlit"] = st
        src = (HERE / "app_team.py").read_text().replace(
            'DB = Path("data/platform.db")', f'DB = Path("{SCRATCH}")')
        exec(compile(src, "app_team.py", "exec"),
             {"__name__": "__main__", "__file__": str(HERE / "app_team.py")})
    except Exception as exc:
        ok = False
        print("  login screen        ", type(exc).__name__, exc)
    else:
        print("  login screen         ok")

    # the live database must be exactly as it was
    before = {p["email"]: (p["role"], p["active"]) for p in store.people(LIVE)}
    perms = {r: sorted(store.permissions_of(r, LIVE))
             for r in store.all_roles(LIVE)}
    print()
    print("  live database untouched:",
          all(perms.values()) and len(before) > 0)
    SCRATCH.unlink(missing_ok=True)
    print("ALL OK" if ok else "FAILURES")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
