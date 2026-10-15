import { useEffect, useState } from "react";
import { api, type RunDetail, type RunRequest, type Stages } from "../api";
import { RunPanel, useJob } from "../run";
import { link } from "../router";
import { Strip } from "../ui";
import { Artifacts } from "../tabs/Artifacts";
import { FlowGraph } from "../tabs/FlowGraph";
import { QCReport } from "../tabs/QCReport";
import { Questions, questionCount } from "../tabs/Questions";
import { RespondentBot } from "../tabs/RespondentBot";
import { Routing } from "../tabs/Routing";
import { SurveyBuilder } from "../tabs/SurveyBuilder";
import { TestDesign } from "../tabs/TestDesign";

const SECTIONS: { id: string; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "questions", label: "Questions" },
  { id: "routing", label: "Routing" },
  { id: "flow", label: "Flow" },
  { id: "survey-file", label: "Survey file" },
  { id: "tests", label: "Tests" },
  { id: "run", label: "Run" },
  { id: "verdict", label: "Verdict" },
  { id: "files", label: "Files" },
];

/** The five stages, in the order they happen. Each reads what the one before wrote. */
const STAGES: { key: keyof Stages; name: string; section: string }[] = [
  { key: "interpreted", name: "Questionnaire", section: "questions" },
  { key: "built", name: "Survey", section: "survey-file" },
  { key: "designed", name: "Tests", section: "tests" },
  { key: "ran", name: "Run", section: "run" },
  { key: "judged", name: "Verdict", section: "verdict" },
];

function verdictOf(run: RunDetail): { text: string; tone: string } | null {
  const js = run.findings?.journeys;
  if (!js) return null;
  const good = js.filter((j) => j.status === "WORKING").length;
  return { text: `${good} of ${js.length} journeys working`, tone: good === js.length ? "ok" : "warn" };
}

function StageLine({ run }: { run: RunDetail }) {
  const next = STAGES.findIndex((s) => !run.stages[s.key]);
  return (
    <ol className="stageline">
      {STAGES.map((s, i) => {
        const done = run.stages[s.key];
        const state = done ? "done" : i === next ? "next" : "todo";
        return (
          <li key={s.key} className={state}>
            <a href={link.survey(run.name, s.section)}>
              <span className="dot">{done ? "✓" : i + 1}</span>
              <span className="label">{s.name}</span>
            </a>
          </li>
        );
      })}
    </ol>
  );
}

const remembered = (key: string, fallback: string) => {
  try { return window.localStorage.getItem(key) ?? fallback; } catch { return fallback; }
};
const remember = (key: string, value: string) => {
  try { window.localStorage.setItem(key, value); } catch { /* not kept; fine */ }
};

/** Agent 4 needs the survey live in LimeSurvey, so it asks where. */
function BotForm({ run, busy, onRun }: { run: RunDetail; busy: boolean; onRun: (r: RunRequest) => void }) {
  const [sid, setSid] = useState(() => remembered(`sid:${run.name}`, ""));
  const [base, setBase] = useState(() => remembered("limesurvey", "http://localhost:8080"));
  const [headed, setHeaded] = useState(false);
  const ready = run.stages.designed && /^\d+$/.test(sid.trim()) && base.trim() !== "";
  const go = () => {
    remember(`sid:${run.name}`, sid.trim());
    remember("limesurvey", base.trim());
    onRun({ agents: [4, 5], sid: sid.trim(), base: base.trim(), headed });
  };
  return (
    <div className="botform">
      <p className="muted">
        First <a href={link.survey(run.name, "survey-file")}>download the survey file</a>, import it into
        LimeSurvey and activate it. Then give its survey id here. Each test submits one response.
      </p>
      <div className="fields">
        <label>Survey id<input inputMode="numeric" value={sid} onChange={(e) => setSid(e.target.value)} placeholder="e.g. 994316" /></label>
        <label className="wide">LimeSurvey address<input value={base} onChange={(e) => setBase(e.target.value)} /></label>
      </div>
      <label className="check"><input type="checkbox" checked={headed} onChange={(e) => setHeaded(e.target.checked)} /> Show the browser while it runs</label>
      <div className="btn-row">
        <button className="btn primary" disabled={!ready || busy} onClick={go}>
          {run.stages.ran ? "Run the tests again" : "Run the tests"}
        </button>
        <span className="muted small">Then explains the results.</span>
      </div>
    </div>
  );
}

