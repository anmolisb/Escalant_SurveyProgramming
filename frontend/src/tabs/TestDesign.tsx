import { marked } from "marked";
import { api, type RunDetail } from "../api";
import { Empty, Section, Strip, words } from "../ui";

/** The nine kinds of behaviour a survey can get wrong, in words. */
const DIMENSIONS: Record<string, string> = {
  D1: "Showing, hiding and flow", D2: "Endings", D3: "Answer rules", D4: "Compulsory questions",
  D5: "Carried-forward options", D6: "Carried-forward wording", D7: "Shuffled questions",
  D8: "Quotas", D9: "Combinations",
};

function Meter({ label, raw }: { label: string; raw: string }) {
  // "15/15 (100.0%) EXHAUSTIVE"
  const match = raw.match(/^(\d+)\/(\d+).*?\)\s*(.*)$/);
  if (!match) return null;
  const [got, total, status] = [Number(match[1]), Number(match[2]), match[3]];
  const pct = total ? (got / total) * 100 : 0;
  const fill = pct >= 100 ? "" : pct >= 50 ? "warn" : "bad";
  return (
    <div className="meter">
      <div className="label">{label}</div>
      <div className="track"><div className={`fill ${fill}`} style={{ width: `${pct}%` }} /></div>
      <div className="val">{got}<span>/{total}</span></div>
      <div className="stat">{status.toLowerCase()}</div>
    </div>
  );
}

export function TestDesign({ run }: { run: RunDetail }) {
  const design = run.design;
  const report = run.paths_report;
  if (!run.survey_file) {
    return <Empty title="Waiting on the survey file" then="Build the survey first, step 2 in the sidebar">
      Tests can be designed without it, but none would be runnable: there would be no field to bind an answer to.
    </Empty>;
  }
  if (!design) {
    return <Empty title="No tests designed yet" then="Run Test Designer, step 3 in the sidebar">
      The designer works out every distinct journey through the survey and writes a test for each behaviour the
      questionnaire claims.
    </Empty>;
  }
  const shadowed = report.branch_states_shadowed ?? [];
  return (
    <>
      <Section title="What will be tested">
        The designer works out every distinct journey through the survey and writes a test for each behaviour the
        questionnaire claims. It never opens the survey; that comes next.
      </Section>
      <Strip cells={[
        { label: "Journeys", value: String(report.paths_selected ?? "–") },
        { label: "Test cases", value: String(design.logical_tests) },
        { label: "Runnable", value: String(design.executable_tests) },
        { label: "Branch states", value: `${report.branch_states_covered ?? "–"}/${report.branch_states_total ?? "–"}` },
        { label: "Weakest reading", value: `${design.coverage_floor_pct}%`, tone: design.coverage_floor_pct >= 100 ? "ok" : "warn" },
      ]} />

      <Section title="Nine kinds of behaviour, counted separately">
        Never added together, because they count different things. The shortest bar is the one to look at.
      </Section>
      <div className="meters">
        {Object.keys(design.coverage_vector).sort().map((k) => (
          <Meter key={k} label={DIMENSIONS[k] ?? k} raw={design.coverage_vector[k]} />
        ))}
      </div>
      <p className="caption">
        Build agrees with the questionnaire: {words(design.conformance_verdict).toLowerCase()} ·{" "}
        {design.compilation_refused} test(s) refused to compile · replayed against the questionnaire's own worked
        examples: {design.specification_replay}
      </p>

      {shadowed.length > 0 && (
        <>
          <Section title="Findings for whoever wrote the questionnaire">
            Rules that say the same thing twice, so one of them can never be observed on its own.
          </Section>
          {shadowed.map((s) => (
            <div className="banner warn" key={s.question}><b>{s.question}</b> {"—"} {s.finding}</div>
          ))}
        </>
      )}

      <Section title="The journeys these tests run on">
        Exclusive, and every branch taken in both directions by at least one of them.
      </Section>
      {run.paths.map((p) => (
        <details className="card" key={p.path_id}>
          <summary>
            <span className="rid">{p.path_id}</span>
            <span className="rname">{p.name}</span>
            {p.scenario && <span className="pill info">acceptance scenario {p.scenario}</span>}
          </summary>
          <div className="body">
            <div className="journey-svg"><img src={api.journeySvg(run.name, p.path_id)} alt={`${p.path_id} flow`} /></div>
            <div className="facts">
              <b>Ends at</b> {p.disposition ?? "COMPLETE"} · <b>Rules exercised</b>{" "}
              {p.rules_exercised?.length ? p.rules_exercised.join(", ") : "none"}
            </div>
            <div className="facts"><b>Why this one.</b> {p.why_selected}</div>
            {p.what_it_adds && <div className="caption">What it adds: {p.what_it_adds}</div>}
            {p.skipped?.length > 0 && <div className="caption">Skipped: {p.skipped.join(", ")}</div>}
          </div>
        </details>
      ))}

      {run.review && (
        <details className="card">
          <summary><span className="rname">Full review</span></summary>
          <div className="body review" dangerouslySetInnerHTML={{ __html: marked.parse(run.review) as string }} />
        </details>
      )}
    </>
  );
}

