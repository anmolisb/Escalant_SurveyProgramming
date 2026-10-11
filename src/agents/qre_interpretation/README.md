# Agent 1: QRE Interpreter

Reads a questionnaire requirement document (QRE, `.docx`) and produces the
**Canonical Survey Specification**: a platform-neutral, typed, traceable
description of how the survey must behave. The Survey Builder, the Test
Designer and the Respondent Bot all work from that one file.

**Supported format.** The S, M and C QRE format in `fixtures/qre-samples/`: a
front page, then headed sections (study specification, questionnaire table,
routing table, quotas, completion messages, programming requirements,
acceptance scenarios).

## Run

```bash
pip install -r requirements.txt
cp config/.env.example .env          # then set GROQ_API_KEY
python -m src.agents.qre_interpretation.orchestrator fixtures/qre-samples/S01_campus_cafeteria_experience.docx
```

Outputs go to `out/<document name>/agent1/`. Exit code **0** means the
specification passed its check, **2** means it was produced but the check found
something wrong, **1** means the run stopped with an error.

`GROQ_MODEL` in `.env` must return JSON directly (default
`openai/gpt-oss-120b`). Reasoning models spend their budget thinking and return
nothing.

## Architecture

Every output file starts with `agent1_` and carries its stage number, so files
sort in pipeline order. All names live in `src/common/paths.py`.

```
                        file.docx
                            │
┌───────────────────────────▼───────────────────────────┐
│ STAGE 1  Ingestion                         no model   │
│ paragraphs and tables, in document order              │
└───────────────────────────┬───────────────────────────┘
                            │  agent1_s1_document.json
┌───────────────────────────▼───────────────────────────┐
│ STAGE 2  Sections                          model*     │
│ each heading matched to one of 7 sections             │
│ by name first, by content shape only if that fails    │
└───────────────────────────┬───────────────────────────┘
                            │  agent1_s2_blocks.json, agent1_s2_flags.json
┌───────────────────────────▼───────────────────────────┐
│ STAGE 3  Transcription                     model*     │
│ every row and cell copied word for word               │
└───────────────────────────┬───────────────────────────┘
                            │  agent1_s3_<section>.json, agent1_s3_flags.json
┌───────────────────────────▼───────────────────────────┐
│ STAGE 4  Deep parse                        model*     │
│ typed questions, rules, messages, scenarios           │
│ conditions still kept exactly as written              │
└───────────────────────────┬───────────────────────────┘
                            │  agent1_s4_<section>.json, agent1_s4_survey.json,
                            │  agent1_s4_flags.json
┌───────────────────────────▼───────────────────────────┐
│ STAGE 5  Audit                             no model   │
│ Stage 4 checked against Stages 2 and 3: coverage,     │
│ rows, wording, references, conditions, piping         │
└───────────────────────────┬───────────────────────────┘
                            │  agent1_s5_audit.json
 ─ ─ ─ ─ ─ ─ ─ ─ ─  Part 1 ends: what the QRE says  ─ ─ ─ ─ ─ ─ ─ ─ ─
┌───────────────────────────▼───────────────────────────┐
│ STAGE 6  Specification                     model*     │
│ what the QRE means: conditions become trees,          │
│ every value marked with where it came from            │
└───────────────────────────┬───────────────────────────┘
                            │  agent1_canonical_survey_spec.json  ◀ the contract
┌───────────────────────────▼───────────────────────────┐
│ STAGE 7  Validation                        no model   │
│ an independent reading of the document checks the     │
│ specification; open questions go to a person          │
└───────────────────────────┬───────────────────────────┘
                            │  agent1_s7_validation.json, agent1_s7_evaluation_*.json,
                            │  agent1_s7_decisions.json, agent1_s7_decision_register.md
┌───────────────────────────▼───────────────────────────┐
│ STAGE 8  Route graph                       no model   │
│ how a respondent moves through the survey             │
└───────────────────────────┬───────────────────────────┘
                            │  agent1_s8_route_graph.json, agent1_s8_graph_report.json,
                            │  agent1_s8_route_graph.gexf
                            ▼
                    agent1_ready.json   APPROVED or BLOCKED
                            │
          Survey Builder · Test Designer · Respondent Bot

  * only for what plain code cannot read (see "Where the model is used")
  agent1_llm_cache.json holds every model answer, across all stages
```

## Key ideas

**Part 1 records, Part 2 interprets.** Stage 4 keeps `Show if: Q5 contains any
touchpoint` as text. Only Stage 6 may decide the operator is `contains_any`.
Because Stage 3 is a word-for-word copy, any difference Stage 5 finds can only
have come from Stage 4.

**Every value says where it came from**: `extracted` (stated in the QRE),
`derived` (worked out by code), `inferred` (read by a model), `unknown` or
`ambiguous`. Where the QRE is silent the value is null and a review item names
it. Nothing is guessed.

**Conditions are trees, not strings.** A condition already written formally
(`S1 == 'No'`) is parsed by code. Prose goes to the model, which must answer in
the parser's own grammar, so it can only propose what the QRE could have written
itself. Anything unreadable becomes a review item.

**The check shares no code with what it checks.** Stage 7's oracle reads the
document from Stage 1 only and works everything else out itself.

**People decide, not the pipeline.** Readings the QRE does not settle (which
rule wins when two apply, say) go into the decision register. A project owner
edits an entry and re-runs; the answer is reused until the document changes.

**The ready gate.** `agent1_ready.json` says `APPROVED` only when Stage 7 did
not fail the specification, every blocking decision is confirmed, and the
Stage 8 graph check passed. Otherwise `blocked_by` says what is outstanding.

## Where the model is used

Code reads everything it can. The model gets only these, at temperature 0, each
answer checked against a Pydantic schema:

| Stage | Call |
|---|---|
| 2 | Match a heading that matches no section name |
| 3 | Transcribe a prose section (completion messages) |
| 4 | Label instruction lines in no known form |
| 6 | Rewrite a prose condition in the parser's grammar |
| 6 | Find wording that quotes an earlier answer |
| 6 | Read a quota sentence into its parts |

Every answer is saved in `agent1_llm_cache.json`, so a re-run of an unchanged
document makes no model calls and gives the same specification. To re-ask
everything: `QRE_LLM_CACHE=off` in front of the run command. A fresh run costs
about 2 calls for an S QRE, 7 for an M and 15 for a C.

## Code

```
src/agents/qre_interpretation/
  orchestrator.py        runs every stage and writes the outputs
  models.py              every output and model-answer schema
  stage1_ingestion.py    stage2_headings.py    stage3_raw_json.py
  stage4_deep_parse.py   stage5_audit.py
  stage6_canonical.py    stage6_conditions.py  (condition parser)
  stage7_validation.py   stage7_oracle.py      stage7_tests.py
  stage7_cross_check.py  stage7_decisions.py
  stage8_graph.py
```

Tests: `tests/test_conditions.py`, `tests/test_stage5_content.py`,
`tests/test_stage8_graph.py`.

## Known limitations

- **Every QRE starts BLOCKED.** Each leaves some readings unstated, and those
  wait for a person in the decision register. That is the gate working.
- **M QREs exit with code 2.** Stage 7 and Stage 6 name S3's age range fields
  differently, so the check reports a mismatch. The specification is correct
  and the survey builds.
- **Model readings of prose can vary** between documents. A declined condition
  becomes a review item, never a guess.
- **Only the first completion ending is wired into the graph.** No supported
  QRE has two.
- **No invented answer codes.** Where the QRE gives none, the Survey Builder
  numbers options itself (A001, A002, ...).
