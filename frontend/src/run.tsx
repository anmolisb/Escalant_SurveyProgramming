import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job, type RunRequest } from "./api";

/** The survey's current or last run, polled while it is running. Calls
 *  `onFinish` once when a run ends, so the page can show the new results. */
export function useJob(name: string, onFinish: () => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;
  const wasRunning = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const next = await api.job(name);
      setJob(next);
      if (wasRunning.current && next && !next.running) finishRef.current();
      wasRunning.current = !!next?.running;
    } catch { /* the next poll tries again */ }
  }, [name]);

  useEffect(() => {
    wasRunning.current = false;
    setJob(null);
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!job?.running) return;
    const timer = window.setInterval(refresh, 1500);
    return () => window.clearInterval(timer);
  }, [job?.running, refresh]);

  const start = async (request: RunRequest) => {
    setError(null);
    try {
      const started = await api.start(name, request);
      wasRunning.current = true;
      setJob(started);
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const stop = async () => { await api.stop(name); refresh(); };

  return { job, error, start, stop, clearError: () => setError(null) };
}

const STEP_LABEL: Record<string, string> = {
  waiting: "waiting", running: "running", done: "done", flagged: "done, with checks to read",
  failed: "stopped with an error", stopped: "stopped", skipped: "not run",
};

function elapsed(job: Job): string {
  const seconds = Math.round(((job.finished ?? Date.now() / 1000) - job.started));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

/** What is running now, step by step, with what it prints. */
export function RunPanel({ job, onStop }: { job: Job; onStop: () => void }) {
  const [open, setOpen] = useState(job.running);
  const log = useRef<HTMLPreElement>(null);
  useEffect(() => { if (job.running) setOpen(true); }, [job.running]);
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [job.log, open]);

  const failed = job.steps.some((s) => s.status === "failed");
  const state = job.running ? "running" : failed ? "bad" : "ok";
  const headline = job.running
    ? `Running: ${job.steps.find((s) => s.status === "running")?.name ?? "starting"}`
    : failed ? "The last run stopped with an error" : "The last run finished";

  return (
    <section className={`runpanel ${state}`} aria-live="polite">
      <div className="rp-head">
        <div>
          <div className="rp-title">{job.running && <span className="spinner" aria-hidden />}{headline}</div>
          <div className="muted">{elapsed(job)}{job.running ? " so far" : ""}</div>
        </div>
        <div className="btn-row">
          <button className="btn" onClick={() => setOpen(!open)}>{open ? "Hide output" : "Show output"}</button>
          {job.running && <button className="btn" onClick={onStop}>Stop</button>}
        </div>
      </div>
      <ol className="rp-steps">
        {job.steps.map((s) => (
          <li key={s.agent} className={s.status}>
            <span className="rp-dot" aria-hidden />
            <span><b>{s.name}</b> <span className="muted">{STEP_LABEL[s.status] ?? s.status}</span></span>
          </li>
        ))}
      </ol>
      {open && <pre className="log" ref={log}>{job.log || "Starting…"}</pre>}
    </section>
  );
}
