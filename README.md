# QRE extraction pipeline

DOCX questionnaire requirement document → four structured JSON outputs.

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

Re-run any stage from the previous stage's artifact:

```bash
python3 src/orchestrator.py <file.docx> --from-stage 4
```

Artifacts land in `out/<document stem>/`.

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
        │ 4 targets, name match then shape      │
        └───────────────────┬───────────────────┘
                            │  stage2_blocks.json + stage2_flags.json
                            │  one ContentBlock per target = the heading
                            │  plus every block beneath it
        ┌───────────────────▼───────────────────┐
        │ STAGE 3  raw JSON                     │  LLM: prose only
        │ literal transcription per block       │
        └───────────────────┬───────────────────┘
                            │  stage3_<target>.json ×4 + stage3_flags.json
                            │  rows[] — source column names as keys,
                            │           cell text verbatim as values
        ┌───────────────────▼───────────────────┐
        │ STAGE 4  deep parse                   │  LLM: field split,
        │ 4 parsers, asyncio.gather             │       condition translation
        └───────────────────┬───────────────────┘
                            │  stage4_<target>.json ×4 + stage4_flags.json
                            │  typed objects: Question, RoutingRule,
                            │  AcceptanceScenario, CompletionMessage
                            ▼
                    STAGE 5  quality check  (not built — see below)
```

**Targets.** `Questionnaire`, `Routing and termination`,
`Acceptance test scenarios`, `Completion messages`.

**Transcription boundary.** Stages 1–3 transcribe. Nothing is renamed,
normalised, inferred or split before Stage 4. That is what makes Stage 5's audit
possible: Stage 3's output is a faithful record of the source, so any difference
between it and Stage 4 is attributable to Stage 4.

**Stage isolation.** Each stage reads only the previous stage's artifact, so any
stage re-runs alone via `--from-stage N`.

### Where the LLM is allowed

Three places, and nowhere else. A table is never sent to a model when
python-docx can read it.

| Stage | Call | Response schema |
|---|---|---|
| 2 | Shape-match an unmatched heading's content against a target | `LLMHeadingCandidate` |
| 3 | Transcribe a prose block (completion messages) | `LLMCompletionMessages` |
| 4 | Split one question's inline attributes | `LLMQuestionFields` |
| 4 | Translate one routing condition into an expression | `LLMRoutingExpression` |

Every response is a Pydantic model, temperature 0.

### Stage 4 concurrency

All four parse concurrently. Routing awaits the questionnaire task because
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

## Review flags

Ambiguity emits a flag rather than a guess.

```json
{"target_heading": "...", "status": "NOT_PRESENT | POSSIBLE_MATCH",
 "candidate_heading": "...", "confidence": 0.0, "reasoning": "..."}
```

`stage2_flags.json`, `stage3_flags.json` and `stage4_flags.json` are always
written, empty array included — an absent file would be ambiguous between "no
flags" and "the stage did not run".

---

## Stage 5 — extraction quality check (not built)

Audits Stage 4's output against the source. **Audits, not re-extracts**: a second
independent extraction tends to repeat the first one's mistakes, so it agrees
with a wrong answer instead of catching it.

Manual for now via a Streamlit review UI; a Groq audit-style call with a Pydantic
schema later.

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

### Not yet decided

The spec places the review queue alongside "Steps 2 and 10". This pipeline has
four stages and no Step 10 — that numbering is from the earlier ten-step design.
The queue that exists today is the three `*_flags.json` files. Whether Stage 5
appends to those or gets its own store needs deciding before it is built.

---

## Files

```
src/
  models.py              every artifact and LLM response schema
  llm.py                 instructor-patched Groq client
  stage1_ingestion.py
  stage2_headings.py
  stage3_raw_json.py
  stage4_deep_parse.py
  orchestrator.py
```

## Rate limits

Groq's free tier caps tokens per minute. `llm.py` bounds concurrency
(`MAX_CONCURRENCY`), keeps `MAX_TOKENS` tight because the requested cap counts
against the budget, and waits out a 429 using the delay the provider names.

A 31-question QRE issues roughly 50 calls and takes several minutes on the free
tier. Stage 5's audit will add one call per section on top of that.

## Known gaps

- **No tests.** The previous suite covered modules that no longer exist and was
  deleted with them; nothing replaced it.
- **Stage 5 not built.** Manual review is the only quality check today.
- **Two fixtures verified end to end** — `S01` (10 questions) and `C01` (31
  questions, matrix, prose routing conditions). The rest of the corpus has not
  been run through this pipeline.
