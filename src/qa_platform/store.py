"""Everything the platform knows that no agent produces.

The dividing line matters and is worth stating once. The ``out/`` folder is
the record of what the agents found: it is rewritten whenever a stage runs,
and nothing here may contradict it. This database is the record of what
people decided about those findings: who owns one, what state it is in, what
they said about it. Blend the two and you lose the ability to re-run a stage
and trust the result, because you can no longer tell a fact from an opinion.

SQLite because it is one file, needs no server, and the whole team's history
will not trouble it for years.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/platform.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS person (
    email       TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    initials    TEXT NOT NULL,
    role        TEXT NOT NULL,
    password    TEXT NOT NULL,     -- salted hash, never the password
    active      INTEGER NOT NULL DEFAULT 1,
    last_seen   TEXT
);

CREATE TABLE IF NOT EXISTS role_permission (
    role        TEXT NOT NULL,
    permission  TEXT NOT NULL,
    PRIMARY KEY (role, permission)
);

-- A questionnaire the platform knows about. The run folder is the link back
-- to what the agents wrote; everything else here is ours.
CREATE TABLE IF NOT EXISTS questionnaire (
    run_name    TEXT PRIMARY KEY,
    code        TEXT,
    title       TEXT,
    tier        TEXT,
    client      TEXT,
    owner       TEXT,
    due         TEXT,
    held_back   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (owner) REFERENCES person(email)
);

-- One row per time the bot ran. Agent 4 used to overwrite its results, so
-- there was no way to ask what changed; this is what makes that answerable.
CREATE TABLE IF NOT EXISTS run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_name    TEXT NOT NULL,
    started     TEXT NOT NULL,
    finished    TEXT,
    by_email    TEXT,
    folder      TEXT NOT NULL,     -- out/<name>/runs/<stamp>
    checks      INTEGER DEFAULT 0,
    passed      INTEGER DEFAULT 0,
    failed      INTEGER DEFAULT 0,
    blocked     INTEGER DEFAULT 0,
    FOREIGN KEY (run_name) REFERENCES questionnaire(run_name)
);
CREATE INDEX IF NOT EXISTS run_by_name ON run(run_name, started DESC);

-- A finding keeps its identity across runs, which is the whole point: an
-- owner and a conversation survive a re-run, and closing one means
-- something. The key is derived from what the finding is about, never from
-- a row number.
CREATE TABLE IF NOT EXISTS finding (
    key         TEXT PRIMARY KEY,
    ref         TEXT UNIQUE,       -- F-104, for people to say out loud
    run_name    TEXT NOT NULL,
    question    TEXT,
    cause       TEXT,
    label       TEXT,
    headline    TEXT,
    state       TEXT NOT NULL DEFAULT 'Open',
    owner       TEXT,
    blocks      INTEGER NOT NULL DEFAULT 0,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    closed_at   TEXT,
    payload     TEXT               -- the agent's own words, as written
);
CREATE INDEX IF NOT EXISTS finding_by_name ON finding(run_name, state);

CREATE TABLE IF NOT EXISTS finding_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_key TEXT NOT NULL,
    at          TEXT NOT NULL,
    by_email    TEXT,
    kind        TEXT NOT NULL,     -- state | assign | note | reopened
    text        TEXT,
    FOREIGN KEY (finding_key) REFERENCES finding(key)
);
CREATE INDEX IF NOT EXISTS event_by_finding ON finding_event(finding_key, at DESC);

CREATE TABLE IF NOT EXISTS house_rule (
    key         TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'all',
    enabled     INTEGER NOT NULL DEFAULT 1
);
"""

STATES = ["Open", "In progress", "Asked client",
          "Fixed, awaiting re-run", "Closed"]

PERMISSIONS = {
    "read":      "Read a questionnaire and its results",
    "run":       "Run a stage",
    "judge":     "Judge a run",
    "triage":    "Move a finding to any state",
    "markfixed": "Mark a finding fixed",
    "assign":    "Assign a finding to someone",
    "comment":   "Add a note to a finding",
    "signoff":   "Sign a questionnaire off for fielding",
    "rules":     "Turn house rules on and off",
    "admin":     "Add people and change their role",
}

