import type { ReactNode } from "react";
import { api, type Journey, type Path, type RunDetail } from "../api";
import { Empty, Pill, Section, Strip, Track, words } from "../ui";

/** Causes a respondent could actually run into. A gap in our own tests should
 *  not paint a journey red. */
const REAL = new Set(["SURVEY_DEFECT", "SPECIFICATION_ERROR", "NOT_BUILT_YET"]);

function Route({ path, verdict, troubleAt }: { path: Path; verdict: Journey; troubleAt: Map<string, string> }) {
  const status = verdict.status || "NOT PROVEN";
  const klass = status === "WORKING" ? "working" : status === "BROKEN" ? "broken" : "unproven";
  return (
    <div className={`route ${klass}`}>
      <div className="head">
        <span className="rid">{path.path_id}</span>
        <span className="rname">{path.name}</span>
        <Pill>{status}</Pill>
        <span className="rmeta">{verdict.passed} of {verdict.tests} checks passed</span>
      </div>
      <Track
        stops={path.sequence}
        ending={path.disposition ?? "COMPLETE"}
        toneOf={(q) => (troubleAt.get(q) === "real" ? "fail" : troubleAt.get(q) ? "unproven" : "")}
      />
      {verdict.broke_at && (
        <div className="why">
          {status === "BROKEN" ? "First came unstuck at" : "Could not be proved at"} <b>{verdict.broke_at}</b>:{" "}
          {verdict.first_failure}
        </div>
      )}
    </div>
  );
}

export function QCReport({ run, controls }: { run: RunDetail; controls?: ReactNode }) {
  const findings = run.findings;
  return (
    <>
      <Section title="What it all means">
        A failing test is not a defect. It may be the survey, a misreading of the questionnaire, something not built
        yet, or a gap in the tests themselves. Telling those apart needs the whole run.
      </Section>
      {!run.stages.ran ? (
        <Empty title="No run to judge yet" then="Run the tests on the previous tab">
          The adjudicator reads a completed run and decides what each failure means and who should act on it.
        </Empty>
      ) : controls}

      {findings && <FindingsView run={run} findings={findings} />}
    </>
  );
}

function FindingsView({ run, findings }: { run: RunDetail; findings: NonNullable<RunDetail["findings"]> }) {
  const journeys = findings.journeys;
  const working = journeys.filter((j) => j.status === "WORKING").length;
  const broken = journeys.filter((j) => j.status === "BROKEN").length;
  const real = findings.groups.filter((g) => REAL.has(g.cause)).length;
  // Each journey is coloured by its own tests only, so one journey's trouble at
  // a question does not mark that question on every other journey.
  const troubleBy = new Map<string, Map<string, string>>();
  for (const j of findings.judgements) {
    if (!j.question || !j.path_id) continue;
    const at = troubleBy.get(j.path_id) ?? new Map<string, string>();
    if (REAL.has(j.cause)) at.set(j.question, "real");
    else if (!at.has(j.question)) at.set(j.question, "soft");
    troubleBy.set(j.path_id, at);
  }
  const shapes = new Map(run.paths.map((p) => [p.path_id, p]));
  return (
    <>
      <Strip cells={[
        { label: "Journeys working", value: `${working} of ${journeys.length}`, tone: working === journeys.length ? "ok" : "warn" },
        { label: "A respondent would notice", value: String(broken), tone: broken ? "bad" : "ok" },
        { label: "Things to look at", value: String(findings.groups.length), tone: findings.groups.length ? "warn" : "ok" },
        { label: "Of those, need a fix", value: String(real), tone: real ? "bad" : "ok" },
      ]} />
      <Section title="Can a respondent get through?">One line per journey. Each station is a question the respondent meets; the line ends where the survey sends them.</Section>
      <div className="legend">
        <span><span className="swatch ring" />checked and fine</span>
        <span><span className="swatch dot-bad" />something went wrong here</span>
        <span><span className="swatch dot-warn" />could not be proved here</span>
        <span><span className="swatch end" />where the journey ends</span>
      </div>
      {[...journeys].sort((a, b) => a.path_id.localeCompare(b.path_id)).map((v) => {
        const shape = shapes.get(v.path_id);
        return shape ? <Route key={v.path_id} path={shape} verdict={v} troubleAt={troubleBy.get(v.path_id) ?? new Map()} /> : null;
      })}

      <Section title="What needs correcting">
        Failures sharing a cause and a question appear once. One mistake upstream can fail nine tests.
      </Section>
      {!findings.groups.length ? (
        <div className="banner ok">Nothing. Every test passed.</div>
      ) : (
        <div className="tblwrap">
          <table className="tbl">
            <thead><tr><th style={{ width: "14%" }}>Cause</th><th style={{ width: "7%" }}>Question</th><th style={{ width: "11%" }}>Tests</th><th style={{ width: "14%" }}>Who should act</th><th>What it means</th><th>What to do</th></tr></thead>
            <tbody>
              {findings.groups.map((g, i) => (
                <tr key={i}>
                  <td><Pill>{words(g.cause)}</Pill></td>
                  <td className="code">{g.question}</td>
                  <td className="code">{g.tests.join(", ")}</td>
                  <td>{g.owner}</td>
                  <td>{g.means}</td>
                  <td>{g.to_fix}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p style={{ marginTop: 16 }}>
        <a className="btn primary" href={api.fileUrl(run.name, "agent5/agent5_qc_report.xlsx")}>Download the QC report</a>
      </p>
    </>
  );
}
