# QRE extraction pipeline

DOCX questionnaire requirement document → a structured extraction of what it
says, and a canonical specification of what it means.

Agent 1 has two parts. **Part 1** (stages 1 to 5) reads the document and records
it. **Part 2** (stages 6 and 7) interprets that record into a platform-neutral
survey specification and the graphs built from it. The dividing line matters and
is enforced: Part 1 preserves `Show if: Q5 contains any touchpoint` as text, and
Part 2 is the only place allowed to decide that the operator is `contains_any`.

## Setup

```bash
pip3 install -r requirements.txt
```

`.env` is **tracked in git**, but only ever with a blank key. Put your real key
in it, then run this once so your local copy is never staged:

```bash
git update-index --skip-worktree .env
```

Without that flag, `git add -A` will commit your key. The flag is per-clone, so
every clone needs it. To edit the tracked template itself — changing the model,
say — release the flag first:

```bash
git update-index --no-skip-worktree .env
```

`GROQ_MODEL` must be a model that emits JSON directly. Reasoning models
(`qwen/qwen3.6-27b`) fail instructor's JSON mode — they spend the token budget on
thinking and return an empty completion. Default is `openai/gpt-oss-120b`.

## Run

```bash
python3 src/orchestrator.py fixtures/qre-samples/S01_campus_cafeteria_experience.docx
```

Re-run from a previous stage's artifact instead of from the document:

```bash
python3 src/orchestrator.py <file.docx> --from-stage 4
```

Artifacts land in `out/<document stem>/`.

`--from-stage` skips stages 1 to 3 only. Stage 4 onwards always runs, so
`--from-stage 6` still re-parses. Stage 4 is the expensive stage — roughly fifty
model calls on a 31-question QRE — so iterating on Part 2 this way costs more
than it should. The decision record below removes most of that cost on a
re-run, but a `load_stage4` would remove the rest.

---

## Architecture

```
                        file.docx
                            │
        ┌───────────────────▼───────────────────┐
        │ STAGE 1  ingestion                    │  no LLM
        │ body XML walked in document order     │
        └───────────────────┬───────────────────┘
                            │  stage1_document.json
                            │  blocks[] — paragraphs (text, style, bold)
                            │             and tables (row/column grids)
        ┌───────────────────▼───────────────────┐
        │ STAGE 2  heading identification       │  LLM: shape-matching
        │ 7 targets, name match then shape      │
        └───────────────────┬───────────────────┘
                            │  stage2_blocks.json + stage2_flags.json
                            │  one ContentBlock per target = the heading
                            │  plus every block beneath it, and every
                            │  unmatched section kept as `unclassified`
        ┌───────────────────▼───────────────────┐
        │ STAGE 3  raw JSON                     │  LLM: prose only
        │ literal transcription per block       │
        └───────────────────┬───────────────────┘
                            │  stage3_<target>.json + stage3_flags.json
                            │  rows[] — source column names as keys,
                            │           cell text verbatim as values
                            │  row_sources[] — index-aligned provenance
        ┌───────────────────▼───────────────────┐
        │ STAGE 4  deep parse                   │  LLM: field split,
        │ parsers run under asyncio.gather      │       condition translation
        └───────────────────┬───────────────────┘
                            │  stage4_<target>.json + stage4_flags.json
                            │  typed objects: Question, RoutingRule,
                            │  AcceptanceScenario, CompletionMessage,
                            │  ExtractedStatement
        ┌───────────────────▼───────────────────┐
        │ STAGE 5  extraction quality check     │  no LLM
        │ audits stage 4 against 2 and 3        │
        └───────────────────┬───────────────────┘
                            │  stage5_audit.json
     ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  Part 1 ends here
        ┌───────────────────▼───────────────────┐
        │ STAGE 6  canonical specification      │  LLM: prose conditions,
        │ what the QRE means                    │       text pipes, quotas
        └───────────────────┬───────────────────┘
                            │  part2_canonical.json
                            │  every added value carries an origin
        ┌───────────────────▼───────────────────┐
        │ STAGE 7  route + dependency graphs    │  no LLM
        │ a view of the specification           │
        └───────────────────┬───────────────────┘
                            │  part2_route_graph.json
                            │  part2_graph_report.json
                            ▼
                    Agent 2 (build) · Agent 3 (test design)
```

