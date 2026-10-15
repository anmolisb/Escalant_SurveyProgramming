import type { ReactNode } from "react";

/** A status is useful at a glance only if it is coloured by what it means.
 *  Green: nothing to do. Red: a respondent would notice. Amber: unproven or
 *  waiting on someone. Blue: a question rather than a fault. */
const TONES: Record<string, string[]> = {
  ok: ["PASSED", "WORKING", "CONFORMS", "BUILT"],
  bad: ["FAILED", "BROKEN", "SURVEY_DEFECT", "NOT_CONFORMANT"],
  warn: ["NOT PROVEN", "BLOCKED", "SPECIFICATION_ERROR", "NOT_BUILT_YET", "UNDECIDED", "HARNESS_FAULT"],
  info: ["INCONCLUSIVE", "SKIPPED", "UNSETTLED_QUESTION", "TEST_MODEL_GAP", "COVERAGE_GAP", "NEEDS_SAMPLE"],
};

export function tone(value: string): string {
  const upper = String(value).toUpperCase();
  for (const [name, words] of Object.entries(TONES)) {
    if (words.some((w) => upper.includes(w))) return name;
  }
  return "";
}

export const sentence = (value: unknown) => {
  const text = String(value ?? "").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
};

export const words = (code: string) => sentence(code.replace(/_/g, " ").toLowerCase());

export function Pill({ children, kind }: { children: ReactNode; kind?: string }) {
  const value = String(children);
  return <span className={`pill ${kind ?? tone(value)}`}>{children}</span>;
}

export function Section({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="sect">
      <h2>{title}</h2>
      {children && <p>{children}</p>}
    </div>
  );
}

/** An empty screen says what to do next, not merely that it is empty. */
export function Empty({ title, children, then }: { title: string; children: ReactNode; then?: string }) {
  return (
    <div className="empty">
      <div className="t">{title}</div>
      <div className="b">{children}</div>
      {then && <div className="then">{then}</div>}
    </div>
  );
}

export type Cell = { label: string; value: string; tone?: string; sub?: string; small?: boolean };

export function Strip({ cells }: { cells: Cell[] }) {
  return (
    <div className="strip">
      {cells.map((c) => (
        <div className={`cell ${c.tone ?? ""}`} key={c.label}>
          <div className="k">{c.label}</div>
          <div className={`v ${c.small ? "small" : ""}`}>{c.value}</div>
          {c.sub && <div className="sub">{c.sub}</div>}
        </div>
      ))}
    </div>
  );
}

/** A journey drawn as a line with a station for each question, ending at the
 *  terminus the respondent reaches. */
export function Track({ stops, ending, toneOf }: {
  stops: string[];
  ending: string;
  toneOf?: (stop: string) => string;
}) {
  return (
    <ol className="line">
      {stops.map((q, i) => (
        <li key={`${q}-${i}`} className={`station ${toneOf ? toneOf(q) : ""}`}>
          <span className="pin" />
          <span className="stn">{q}</span>
        </li>
      ))}
      <li className="station terminus">
        <span className="pin" />
        <span className="stn">{ending}</span>
      </li>
    </ol>
  );
}

export const kb = (bytes: number) => `${Math.max(1, Math.round(bytes / 1024))} KB`;
