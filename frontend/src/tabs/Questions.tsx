import { useState } from "react";
import type { Question } from "../api";
import { Pill, Section, sentence, Strip } from "../ui";

export function questionCount(questions: Question[]): string {
  const shown = questions.filter((q) => q.display).length;
  const asked = questions.length - shown;
  const text = `${asked} question${asked === 1 ? "" : "s"}`;
  return shown ? `${text} + ${shown} message${shown === 1 ? "" : "s"}` : text;
}

function Card({ q }: { q: Question }) {
  if (q.display) {
    return (
      <div className="qcard display">
        <div className="top"><span className="qid">{q.id}</span><Pill kind="info">Display message</Pill></div>
        <div className="text">{q.wording}</div>
        <div className="muted" style={{ fontSize: "0.82rem" }}>Shown to everyone with a Next button. Nothing to answer.</div>
      </div>
    );
  }
  const extra = q.options.length - 8;
  return (
    <div className="qcard">
      <div className="top"><span className="qid">{q.id}</span><Pill>{sentence(q.type)}</Pill></div>
      <div className="text">{q.wording}</div>
      <div className="opts">
        {q.options.slice(0, 8).map((o) => <span className="opt" key={o}>{o}</span>)}
        {extra > 0 && <span className="opt muted">+{extra} more</span>}
      </div>
      {q.shown_if && <div className="guard">Shown only when {q.shown_if}</div>}
    </div>
  );
}

/** Cards read like the questionnaire; the table scans faster. Both are kept. */
export function Questions({ questions }: { questions: Question[] }) {
  const [view, setView] = useState<"cards" | "table">("cards");
  return (
    <>
      <Section title="The questionnaire as the interpreter read it">
        {questionCount(questions)} extracted from the document. Anything shown only under a condition says so.
      </Section>
      <Strip cells={[
        { label: "Questions", value: String(questions.filter((q) => !q.display).length) },
        { label: "Messages", value: String(questions.filter((q) => q.display).length), tone: "idle" },
        { label: "Shown only under a condition", value: String(questions.filter((q) => q.shown_if).length) },
        { label: "Answer options", value: String(questions.reduce((n, q) => n + q.options.length, 0)) },
      ]} />
      <div className="toggle-row">
        <button className={`btn ${view === "cards" ? "primary" : ""}`} onClick={() => setView("cards")}>Cards</button>
        <button className={`btn ${view === "table" ? "primary" : ""}`} onClick={() => setView("table")}>Table</button>
      </div>
      {view === "cards" ? (
        questions.map((q) => <Card q={q} key={q.id} />)
      ) : (
        <div className="tblwrap">
          <table className="tbl">
            <thead><tr><th style={{ width: "7%" }}>ID</th><th style={{ width: "11%" }}>Type</th><th>Question</th><th style={{ width: "8%" }}>Options</th><th style={{ width: "28%" }}>Shown if</th></tr></thead>
            <tbody>
              {questions.map((q) => (
                <tr key={q.id}>
                  <td className="code">{q.id}</td>
                  <td><Pill kind={q.display ? "info" : ""}>{sentence(q.type)}</Pill></td>
                  <td>{q.wording}</td>
                  <td>{q.display ? "" : q.options.length}</td>
                  <td>{q.shown_if ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
