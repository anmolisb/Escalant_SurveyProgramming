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
 → Graph validation (Stage 9)
 → Agent 3 (not built)
```

Stages 1–9 all run automatically on every `python3 src/orchestrator.py
<file.docx>` call. Graph validation - previously a standalone script a person
had to remember to run - became Stage 9 on 29 Aug 2026; see that entry below.

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

**Standalone script preserved.** `python3 src/run_graph_validation.py` still
works exactly as before - reads whatever `part2_canonical.json` and
`part2_route_graph.json` already say, calls no model, safe to re-run any time.
Nothing in `graph_validate.py`, `run_graph_validation.py` or
`tests/test_part2_graph.py` changed when it was wired in below.

## Stage 9 in the automatic pipeline — 29 Aug 2026

Graph validation now runs on every `orchestrator.py` call, right after Stage
8, calling `run_graph_validation.validate()` exactly as the standalone script
does - same function, same artifacts, no model, no Stage 4 rerun. What's new
is `orchestrator.agent3_execution_approval()`, a small function that lives in
`orchestrator.py` alone and touches neither Stage 7's nor Stage 9's own code.

It exists because Stage 9's own verdict answers one question -
**`GRAPH_INPUT_SUFFICIENCY`**: is the graph, together with the canonical
specification, structurally and behaviourally enough for Agent 3 to build
tests from - and that is a *different* question from **whether Agent 3 may
actually proceed**. A graph can be structurally sound, behaviourally correct,
and input-sufficient, while a human decision from Stage 7 is still pending -
and in that case Agent 3 must stay blocked regardless of how clean the graph
is. `agent3_execution_approval()` is the plain AND of three things, computed
after Stage 9 finishes and never inside it:

```
canonical_validation_clear   Stage 7's canonical_status != FAILED
human_decision_gate_clear    Stage 7's human_decision_gate == CLEAR
graph_validation_passed      Stage 9's overall in (READY, READY_WITH_WARNINGS)
                              and agent3_input_status == READY
```

All three required; `APPROVED` only when every one holds. Written to a new,
additive artifact - `agent1_stage9_gate.json` - that sits beside Stage 7's and
Stage 9's own files without editing either of them.

**Verified on both fixtures**, reusing the exact committed Stage 6/7/8/9
content (confirmed byte-identical to what was already on disk, save for
timestamps) - no Stage 4 call, no LLM call:

| | S01 | C01 |
|---|---|---|
| `GRAPH_INPUT_SUFFICIENCY` | READY | READY |
| `AGENT3_EXECUTION_APPROVAL` | **BLOCKED** | **BLOCKED** |
| canonical validation clear | true | true |
| human decision gate clear | **false** | **false** |
| graph validation passed | true | true |
| blocked by | `human_decision_gate=PENDING_BLOCKING_DECISIONS` | same |

Both graphs are sufficient input for Agent 3. Neither is approved to run it
against, because both surveys still have BLOCKING decisions in
`agent1_decisions.json` nobody has resolved - exactly the distinction this
change exists to keep visible rather than let a clean graph quietly paper
over. The 16 tests in `tests/test_part2_graph.py` and all of Stage 9's
existing behavioural/structural results (13 PASS on S01; 46 PASS + 5
UNVERIFIED on C01, none silently turned into a PASS) are unchanged.

**Artifacts added:** `agent1_stage9_gate.json`, per survey under
`out/<stem>/`, alongside the Stage 9 files already listed above.
