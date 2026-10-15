// What the backend returns. Shapes follow src/api/views.py.

export type Stages = {
  interpreted: boolean;
  built: boolean;
  designed: boolean;
  ran: boolean;
  judged: boolean;
};

export type RunSummary = {
  name: string;
  code: string;
  title: string;
  description: string | null;
  tier: string;
  modified: number;
  stages: Stages;
  tests: number | null;
  passed: number | null;
  journeys: number | null;
  working: number | null;
};

export type Question = {
  id: string;
  type: string;
  display: boolean;
  wording: string;
  options: string[];
  shown_if: string | null;
};

export type Rule = {
  id: string;
  action: string;
  destination: string | null;
  condition: string | null;
  reading: string | null;
};

export type Path = {
  path_id: string;
  name: string;
  route_class: string;
  sequence: string[];
  disposition: string | null;
  rules_exercised: string[];
  skipped: string[];
  scenario: string | null;
  why_selected: string;
  what_it_adds: string;
};

export type Design = {
  logical_tests: number;
  executable_tests: number;
  coverage_floor_pct: number;
  coverage_vector: Record<string, string>;
  conformance_verdict: string;
  compilation_refused: number;
  specification_replay: string;
};

export type PathsReport = {
  paths_selected?: number;
  branch_states_total?: number;
  branch_states_covered?: number;
  branch_states_shadowed?: { question: string; guard?: string; shadowed_by?: string; finding: string }[];
};

export type Check = { kind: string; matched: boolean | null; actually: string };

export type TestResult = {
  test_id: string;
  case_id: string;
  order: number;
  question: string;
  title: string;
  status: string;
  checks: Check[];
  blocked_reason: string;
};

export type Results = { run_at: string; counts: Record<string, number>; results: TestResult[] };

export type Journey = {
  path_id: string;
  name: string;
  status: string;
  tests: number;
  passed: number;
  broke_at: string;
  first_failure: string;
};

export type Group = {
  cause: string;
  owner: string;
  question: string;
  tests: string[];
  means: string;
  to_fix: string;
};

export type Judgement = { question: string; cause: string; path_id: string };

export type Findings = { journeys: Journey[]; groups: Group[]; judgements: Judgement[] };

export type RunDetail = {
  name: string;
  code: string;
  title: string;
  description: string | null;
  tier: string;
  stages: Stages;
  stale: (keyof Stages)[];
  questions: Question[];
  rules: Rule[];
  survey_file: { name: string; size: number } | null;
  design: Design | null;
  paths_report: PathsReport;
  paths: Path[];
  review: string | null;
  results: Results | null;
  findings: Findings | null;
};

export type FileGroup = { label: string; files: { path: string; name: string; size: number }[] };

export type Graph = { svg: string; nodes: number; edges: number; endings: number };

export type JobStep = { agent: number; name: string; status: string; exit_code: number | null };

export type Job = {
  survey: string;
  running: boolean;
  started: number;
  finished: number | null;
  steps: JobStep[];
  log: string;
};

export type RunRequest = { agents: number[]; sid?: string; base?: string; headed?: boolean };

async function get<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

/** A request that changes something. The server's reason is passed on as the error. */
async function send<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, { method: "POST", ...init });
  if (!response.ok) {
    const text = await response.text();
    let reason = text;
    try { reason = JSON.parse(text).detail ?? text; } catch { /* plain text */ }
    throw new Error(reason);
  }
  return response.json() as Promise<T>;
}

const run = (name: string) => `/api/runs/${encodeURIComponent(name)}`;

export const api = {
  runs: () => get<RunSummary[]>("/api/runs"),
  run: (name: string) => get<RunDetail>(run(name)),
  graph: (name: string, vertical: boolean) => get<Graph>(`${run(name)}/graph?vertical=${vertical}`),
  files: (name: string) => get<FileGroup[]>(`${run(name)}/files`),
  journeySvg: (name: string, id: string) => `${run(name)}/journeys/${encodeURIComponent(id)}.svg`,
  fileUrl: (name: string, path: string) => `${run(name)}/file?path=${encodeURIComponent(path)}`,
  zipUrl: (name: string) => `${run(name)}/zip`,
  job: (name: string) => get<Job | null>(`${run(name)}/job`),
  running: () => get<string[]>("/api/running"),
  upload: (file: File) =>
    send<{ name: string }>(`/api/upload?filename=${encodeURIComponent(file.name)}`, { body: file }),
  start: (name: string, request: RunRequest) =>
    send<Job>(`${run(name)}/run`, { body: JSON.stringify(request), headers: { "Content-Type": "application/json" } }),
  stop: (name: string) => send<unknown>(`${run(name)}/stop`, {}),
};