type Action = { label: string; again: string; agents: number[]; needs: keyof Stages | null; then?: string };

/** What each stage's button runs: the stage, and every later stage that needs nothing from a person. */
const ACTIONS: (Action | null)[] = [
  { label: "Read the questionnaire", again: "Read it again", agents: [1, 2, 3], needs: null, then: "Then builds the survey and designs the tests." },
  { label: "Build the survey", again: "Build it again", agents: [2, 3], needs: "interpreted", then: "Then designs the tests again." },
  { label: "Design the tests", again: "Design them again", agents: [3], needs: "built" },
  null,
  { label: "Explain the results", again: "Explain them again", agents: [5], needs: "ran" },
];

function Overview({ run, busy, onRun }: { run: RunDetail; busy: boolean; onRun: (r: RunRequest) => void }) {
  const results = run.results?.counts;
  const total = results ? Object.values(results).reduce((a, b) => a + b, 0) : 0;
  const verdict = verdictOf(run);
  const blocks = [
    {
      done: run.stages.interpreted,
      title: "The questionnaire is read",
      body: "The document is turned into a specification: every question, option, rule and ending, each traced back to where it came from.",
      fact: run.stages.interpreted ? `${questionCount(run.questions)} and ${run.rules.length} routing rules` : "Not read yet",
      go: "questions", goLabel: "See the questions",
    },
    {
      done: run.stages.built,
      title: "The survey is built",
      body: "The specification becomes a LimeSurvey file, ready to import.",
      fact: run.survey_file ? "Survey file ready to download" : "Not built yet",
      go: "survey-file", goLabel: "Get the survey file",
    },
    {
      done: run.stages.designed,
      title: "Tests are designed",
      body: "Every distinct route a respondent can take is worked out, and each behaviour the questionnaire claims gets a test.",
      fact: run.design ? `${run.design.logical_tests} tests across ${run.paths_report.paths_selected ?? run.paths.length} journeys` : "Not designed yet",
      go: "tests", goLabel: "See the tests",
    },
    {
      done: run.stages.ran,
      title: "The tests are run",
      body: "A bot answers the live survey as a respondent would, one fresh session per test, and records what it saw.",
      fact: results ? `${results.PASSED ?? 0} of ${total} passed`
        : run.stale.includes("ran") ? "The last run was against older tests. Run the tests again." : "Not run yet",
      go: "run", goLabel: "See the results",
    },
    {
      done: run.stages.judged,
      title: "The results are explained",
      body: "Each test that did not pass gets one cause and one owner, so a gap in the tests is never mistaken for a broken survey.",
      fact: verdict ? verdict.text : "Not judged yet",
      go: "verdict", goLabel: "Read the verdict",
    },
  ];
  const asked = run.questions.filter((q) => !q.display).length;
  return (
    <>
    <Strip cells={[
      { label: "Questions", value: run.stages.interpreted ? String(asked) : "\u2013", tone: run.stages.interpreted ? "ok" : "idle" },
      { label: "Routing rules", value: run.stages.interpreted ? String(run.rules.length) : "\u2013", tone: run.stages.interpreted ? "ok" : "idle" },
      { label: "Tests designed", value: run.design ? String(run.design.logical_tests) : "\u2013", tone: run.design ? "ok" : "idle" },
      { label: "Tests passed", value: results ? `${results.PASSED ?? 0} of ${total}` : "\u2013", tone: !results ? "idle" : (results.PASSED ?? 0) === total ? "ok" : "warn" },
      { label: "Journeys working", value: verdict ? verdict.text.replace(" journeys working", "") : "\u2013", tone: verdict ? verdict.tone : "idle" },
    ]} />
    <ol className="overview">
      {blocks.map((b, i) => (
        <li key={b.title} className={b.done ? "done" : ""}>
          <span className="num">{i + 1}</span>
          <div>
            <h3>{b.title}</h3>
            <p>{b.body}</p>
            <p className="fact">{b.fact}</p>
            <div className="stage-actions">
              {b.done && <a className="textlink" href={link.survey(run.name, b.go)}>{b.goLabel}</a>}
              {ACTIONS[i] && (() => {
                const a = ACTIONS[i]!;
                const blocked = a.needs !== null && !run.stages[a.needs];
                return (
                  <span className="btn-row">
                    <button className={`btn ${b.done ? "" : "primary"}`} disabled={busy || blocked}
                      onClick={() => onRun({ agents: a.agents })}>{b.done ? a.again : a.label}</button>
                    {a.then && <span className="muted small">{a.then}</span>}
                  </span>
                );
              })()}
            </div>
            {i === 3 && <BotForm run={run} busy={busy} onRun={onRun} />}
          </div>
        </li>
      ))}
    </ol>
    </>
  );
}