**Targets.** `Questionnaire`, `Routing and termination`,
`Acceptance test scenarios`, `Completion messages`, `Quota controls`,
`Study specification`, `Programming and QA requirements`. Every target is
optional. A document with no quota section is not an error: Stage 3 writes
nothing for it, and Stage 4 writes an empty array — which says "this ran and
found none", where an absent file could not.

**Transcription boundary.** Stages 1–3 transcribe. Nothing is renamed,
normalised, inferred or split before Stage 4. That is what makes Stage 5's audit
possible: Stage 3's output is a faithful record of the source, so any difference
between it and Stage 4 is attributable to Stage 4.

**Interpretation boundary.** Nothing before Stage 6 decides what the document
means. Stage 6 is where a condition becomes a tree, a destination gets a kind,
and a display rule gets combined with its routing-table twin.

**Nothing is discarded.** A heading matching no target is kept with its content
(CLAUDE.md §16). An attribute Stage 4 reads but the canonical model does not name
is carried in `extra` with its JSON type rather than dropped.

### Where the LLM is allowed

A table is never sent to a model when python-docx can read it. Every response is
a Pydantic model, temperature 0.

| Stage | Call | Response schema |
|---|---|---|
| 2 | Shape-match an unmatched heading's content against a target | `LLMHeadingCandidate` |
| 3 | Transcribe a prose block (completion messages) | `LLMCompletionMessages` |
| 4 | Split one question's inline attributes | `LLMQuestionFields` |
| 4 | Translate one routing condition into an expression | `LLMRoutingExpression` |
| 6 | Rewrite a prose condition into the parser's grammar | `LLMConditionProposal` |
| 6 | Find wording that quotes an earlier answer | `LLMTextPipes` |
| 6 | Read a quota sentence into parts | `LLMQuota` |

Stage 6's condition call never returns a condition. It returns text in a grammar
the deterministic parser already checks, and the parser decides whether to
accept it — so a model can only propose something the QRE could have written
formally itself. Most conditions never reach a model at all: both fixtures write
`S1 == 'No'` and `Q12 in ['Fully','Partly']` themselves, and those parse
deterministically.

### Stage 4 concurrency

The parsers run concurrently. Routing awaits the questionnaire task because
translating a condition needs its option codes:

```python
questionnaire_task = asyncio.create_task(parse_questionnaire(...))

async def routing_after_questionnaire():
    questions, _ = await questionnaire_task
    return await parse_routing(..., questions)

await asyncio.gather(
    questionnaire_task, routing_after_questionnaire(),
    parse_scenarios(...), parse_messages(...),
)
```

Scenarios and messages never wait.

---

## Reproducibility — the decision record

Temperature 0 is not determinism. Three runs of C01 on identical code produced
three different specifications: the wording of Q21 was read as quoting Q19 twice
and not the third time, and R8's prose condition was declined once and accepted
twice. Each of those changes which questions a respondent sees, so a test built
on one reading cannot be told apart from a test built on another.

Every model call goes through `llm.complete`, so the record sits there. Each
answer is written to `out/<stem>/llm_decisions.json` and reused, keyed by a
digest of the model, the system prompt, the user prompt, the response schema and
the token cap. Change any of those — including editing the QRE, which changes the
prompt — and it asks again rather than reusing an answer to a different question.

```bash
QRE_LLM_CACHE=off python3 src/orchestrator.py <file.docx>   # re-ask everything
```

The file is a deliverable, not just a cache. It says what was inferred, from what
text, by which model and when, which makes the inferred half of a specification
reviewable in a way a fresh call is not. It is committed alongside the artifacts.

---

## Review flags

Ambiguity emits a flag rather than a guess.

```json
{"target_heading": "...", "status": "NOT_PRESENT | POSSIBLE_MATCH",
 "candidate_heading": "...", "confidence": 0.0, "reasoning": "...",
 "severity": "BLOCKING | WARNING | INFO", "target": {"kind": "...", "id": "..."}}
```

`stage2_flags.json`, `stage3_flags.json` and `stage4_flags.json` are always
written, empty array included — an absent file would be ambiguous between "no
flags" and "the stage did not run".

Part 2's equivalent is the `review` list inside `part2_canonical.json`. It reuses
the audit's finding shape so the two queues can be read together.

---

## Stage 5 — extraction quality check

