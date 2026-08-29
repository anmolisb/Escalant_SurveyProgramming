# Agent 1 — context

This file did not exist before this entry. Created to record what Agent 1
now does, for whoever picks this up next without the conversation history
that built it.

## Pipeline, as it stands

```
QRE
 → Part 1 (Stages 1–5: ingestion, heading match, transcription, deep parse,
   extraction audit)
 → Part 2 (Stage 6: canonical survey specification)
 → Canonical validation / Agent 1 evaluation (Stage 7)
 → Human decision gate (Stage 7)
 → Graph builder (Stage 8: RouteGraph, DependencyGraph, rule_edge_map)
 → Graph validation (this entry)
 → Agent 3 (not built)
```

Stages 1–8 run automatically on every `python3 src/orchestrator.py <file.docx>`
call. Graph validation, described below, does not - see "Not wired into the
automatic pipeline" at the end of this entry for why and how to run it.

## Graph validation layer — 29 Aug 2026

**What it is.** `src/graph_validate.py`, run by `src/run_graph_validation.py`.
Proves two separate things about the persisted graph in
`part2_route_graph.json`, without a model call and without rebuilding
anything upstream:

- **Structural fidelity** — every question and disposition node, every
  routing/skip/termination edge, every guard, every dependency edge, every
  quota edge and every randomisation attribute is compared field-by-field
  against `part2_canonical.json`. Ten categories (A–J in the task that built
  this), each reported with its own numerator/denominator, never blended
  into one score.
- **Behavioural fidelity** — for every rule whose condition the QRE states
  formally (not prose), a positive and a negative answer state is built from
  the QRE's own options and the *persisted graph's* edge is walked, not the
  canonical condition tree in isolation - Stage 7 already checked that in
  isolation. On top of that, every acceptance scenario in the canonical
  specification that names an expected ending is replayed as a full walk
  from `__START__`, following `rule_precedence: document_order_first_match`
  exactly as the specification already declares it, to confirm the walk
  reaches the ending the QRE itself says it should.

Where a condition is prose, the behavioural test is `UNVERIFIED`, never
guessed at - same rule Stage 7 already follows, applied one layer further
down: a reading nobody has confirmed cannot make the graph "correct" or
"incorrect", only "not yet checkable by this layer alone".

**Verified status, both fixtures, this run:**

| | S01 | C01 |
|---|---|---|
| Structural findings | 0 | 0 |
| Behavioural tests | 13 (13 PASS) | 51 (46 PASS, 5 UNVERIFIED) |
| Structural status | READY | READY |
| Behavioural status | READY | READY_WITH_WARNINGS |
| Overall graph status | READY | READY_WITH_WARNINGS |
| Agent 3 input status | READY | READY |

The 5 UNVERIFIED on C01 are exactly the 3 prose display conditions (Q2, Q3,
Q6) and 2 quota edges, whose behaviour is deliberately never asserted
per-respondent (a quota's fill depends on other respondents' answers, not
this one's - see instruction I in the task that built this). Nothing FAILED
or was BLOCKED on either fixture; the graph builder's own output matches the
canonical specification exactly, everywhere this layer checked.

**Artifacts, per survey, under `out/<stem>/`:**
`part2_graph_validation.json` (machine-readable), `route_graph.graphml`,
`route_graph.gexf`, `dependency_graph.graphml`, `dependency_graph.gexf`
(shareable exports for an external graph tool - GraphML/GEXF cannot hold a
`None` or a list, so these are a sanitised view; `part2_route_graph.json`
stays the lossless source). One shared report: `docs/graph_validation_report.md`.

**What Agent 3 must still read from the canonical specification, never from
the graph** (unchanged from the graph builder's own documented design):
question wording, option labels and message text; every validation bound
(a reject rule is a constraint, not an edge carrying its bound); acceptance
scenarios; study metadata and programming/QA requirements; quota cell
targets and percentages (the graph only says an edge exists and is
stateful); and the human decision register's resolutions - a graph edge
exists whether or not its condition has been confirmed, and the graph alone
cannot say which of its own transitions are still provisional.

**Not wired into the automatic pipeline.** Unlike Stages 7 and 8, this layer
is a standalone, on-demand script (`python3 src/run_graph_validation.py`),
matching how the task that built it framed the shareable exports - "for THIS
RUN ONLY... not a new persistent database architecture." It reads whatever
`part2_canonical.json` and `part2_route_graph.json` already say, so it is
always safe to re-run after any upstream change; it just is not triggered by
`orchestrator.py` automatically the way Stages 7 and 8 are.
