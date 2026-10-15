import { useState } from "react";
import type { Rule } from "../api";
import { Empty, Pill, Section, sentence, Strip } from "../ui";

/** Rules read as sentences, or as the table that shows each condition beside
 *  how it was read. */
export function Routing({ rules }: { rules: Rule[] }) {
  const [view, setView] = useState<"sentences" | "table">("sentences");
  if (!rules.length) {
    return <Empty title="No routing rules">This questionnaire has no skips or screen-outs, so every respondent sees every question.</Empty>;
  }
  return (
    <>
      <Section title="Where the survey sends people">
        {rules.length} rules. Each reads as a sentence: when this is true, do that.
      </Section>
      <Strip cells={[
        { label: "Rules", value: String(rules.length) },
        { label: "Screen-outs", value: String(rules.filter((r) => r.action === "terminate").length) },
        { label: "Show or skip", value: String(rules.filter((r) => r.action === "show" || r.action === "skip").length) },
        { label: "Refuse an answer", value: String(rules.filter((r) => r.action === "reject").length) },
        { label: "Not read", value: String(rules.filter((r) => !r.reading).length), tone: rules.some((r) => !r.reading) ? "warn" : "idle",
          sub: "left for a person" },
      ]} />
      <div className="toggle-row">
        <button className={`btn ${view === "sentences" ? "primary" : ""}`} onClick={() => setView("sentences")}>Sentences</button>
        <button className={`btn ${view === "table" ? "primary" : ""}`} onClick={() => setView("table")}>Table</button>
      </div>
      {view === "sentences" ? (
        rules.map((r) => (
          <div className="rule" key={r.id}>
            <span className="rid">{r.id}</span>
            <span>when {r.condition ?? "(not stated)"}</span>
            <span className="arrow">{"→"}</span>
            <span className="act">{sentence(r.action)}{r.destination ? ` ${r.destination}` : ""}</span>
          </div>
        ))
      ) : (
        <div className="tblwrap">
          <table className="tbl">
            <thead><tr><th style={{ width: "7%" }}>Rule</th><th style={{ width: "30%" }}>Condition, as written</th><th style={{ width: "30%" }}>How it was read</th><th style={{ width: "12%" }}>Action</th><th>Goes to</th></tr></thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id}>
                  <td className="code">{r.id}</td>
                  <td>{r.condition}</td>
                  <td className="code">{r.reading ?? <span className="warn">not read, left for a person</span>}</td>
                  <td><Pill>{sentence(r.action)}</Pill></td>
                  <td className="code">{r.destination}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