export function Survey({ name, section }: { name: string; section: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api.run(name).then(setRun).catch((e) => setError(String(e.message)));
  useEffect(() => {
    setRun(null);
    setError(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);
  const { job, error: runError, start, stop, clearError } = useJob(name, load);
  // Show each agent's output as soon as it lands, not only at the end.
  const doneSteps = job?.steps.filter((s) => s.status === "done" || s.status === "flagged").length ?? 0;
  useEffect(() => { if (job?.running && doneSteps) load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [doneSteps]);
  const busy = !!job?.running;
  const onRun = (request: RunRequest) => {
    start(request);
    window.scrollTo(0, 0);
  };

  if (error) {
    return (
      <div className="page">
        <p className="notice bad">There is no survey called {name}.</p>
        <a className="textlink" href={link.home}>Back to all surveys</a>
      </div>
    );
  }
  if (!run) return <div className="page"><p className="muted">Loading…</p></div>;

  const current = SECTIONS.some((s) => s.id === section) ? section : "overview";
  const verdict = verdictOf(run);

  return (
    <div className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <a href={link.home}>All surveys</a>
      </nav>
      <header className="survey-head">
        <h1>{run.title}</h1>
        {run.description && <p className="lede">{run.description}</p>}
        <div className="headline-row">
          <StageLine run={run} />
          {verdict && <p className={`verdict ${verdict.tone}`}>{verdict.text}</p>}
        </div>
      </header>

      {runError && (
        <p className="notice bad">{runError} <button className="linkbtn" onClick={clearError}>Dismiss</button></p>
      )}
      {job && <RunPanel job={job} onStop={stop} />}

      <div className="survey-body">
        <nav className="sidemenu" aria-label="Sections">
          <ul>
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a href={link.survey(run.name, s.id)} aria-current={s.id === current ? "page" : undefined}>{s.label}</a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="content">
          {current === "overview" && <Overview run={run} busy={busy} onRun={onRun} />}
          {current === "questions" && <Questions questions={run.questions} />}
          {current === "routing" && <Routing rules={run.rules} />}
          {current === "flow" && <FlowGraph run={run.name} />}
          {current === "survey-file" && <SurveyBuilder run={run} />}
          {current === "tests" && <TestDesign run={run} />}
          {current === "run" && <RespondentBot run={run} controls={<BotForm run={run} busy={busy} onRun={onRun} />} />}
          {current === "verdict" && <QCReport run={run} />}
          {current === "files" && <Artifacts run={run.name} />}
        </div>
      </div>
    </div>
  );
}
