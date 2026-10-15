"""Runs the agents for the web app, one survey at a time, in the background.

Each agent runs exactly as it does from the command line, as its own Python
process, so the web app adds no second way of running anything. What a run
prints goes to `out/<survey>/run.log` (ignored by git), which the app shows
while it runs.

A run is a chain of agents. Uploading a questionnaire runs Agents 1 to 3,
since none of them needs anything from a person. Agent 4 needs the survey to
be imported into LimeSurvey first, so it is started separately, with the
survey's id, and Agent 5 follows it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from src.common.paths import OUT_ROOT, REPO_ROOT, agent2_lss

#: Questionnaires uploaded through the app. Under data/, which git ignores,
#: because a client's questionnaire must never be committed (principle 12).
UPLOADS = REPO_ROOT / "data" / "uploads"
#: The development corpus, so its surveys can be re-run from the app too.
CORPUS = REPO_ROOT / "fixtures" / "qre-samples"

AGENT_NAMES = {
    1: "Reading the questionnaire",
    2: "Building the survey",
    3: "Designing the tests",
    4: "Running the tests",
    5: "Explaining the results",
}

#: Exit codes after which the chain carries on. Agent 1 exits 2 when its own
#: checks found something to look at; it has still written everything, and
#: the later agents run with that status in view.
CARRY_ON = {1: {0, 2}}

LOG = "run.log"


class JobError(Exception):
    """A run that cannot be started, with the reason to show."""


@dataclass
class Step:
    agent: int
    status: str = "waiting"      # waiting, running, done, flagged, failed, stopped
    exit_code: int | None = None


@dataclass
class Job:
    survey: str
    steps: list[Step]
    started: float = field(default_factory=time.time)
    finished: float | None = None
    process: subprocess.Popen | None = None
    stop_requested: bool = False

    @property
    def running(self) -> bool:
        return self.finished is None

    def view(self) -> dict:
        return {
            "survey": self.survey,
            "running": self.running,
            "started": self.started,
            "finished": self.finished,
            "steps": [{"agent": s.agent, "name": AGENT_NAMES[s.agent],
                       "status": s.status, "exit_code": s.exit_code}
                      for s in self.steps],
            "log": tail(OUT_ROOT / self.survey / LOG),
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def tail(path: Path, lines: int = 400) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def safe_name(filename: str) -> str:
    """A run name from an uploaded file's name: letters, digits, _ and - only."""
    stem = Path(filename).stem
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_-")
    if not name:
        raise JobError("The file name has no letters or digits to name the survey by.")
    return name


def source_for(survey: str) -> Path:
    """The questionnaire behind a survey: an upload first, else the corpus."""
    for folder in (UPLOADS, CORPUS):
        path = folder / f"{survey}.docx"
        if path.exists():
            return path
    raise JobError(f"No questionnaire found for {survey}. Upload it again.")


def _command(survey: str, agent: int, sid: str | None, base: str | None,
             headed: bool) -> list[str]:
    run = f"out/{survey}"
    python = [sys.executable, "-m"]
    if agent == 1:
        return [*python, "src.agents.qre_interpretation.orchestrator",
                str(source_for(survey).relative_to(REPO_ROOT))]
    if agent == 2:
        return [*python, "src.agents.survey_builder.build", run]
    if agent == 3:
        lss = agent2_lss(OUT_ROOT / survey).relative_to(REPO_ROOT)
        return [*python, "src.agents.test_design.run", run, "--lss", str(lss)]
    if agent == 4:
        command = [*python, "src.agents.respondent_bot.run_browser", run, "--sid", str(sid)]
        if base:
            command += ["--base", base]
        if headed:
            command.append("--headed")
        return command
    return [*python, "src.agents.qa_adjudication.adjudicate", run]