DEFAULT_ROLES = {
    "QA tester":         ["read", "run", "judge", "triage", "assign", "comment"],
    "Survey programmer": ["read", "run", "markfixed", "comment"],
    "Project lead":      ["read", "assign", "comment", "signoff"],
    "QA manager":        ["read", "judge", "triage", "assign", "comment",
                          "rules", "admin"],
    "Client reviewer":   ["read", "comment"],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(path: Path | str = DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def setup(path: Path | str = DB_PATH) -> None:
    """Create the tables and the default roles. Safe to call every start."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        have = conn.execute("SELECT COUNT(*) c FROM role_permission").fetchone()
        if not have["c"]:
            for role, perms in DEFAULT_ROLES.items():
                for p in perms:
                    conn.execute(
                        "INSERT OR IGNORE INTO role_permission VALUES (?,?)",
                        (role, p))


# ------------------------------------------------------------------ people
def hash_password(password: str, email: str) -> str:
    """Salted with the email. Not a substitute for a real identity provider,
    which is the production answer, but it means the database never holds a
    password in the clear."""
    return hashlib.sha256((email + "::" + password).encode()).hexdigest()


def add_person(email, name, initials, role, password,
               path=DB_PATH, active=True) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO person "
            "(email,name,initials,role,password,active,last_seen) "
            "VALUES (?,?,?,?,?,?,COALESCE("
            "  (SELECT last_seen FROM person WHERE email=?), NULL))",
            (email.lower(), name, initials, role,
             hash_password(password, email.lower()), 1 if active else 0,
             email.lower()))


def authenticate(email: str, password: str, path=DB_PATH):
    """Returns the person, or a reason they cannot sign in."""
    email = (email or "").strip().lower()
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM person WHERE email=?",
                           (email,)).fetchone()
        if row is None:
            return None, "No account with that email."
        if row["password"] != hash_password(password or "", email):
            return None, "That password is not right."
        if not row["active"]:
            return None, ("That account is suspended. Ask an administrator "
                          "to re-enable it.")
        conn.execute("UPDATE person SET last_seen=? WHERE email=?",
                     (now(), email))
        return dict(row), None


def people(path=DB_PATH) -> list[dict]:
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM person ORDER BY name")]


def set_role(email, role, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE person SET role=? WHERE email=?", (role, email))


def set_active(email, active, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE person SET active=? WHERE email=?",
                     (1 if active else 0, email))


# ------------------------------------------------------------ roles, rights
def permissions_of(role: str, path=DB_PATH) -> set[str]:
    with connect(path) as conn:
        return {r["permission"] for r in conn.execute(
            "SELECT permission FROM role_permission WHERE role=?", (role,))}


def all_roles(path=DB_PATH) -> list[str]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT role FROM role_permission ORDER BY role")
        return [r["role"] for r in rows]


def grant(role, permission, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("INSERT OR IGNORE INTO role_permission VALUES (?,?)",
                     (role, permission))


def revoke(role, permission, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "DELETE FROM role_permission WHERE role=? AND permission=?",
            (role, permission))


# --------------------------------------------------------- questionnaires
def upsert_questionnaire(run_name, **fields) -> None:
    with connect(fields.pop("path", DB_PATH)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO questionnaire (run_name) VALUES (?)",
            (run_name,))
        for key, value in fields.items():
            conn.execute(f"UPDATE questionnaire SET {key}=? WHERE run_name=?",
                         (value, run_name))


def questionnaires(path=DB_PATH) -> list[dict]:
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM questionnaire ORDER BY tier, run_name")]


# ------------------------------------------------------------------- runs
def start_run(run_name, folder, by_email, path=DB_PATH) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO run (run_name, started, by_email, folder) "
            "VALUES (?,?,?,?)", (run_name, now(), by_email, str(folder)))
        return cur.lastrowid


def finish_run(run_id, checks, passed, failed, blocked, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "UPDATE run SET finished=?, checks=?, passed=?, failed=?, "
            "blocked=? WHERE id=?",
            (now(), checks, passed, failed, blocked, run_id))


def runs_of(run_name, limit=20, path=DB_PATH) -> list[dict]:
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(
            # id breaks the tie. Two runs started in the same second sort
            # arbitrarily on the timestamp alone, and a comparison done
            # backwards reports every fix as a breakage.
            "SELECT * FROM run WHERE run_name=? "
            "ORDER BY started DESC, id DESC LIMIT ?", (run_name, limit))]


def compare_runs(run_name, path=DB_PATH) -> dict:
    """What changed between the last two runs.

    The question after every fix is whether it worked and whether it broke
    something else. Answering it needs two runs kept side by side, which is
    why a run writes to its own folder instead of overwriting the last.
    """
    rows = runs_of(run_name, limit=2, path=path)
    if len(rows) < 2:
        return {"have": False}

    def outcomes(folder):
        f = Path(folder) / "agent4_results.json"
        if not f.exists():
            return {}
        doc = json.loads(f.read_text(encoding="utf-8"))
        return {r.get("case_id") or r.get("test_id"): r.get("status")
                for r in doc.get("results", [])}

    now_, before = outcomes(rows[0]["folder"]), outcomes(rows[1]["folder"])
    fixed, broke, still = [], [], []
    for check, state in now_.items():
        was = before.get(check)
        if was is None:
            continue
        if was != "PASSED" and state == "PASSED":
            fixed.append(check)
        elif was == "PASSED" and state != "PASSED":
            broke.append(check)
        elif was != "PASSED" and state != "PASSED":
            still.append(check)
    return {"have": True, "fixed": sorted(fixed), "broke": sorted(broke),
            "still": sorted(still),
            "new": sorted(set(now_) - set(before)),
            "gone": sorted(set(before) - set(now_))}


# --------------------------------------------------------------- findings
def finding_key(run_name, question, cause, checks) -> str:
    """A finding's identity, derived from what it is about.

    Keyed on the questionnaire, the question, the cause and the checks it
    covers. Re-run the bot and the same problem produces the same key, so
    its owner and its conversation survive; fix it and it stops appearing.
    A row number would lose all of that the moment a check was added.
    """
    seed = f"{run_name}|{question}|{cause}|{','.join(sorted(checks))}"
    return hashlib.sha1(seed.encode()).hexdigest()[:16]


def _next_ref(conn) -> str:
    row = conn.execute(
        "SELECT ref FROM finding WHERE ref LIKE 'F-%' "
        "ORDER BY CAST(SUBSTR(ref,3) AS INTEGER) DESC LIMIT 1").fetchone()
    n = int(row["ref"][2:]) + 1 if row else 101
    return f"F-{n}"


def run_is_trustworthy(results: list[dict], floor: float = 0.5) -> tuple:
    """Whether a run proved enough to be allowed to close anything.

    A run where most checks never finished has not shown that a defect is
    gone; it has shown that the bot could not look. Letting such a run close
    findings would quietly retire real defects, which is worse than not
    running at all.

    Learned from a run at forty-one workers that saturated LimeSurvey:
    every check blocked, no findings were produced, and nothing in the
    pipeline would have objected to closing them all.
    """
    total = len(results)
    if not total:
        return False, "the run produced no results at all"
    usable = sum(1 for r in results
                 if r.get("status") in ("PASSED", "FAILED"))
    share = usable / total
    if share < floor:
        return False, (f"only {usable} of {total} checks actually finished "
                       f"({share:.0%}). A run that could not look is not "
                       f"evidence that anything is fixed")
    return True, ""


def sync_findings(run_name, groups, results=None, path=DB_PATH) -> dict:
    """Fold what Agent 5 just found into what we already knew.

    Three things happen here and each matters. A problem seen before keeps
    its key, so its owner and history carry over. One that has reappeared
    after being closed is reopened rather than filed again, because somebody
    believed it was fixed and was wrong, and that is worth saying. One that
    has stopped appearing is closed as fixed by the run itself.
    """
    # A run that mostly failed to run may raise findings, but it may not
    # close them: absence of evidence is not evidence of a fix.
    may_close, why_not = (True, "")
    if results is not None:
        may_close, why_not = run_is_trustworthy(results)

    seen, opened, reopened = set(), [], []
    with connect(path) as conn:
        for g in groups:
            checks = [str(c) for c in (g.get("tests") or [])]
            key = finding_key(run_name, g.get("question"), g.get("cause"),
                              checks)
            seen.add(key)
            row = conn.execute("SELECT * FROM finding WHERE key=?",
                               (key,)).fetchone()
            payload = json.dumps(g, default=str)
            if row is None:
                ref = _next_ref(conn)
                conn.execute(
                    "INSERT INTO finding (key,ref,run_name,question,cause,"
                    "label,headline,state,owner,blocks,first_seen,last_seen,"
                    "payload) VALUES (?,?,?,?,?,?,?,'Open',NULL,?,?,?,?)",
                    (key, ref, run_name, g.get("question"), g.get("cause"),
                     g.get("label"), (g.get("reason") or "")[:300],
                     1 if g.get("cause") in ("SURVEY_DEFECT",
                                             "SPECIFICATION_ERROR") else 0,
                     now(), now(), payload))
                conn.execute(
                    "INSERT INTO finding_event (finding_key,at,kind,text) "
                    "VALUES (?,?,'state',?)",
                    (key, now(), "Raised by the platform."))
                opened.append(ref)
            else:
                conn.execute(
                    "UPDATE finding SET last_seen=?, payload=? WHERE key=?",
                    (now(), payload, key))
                if row["state"] == "Closed":
                    conn.execute(
                        "UPDATE finding SET state='Open', closed_at=NULL "
                        "WHERE key=?", (key,))
                    conn.execute(
                        "INSERT INTO finding_event (finding_key,at,kind,text)"
                        " VALUES (?,?,'reopened',?)",
                        (key, now(), "Seen again after being closed."))
                    reopened.append(row["ref"])

        # Anything that was open and has stopped appearing is fixed, but
        # only if this run was in a position to tell.
        gone = []
        if not may_close:
            return {"opened": opened, "reopened": reopened, "closed": [],
                    "held_open": why_not}
        for row in conn.execute(
                "SELECT * FROM finding WHERE run_name=? AND state!='Closed'",
                (run_name,)):
            if row["key"] in seen:
                continue
            conn.execute(
                "UPDATE finding SET state='Closed', closed_at=? WHERE key=?",
                (now(), row["key"]))
            conn.execute(
                "INSERT INTO finding_event (finding_key,at,kind,text) "
                "VALUES (?,?,'state',?)",
                (row["key"], now(), "No longer found. Closed by the run."))
            gone.append(row["ref"])
    return {"opened": opened, "reopened": reopened, "closed": gone,
            "held_open": ""}


def findings(run_name=None, state=None, owner=None, path=DB_PATH) -> list[dict]:
    where, args = [], []
    if run_name:
        where.append("run_name=?"); args.append(run_name)
    if state:
        where.append("state=?"); args.append(state)
    if owner:
        where.append("owner=?"); args.append(owner)
    sql = "SELECT * FROM finding"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY blocks DESC, first_seen DESC"
    with connect(path) as conn:
        out = []
        for r in conn.execute(sql, args):
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            out.append(d)
        return out


def finding_by_ref(ref, path=DB_PATH):
    with connect(path) as conn:
        r = conn.execute("SELECT * FROM finding WHERE ref=?", (ref,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        return d


def move_finding(key, state, by_email, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "UPDATE finding SET state=?, closed_at=? WHERE key=?",
            (state, now() if state == "Closed" else None, key))
        conn.execute(
            "INSERT INTO finding_event (finding_key,at,by_email,kind,text) "
            "VALUES (?,?,?,'state',?)",
            (key, now(), by_email, f"Moved to {state}."))


def assign_finding(key, to_email, by_email, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE finding SET owner=? WHERE key=?", (to_email, key))
        conn.execute(
            "INSERT INTO finding_event (finding_key,at,by_email,kind,text) "
            "VALUES (?,?,?,'assign',?)",
            (key, now(), by_email, f"Assigned to {to_email}."))


def add_note(key, text, by_email, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO finding_event (finding_key,at,by_email,kind,text) "
            "VALUES (?,?,?,'note',?)", (key, now(), by_email, text))


def history(key, path=DB_PATH) -> list[dict]:
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM finding_event WHERE finding_key=? "
            "ORDER BY at DESC, id DESC", (key,))]


# ------------------------------------------------------------- house rules
def house_rules(path=DB_PATH) -> list[dict]:
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM house_rule ORDER BY name")]


def set_rule(key, enabled, path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE house_rule SET enabled=? WHERE key=?",
                     (1 if enabled else 0, key))