Audits Stage 4's output against the source. **Audits, not re-extracts**: a second
independent extraction tends to repeat the first one's mistakes, so it agrees
with a wrong answer instead of catching it.

Five deterministic checks. No model is called, so the same inputs always give the
same findings, which is what makes this usable as a gate rather than as advice.

| Check | What it answers |
|---|---|
| `source_coverage` | Was every block Stage 1 read accounted for? |
| `row_accounting` | Did every transcribed row become an object? |
| `reference_integrity` | Does every identifier point at something that exists? |
| `condition_consistency` | Do scenarios treat identical conditions identically? |
| `piping_symmetry` | Are piped questions guarded the way their peers are? |

Written to `stage5_audit.json`, holding the per-section scores, the findings and
a pass/fail. Kept separate from `stage4_flags.json` rather than appended to it:
a Stage 4 flag is trouble that stage hit while working, an audit finding is a
disagreement between artifacts that each looked fine alone, and conflating the
two loses which you are reading.

Nothing here evaluates a condition. Deciding whether
`Q3 != 'None/currently not using'` holds means parsing it, which is Part 2's
job. `condition_consistency` reaches the same defect by comparing condition text
for equality — enough to report that C02's scenario T3 names Q7, Q8 and Q9 but
not Q15, though all four carry an identical display condition.

### Inputs

Per section, Stage 5 needs a pair — what Stage 4 produced, and what it was
produced from. Everything required is already on disk.

| Input | File | Role in the audit |
|---|---|---|
| Stage 4 output | `stage4_<target>.json` | The thing being audited |
| Literal transcription | `stage3_<target>.json` | Field-by-field comparand. Row-aligned with Stage 4, so a discrepancy points at one item and one field |
| Original content block | `stage2_blocks.json` | Completeness check. Catches anything Stage 3 itself dropped, which comparing only against Stage 3 would miss |
| Existing flags | `stage2/3/4_flags.json` | Already-known problems, so the audit does not re-report them as new findings |

Both sources are needed. Stage 3 alone cannot show that a whole row was lost
before it; Stage 2 alone is not row-aligned enough to attribute a discrepancy to
a specific field.

### Scoring

Per section, never blended into one number:

```
score = correct fields ÷ total fields expected for that section
```

"Expected" means fields the source actually states — not every field on the
model. `Question` declares 17 fields, but a free-text question legitimately has
no options, no scale and no matrix rows. Counting unstated fields as expected
would make every question look incomplete.

| Section | Threshold | Why |
|---|---|---|
| Questionnaire | 95% | Large section; a percentage is meaningful |
| Routing and termination | 95% | Large section; a percentage is meaningful |
| Acceptance test scenarios | 100% | Small section; a percentage swings too wildly to mean anything |
| Completion messages | 100% | Small section; same reason |

### Outcome

- **At or above threshold** → the section proceeds automatically.
- **Below threshold** → the section goes to the review queue with the specific
  discrepancies listed, `{item, field, expected, found}`. Not a full re-review of
  the section; the reviewer looks at the named fields.

---

## Stage 6 — the canonical survey specification

Platform-neutral, typed, traceable. Part 1's artifacts stay the record of what
the document says; this is the reading of them, written to a separate file so a
disagreement about interpretation never costs the extraction.

```
CanonicalSurvey
├── semantics        decisions the QRE never states, marked as decisions
├── metadata         what the document says about the study
├── questions[]      order, type, wording, options, matrix rows,
│                    validation, display guard, runtime option source
├── dispositions[]   every way the survey can end
├── rules[]          typed condition tree, destination kind, evaluation
│                    point, precedence
├── dependencies[]   option-source and wording pipes
├── randomization[]  what is shuffled, what is anchored
├── quotas[]         cells resolved to option ids
├── scenarios[]      the QRE's own acceptance tests
├── requirements[]   what the document asks of whoever programs and tests it
└── review[]         everything a person still has to decide
```

**Every added value carries an origin** — `extracted`, `derived`, `inferred`,
`unknown` or `ambiguous` (CLAUDE.md §14). An inference is never presented as
something the QRE stated. Where the document does not say, the answer is null and
a review finding names it, rather than a default standing in for evidence.

**Conditions are trees, not strings.** Built from `condition_raw`, which is
verbatim source text, and never from Stage 4's `condition_expression`, which a
model wrote. Operators come from a closed set, so the same operator cannot arrive
written three ways. Values resolve to option ids alongside their original text,
so nothing downstream matches on a label that changes with any rewording.

