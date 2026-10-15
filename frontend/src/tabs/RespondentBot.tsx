import type { ReactNode } from "react";
import type { RunDetail } from "../api";
import { Empty, Pill, Section, Strip } from "../ui";

/** Shows the last run. The controls that start one are passed in by the app. */
export function RespondentBot({ run, controls }: { run: RunDetail; controls?: ReactNode }) {
  const results = run.results;
  return (
    <>
      <Section title="Running the tests against the real survey">
        The bot answers as a respondent would, one fresh session per test, and records what it saw. It does not
        decide what a failure means; that is the next tab.
      </Section>
      {!run.survey_file ? (
        <Empty title="Nothing to run against" then="Build the survey, step 2 in the sidebar">
          The tests need a live survey. Build the .lss, import it into LimeSurvey and activate it first.
        </Empty>
      ) : !run.stages.designed ? (
        <Empty title="No tests to run" then="Design the tests, step 3 in the sidebar">
          The designer has not produced a test package for this run.
        </Empty>
      ) : (
        controls
      )}

      {results ? <ResultsView results={results} /> : run.stages.designed && (
        <p className="caption">
          {run.stale.includes("ran")
            ? "The last run was against older tests, so it is not shown. Run the tests again above."
            : "No run yet. Import the survey into LimeSurvey, then run the tests above."}
        </p>
      )}
    </>
  );
}

function ResultsView({ results }: { results: NonNullable<RunDetail["results"]> }) {
  const c = results.counts;
  const total = Object.values(c).reduce((a, b) => a + b, 0);
  const couldNot = (c.BLOCKED ?? 0) + (c.SKIPPED ?? 0);
  const inconclusive = c.INCONCLUSIVE ?? 0;
  const rows = [...results.results].sort((a, b) => (a.order || 9999) - (b.order || 9999));
  return (
    <>
      <Strip cells={[
        { label: "Tests run", value: String(total) },
        { label: "Passed", value: String(c.PASSED ?? 0), tone: "ok" },
        { label: "Failed", value: String(c.FAILED ?? 0), tone: c.FAILED ? "bad" : "idle" },
        { label: "Inconclusive", value: String(inconclusive), tone: inconclusive ? "warn" : "idle" },
        { label: "Could not run", value: String(couldNot), tone: couldNot ? "warn" : "idle" },
        { label: "Last run", value: (results.run_at ?? "").slice(0, 16).replace("T", " "), tone: "idle", small: true },
      ]} />
      <p className="caption">
        Passed, failed, inconclusive and could not run add up to the tests run. Inconclusive means the bot cannot yet
        observe what the test claims. Could not run means it never finished its journey, or needs several
        respondents. Neither says anything about the survey.
      </p>
      <div className="tblwrap" style={{ maxHeight: "62vh" }}>
        <table className="tbl">
          <thead><tr><th style={{ width: "9%" }}>Test</th><th style={{ width: "7%" }}>Question</th><th style={{ width: "36%" }}>What was tested</th><th style={{ width: "11%" }}>Outcome</th><th>What the bot saw</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.test_id}>
                <td className="code">{r.case_id || r.test_id}</td>
                <td className="code">{r.question || "–"}</td>
                <td>{r.title}</td>
                <td><Pill>{r.status}</Pill></td>
                <td>{r.checks.filter((k) => k.matched === false).map((k) => k.actually).join(" ") || r.blocked_reason || "what was expected"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