def _work(job: Job, sid: str | None, base: str | None, headed: bool) -> None:
    log_path = OUT_ROOT / job.survey / LOG
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    with log_path.open("w", encoding="utf-8") as log:
        for step in job.steps:
            if job.stop_requested:
                step.status = "stopped"
                continue
            try:
                command = _command(job.survey, step.agent, sid, base, headed)
            except JobError as error:
                log.write(f"\n{error}\n")
                step.status = "failed"
                break
            log.write(f"\n=== Agent {step.agent}: {AGENT_NAMES[step.agent]} ===\n"
                      f"$ {' '.join(command[1:])}\n\n")
            log.flush()
            step.status = "running"
            job.process = subprocess.Popen(
                command, cwd=REPO_ROOT, env=env, stdout=log,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            step.exit_code = job.process.wait()
            job.process = None
            if job.stop_requested:
                step.status = "stopped"
                log.write("\nStopped.\n")
                continue
            if step.exit_code == 0:
                step.status = "done"
            elif step.exit_code in CARRY_ON.get(step.agent, set()):
                step.status = "flagged"
            else:
                step.status = "failed"
                log.write(f"\nAgent {step.agent} stopped with exit code {step.exit_code}. "
                          "The agents after it were not run.\n")
                break
        for step in job.steps:
            if step.status == "waiting":
                step.status = "stopped" if job.stop_requested else "skipped"
    job.finished = time.time()


def check_key() -> None:
    """Refuse to read a questionnaire without the model's key.

    Without it Agent 1 still finishes, reading only what code can read and
    skipping every line that needs the model, which is easy to miss in a
    finished run.
    """
    from src.common.llm import groq_client
    groq_client._load_env()
    if not os.environ.get("GROQ_API_KEY"):
        raise JobError("Reading a questionnaire needs the Groq key. Add GROQ_API_KEY to .env "
                       "at the repository root, then try again.")


def check_survey(sid: str, base: str | None) -> None:
    """Refuse a bot run that could only fail.

    A wrong address or survey id would otherwise block every test and replace
    the last real results with nothing, so LimeSurvey is asked first whether
    the survey is there and active. Opening the first page records no answer.
    """
    base = (base or "http://localhost:8080").rstrip("/")
    url = f"{base}/index.php/{sid}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            page = response.read().decode("utf-8", errors="replace").lower()
    except urllib.error.HTTPError as error:
        raise JobError(f"LimeSurvey answered {error.code} for {url}. Check the address.") from error
    except (urllib.error.URLError, OSError) as error:
        raise JobError(f"Cannot reach LimeSurvey at {base}. Check the address, "
                       "and that LimeSurvey is running.") from error
    if "survey does not exist" in page:
        raise JobError(f"LimeSurvey has no survey {sid}. Check the survey id.")
    if "survey is not active" in page or "survey is currently not active" in page:
        raise JobError(f"Survey {sid} is not active yet. Activate it in LimeSurvey first.")


def start(survey: str, agents: list[int], sid: str | None = None,
          base: str | None = None, headed: bool = False) -> Job:
    """Start a chain of agents for one survey, unless one is already running."""
    if not agents or any(a not in AGENT_NAMES for a in agents):
        raise JobError("Choose which agents to run, numbered 1 to 5.")
    if 4 in agents and not (sid and str(sid).strip().isdigit()):
        raise JobError("The bot needs the survey's id from LimeSurvey, a number.")
    if 4 in agents:
        check_survey(str(sid).strip(), base)
    if 1 in agents:
        check_key()
    with _lock:
        current = _jobs.get(survey)
        if current and current.running:
            raise JobError("This survey is already running. Wait for it, or stop it.")
        (OUT_ROOT / survey).mkdir(parents=True, exist_ok=True)
        job = Job(survey, [Step(a) for a in sorted(agents)])
        _jobs[survey] = job
    threading.Thread(target=_work, args=(job, sid, base, headed), daemon=True).start()
    return job


def status(survey: str) -> dict | None:
    job = _jobs.get(survey)
    return job.view() if job else None


def running() -> list[str]:
    return [name for name, job in _jobs.items() if job.running]


def stop(survey: str) -> None:
    job = _jobs.get(survey)
    if not job or not job.running:
        return
    job.stop_requested = True
    if job.process:
        job.process.terminate()


def save_upload(filename: str, content: bytes) -> str:
    """Keep an uploaded questionnaire and return the survey name it runs under."""
    if Path(filename).suffix.lower() != ".docx":
        raise JobError("Upload a Word file (.docx), in the questionnaire format.")
    if not content.startswith(b"PK"):
        raise JobError("That file is not a readable .docx.")
    name = safe_name(filename)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    (UPLOADS / f"{name}.docx").write_bytes(content)
    return name