**A piped question keeps its printed list** and carries an `option_source`
naming the earlier answer that narrows it. Editing the list down to a guess would
hide the difference; saying nothing would let a bot pick an option that is not on
screen.

---

## Stage 7 — the graphs

Two graphs, because they answer different questions and fusing them gives
something that answers neither well:

| Graph | What it holds |
|---|---|
| `RouteGraph` | How a respondent moves. Questions and endings as nodes, transitions as edges. A `MultiDiGraph`, because one pair of nodes can legitimately be joined twice. |
| `DependencyGraph` | Which questions need which earlier answers. Must be acyclic — a cycle would mean a question needing its own answer. |

Questions form a spine in the order the QRE asks them, and a question's display
condition is an attribute of its node rather than a set of edges. Compiling every
guard into edge conditions multiplies edges for no extra information and buries
which rule each came from. Route discovery walks the spine and skips nodes whose
guard is false.

Three things are deliberately **not** edges:

- **show rules** — already the target node's guard. An edge as well would state
  the same fact in two places that can disagree.
- **reject rules** — a gate on progressing, not a change of destination. Recorded
  as `constraint` in `rule_edge_map` so a coverage check can tell "represented"
  from "lost".
- **randomisation** — changes what a question looks like, never where it leads.

Quota transitions *are* edges, but marked `stateful`: they depend on how many
other people already answered that way, so route enumeration has to exclude them
or every route ends at a quota.

`rule_edge_map` is the traceability spine — which rule produced which edge or
guard. It is what lets a failing test point back at the sentence in the QRE that
asked for the behaviour.

`part2_graph_report.json` says whether the graph faithfully represents the
specification: node and rule coverage, unreachable nodes, endings with a way out
of them, and cycles in either graph. That is a different question from whether
the specification is right, which is what Stage 5 asks.

**A fact that exists only in a graph and not in the specification is a bug.** The
reverse is a design decision.

---

## Files

```
src/
  models.py              every artifact and LLM response schema
  llm.py                 instructor-patched Groq client, and the decision record
  stage1_ingestion.py
  stage2_headings.py
  stage3_raw_json.py
  stage4_deep_parse.py
  stage5_audit.py        five deterministic checks
  part2_conditions.py    a routing condition read as a tree
  part2_canonical.py     the canonical survey specification
  part2_graph.py         route and dependency graphs
  orchestrator.py
```

## Rate limits

Groq's free tier caps tokens per minute and per day. `llm.py` bounds concurrency
(`MAX_CONCURRENCY`), keeps `MAX_TOKENS` tight because the requested cap counts
against the budget, waits out a per-minute 429 using the delay the provider
names, and fails fast on a per-day cap rather than sleeping through retries that
cannot succeed.

A 31-question QRE issues roughly fifty calls and takes several minutes on the
free tier. A re-run of the same document costs nothing, because the decision
record answers every call.

## Known gaps

- **No tests.** The previous suite covered modules that no longer exist and was
  deleted with them; nothing replaced it.
- **Stage 5 scores rows, not fields.** A section's score is the share of
  transcribed rows that produced an identified object. The field-by-field
  comparand against Stage 3 is not built.
- **The whole pipeline has been run end to end on C02, C01 and S01 only.**
  Stages 1 to 4 run over all 17 fixtures without error, but the model-dependent
  paths — Stage 2 shape-matching, Stage 3 prose transcription, Stage 4's field
  split, and all three Stage 6 calls — have been exercised on those three.
- **Part 2 has no condition evaluator.** The trees are machine-evaluable and
  nothing evaluates them. Route feasibility — deciding whether the guards along a
  path can all hold at once — is Agent 3's to build.
- **`build_route_graph` wires only the first completion.** A QRE with two
  `complete` dispositions would connect its last question to one of them.
  Neither committed fixture has two, so it has never bitten.
- **Nothing checks that a survey can end at all.** The disposition checks iterate
  the dispositions that exist, so a document with none passes them vacuously.
- **No `option_id` → LimeSurvey answer-code mapping exists.** Answer codes are
  absent on most questions in both fixtures and may not be invented (§13). That
  mapping is Agent 2's, and nothing specifies it yet.
