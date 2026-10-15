import { useEffect, useState } from "react";
import { api, type RunSummary, type Stages } from "../api";
import { link } from "../router";

const STAGE_KEYS: (keyof Stages)[] = ["interpreted", "built", "designed", "ran", "judged"];
const STAGE_NAMES = ["Questionnaire read", "Survey built", "Tests designed", "Tests run", "Verdict"];

/** Simplest first, so the list reads from short surveys to long ones. */
const TIER_ORDER = ["Simple", "Moderate", "Complex", "Other"];

export function StageMarks({ stages }: { stages: Stages }) {
  return (
    <span className="marks" aria-label="Stages complete">
      {STAGE_KEYS.map((k, i) => (
        <span key={k} className={`mark ${stages[k] ? "filled" : ""}`} title={`${STAGE_NAMES[i]}: ${stages[k] ? "done" : "not yet"}`} />
      ))}
    </span>
  );
}

function Outcome({ run }: { run: RunSummary }) {
  if (run.journeys == null) {
    const done = STAGE_KEYS.filter((k) => run.stages[k]).length;
    return <span className="outcome muted">{done ? STAGE_NAMES[done - 1] : "Not started"}</span>;
  }
  const all = run.working === run.journeys;
  return (
    <span className="outcome">
      <span className={all ? "ok" : "warn"}>{run.working} of {run.journeys} journeys working</span>
      <span className="muted">{run.passed} of {run.tests} tests passed</span>
    </span>
  );
}

export function Home() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<string[]>([]);
  useEffect(() => {
    api.runs().then(setRuns).catch((e) => setError(String(e.message)));
    api.running().then(setRunning).catch(() => setRunning([]));
  }, []);

  const sorted = [...(runs ?? [])].sort((a, b) =>
    TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier) || a.name.localeCompare(b.name));

  return (
    <div className="page">
      <section className="hero">
        <h1>Check a survey against its questionnaire.</h1>
        <p className="lede">
          Give it a questionnaire requirement document. It reads the document, builds the survey in LimeSurvey,
          answers it the way respondents would, and tells you where the survey and the questionnaire disagree.
        </p>
        <div className="hero-actions">
          <a className="button" href={link.new}>Check a questionnaire</a>
          <a className="button quiet" href="#surveys">Open a survey</a>
          <a className="button quiet" href={link.how}>How it works</a>
        </div>
      </section>

      <section id="surveys" className="library">
        <h2>Surveys</h2>
        {error && <p className="notice bad">The app cannot reach its server: {error}. Start it with python -m src.api.server.</p>}
        {!runs && !error && <p className="muted">Loading surveys…</p>}
        <ul className="runs">
          {sorted.map((r) => (
            <li key={r.name}>
              <a className="run-row" href={link.survey(r.name)}>
                <span className="what">
                  <span className="name">{r.title}</span>
                  {r.description && <span className="desc">{r.description}</span>}
                </span>
                <StageMarks stages={r.stages} />
                {running.includes(r.name)
                  ? <span className="outcome"><span className="running-tag">Running now</span></span>
                  : <Outcome run={r} />}
              </a>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
