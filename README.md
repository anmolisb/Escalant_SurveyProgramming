# Escalent Agentic Survey QA Platform

ISB AMPBA 2026S capstone for **Escalent India Pvt. Ltd.**, August–October 2026.

A pipeline of AI agents that reads a questionnaire requirement document (QRE), builds the survey it describes in LimeSurvey, and designs the tests that prove the built survey behaves as specified. Checking a survey by hand does not scale: one with 18 branch points has more than 262,000 answer paths.

`CLAUDE.md` is the authoritative project document — scope, contracts, engineering rules and security. Read it first.

## Agents

| # | Agent | Does | Status on `main` |
|---|---|---|---|
| 1 | QRE Interpreter | Turns a QRE into a structured extraction and a platform-neutral survey specification | Implemented — 9 stages |
| 2 | Survey Builder | Turns Agent 1's output into a LimeSurvey `.lss` file | Implemented — basic question types |
| 3 | Test Designer | Derives respondent paths and test cases from the specification | Implemented — see note |
| 4 | Respondent Bot | Will run the tests against the live survey | Stub |
| 5 | QA Adjudicator | Will compare observed behaviour with the specification | Stub |

**Scope note.** `CLAUDE.md` Section 3 scopes real implementation to Agents 1 and 2 in this phase and keeps Agents 3–5 as stubs until the team moves them into the build phase. Agent 3 has nevertheless been implemented and merged, so the code is ahead of `CLAUDE.md`; the two need reconciling.

## Architecture

Agents are separate command-line programs connected by files, not by an in-process graph. Each reads the previous agent's output from `out/<survey>/` and writes its own beside it. The Streamlit dashboard runs Agents 1 → 2 → 3 by calling the same commands. `src/orchestration/` is an empty placeholder.

```
QRE (.docx)
  └─▶ Agent 1  QRE Interpreter  ──▶ out/<survey>/stage*_*.json, part2_*.json, agent1_*.json
        ├─▶ Agent 2  Survey Builder  ──▶ out/<survey>_generated.lss        reads stage4_*.json
        └─▶ Agent 3  Test Designer   ──▶ out/<survey>/agent3/              reads part2_canonical.json
                                                                           (+ the .lss, if given)
```

### Agent 1 — QRE Interpreter

`src/agents/qre_interpretation/`

```bash
python -m src.agents.qre_interpretation.orchestrator fixtures/qre-samples/<file>.docx
```

- Accepts `.docx` only. PDF ingestion was removed, so the two PDF fixtures cannot currently be run.
- All nine stages run on every call. `--from-stage N` reloads stages 1–3 from disk; stage 4 onwards always re-runs.
- Exits with code 2 when stage 7 marks the specification FAILED.

**Part 1 — what the document says.** Nothing is interpreted before stage 6.

| Stage | What it does | Model use | Writes |
|---|---|---|---|
| **1 Ingestion**<br>`stage1_ingestion.py` | Reads the document body in order: paragraphs (text, style, bold, heading level) and tables (rows of cell text). | — | `stage1_document.json` |
| **2 Sections**<br>`stage2_headings.py` | Assigns headings to seven target sections — Questionnaire, Routing and termination, Acceptance test scenarios, Completion messages, Quota controls, Study specification, Programming and QA requirements — by name, otherwise by content shape. One heading per target. Every target is optional; other sections are kept as `unclassified`. | Shape match | `stage2_blocks.json`<br>`stage2_flags.json` |
| **3 Transcription**<br>`stage3_raw_json.py` | Copies each section verbatim. Table rows keep the document's own column names and a source reference per row. | Completion messages only | `stage3_<section>.json`<br>`stage3_flags.json` |
| **4 Deep parse**<br>`stage4_deep_parse.py` | Builds typed questions, routing rules, scenarios, messages and statements. Column meanings come from synonym lists. Formal conditions are rendered by a parser (`derived`); prose ones by the model (`inferred`). | Instruction labelling, condition translation | `stage4_<section>.json`<br>`stage4_survey.json`<br>`stage4_flags.json` |
| **5 Audit**<br>`stage5_audit.py` | Checks stage 4 against stages 2–3: source coverage, row accounting, reference integrity, condition consistency, piping symmetry. | — | `stage5_audit.json` |

Stage 4 files are written without an envelope or per-item provenance because they are Agent 2's input; later stages still receive the full records in memory.

**Part 2 — what the document means.**

| Stage | What it does | Model use | Writes |
|---|---|---|---|
| **6 Specification**<br>`part2_canonical.py`<br>`part2_conditions.py` | The platform-neutral specification: condition trees built from the verbatim text, typed destinations, display guards, dependencies, randomisation, quotas, endings, scenarios, the survey-wide rules the QRE never states, and a review queue. Every added value records its origin: `extracted`, `derived`, `inferred`, `unknown` or `ambiguous`. | Prose conditions, wording pipes, quota sentences | `part2_canonical.json` |
| **7 Validation**<br>`run_validation.py` + `part2_validate.py`, `qre_oracle.py`, `agent1_eval.py`, `agent1_decisions.py` | Compares raw QRE, stage 4 and specification using an oracle that reads the document independently; re-runs stage 6 twice to check reproducibility; runs tests derived from the QRE; keeps the register of decisions a person must make. | Reuses stage 6's saved answers | `part2_validation.json`<br>`agent1_evaluation_tests.json`<br>`agent1_evaluation_results.json`<br>`agent1_decisions.json`<br>`agent1_decision_register.md` |
| **8 Graphs**<br>`part2_graph.py` | A route graph (how a respondent moves) and a dependency graph (which answers a question needs), plus a map from every edge back to its rule. | — | `part2_route_graph.json`<br>`part2_graph_report.json` |
| **9 Graph check and gate**<br>`graph_validate.py`<br>`run_graph_validation.py` | Checks the saved graph structurally and by walking it. Then sets the Agent 3 gate: APPROVED only if the specification did not fail, every blocking decision is resolved, and the graph is ready. | — | `part2_graph_validation.json`<br>`route_graph` / `dependency_graph` `.graphml` `.gexf`<br>`agent1_stage9_gate.json` |

All model calls go through `src/common/llm/groq_client.py`. Each answer is saved to `out/<survey>/llm_decisions.json` and reused, so a document reads the same way on every run; set `QRE_LLM_CACHE=off` to ask again. Full detail: [`src/agents/qre_interpretation/README.md`](src/agents/qre_interpretation/README.md).

### Agent 2 — Survey Builder

`src/agents/survey_builder/` · deterministic, no model

```bash
python -m src.agents.survey_builder.build out/<survey>
```

Reads four of Agent 1's stage 4 files — survey, questionnaire, routing and messages. `CLAUDE.md` Section 26 names the canonical specification as Agent 2's input instead.

| Step | What it does |
|---|---|
| **1 Preflight**<br>`preflight.py` | Lists every construct the builder cannot handle, all at once, and stops the build if there are any. Also runs alone: `python -m src.agents.survey_builder.preflight out/<survey>`. |
| **2 Load**<br>`loader.py`, `models.py` | Converts the files into a LimeSurvey-shaped model: assigns answer codes `A001…` where the QRE gives none, turns answer labels in conditions into codes, puts questions whose ID starts with `S` in a Screening group and the rest in a Main Survey group. LimeSurvey has no terminate action, so terminate rules are inverted into the Main Survey group's show condition and the end screen picks its message from the original rules. Skip and reject rules produce nothing. |
| **3 Emit**<br>`emitter.py` | Writes the `.lss` XML in the shape a real LimeSurvey export uses, to `out/<survey>_generated.lss`. |

- **Supported question types:** single choice, multiple choice, free text, grid, constant sum.
- **Reported by preflight:** conditions it cannot translate, such as AND/OR combinations and question-to-question comparisons.
- **Not read at all:** quotas, study details, programming notes and scenarios. Quotas are dropped without a warning.

Full detail: [`src/agents/survey_builder/README.md`](src/agents/survey_builder/README.md).

### Agent 3 — Test Designer

`src/agents/test_design/` · deterministic, no model

```bash
python -m src.agents.test_design.run out/<survey> --lss out/<survey>_generated.lss --inputs data/inputs/test_design/<survey>.json
```

`--lss`, `--inputs` and `--sample-size` are optional. Reads `part2_canonical.json` and the decisions in `agent1_decisions.json`. `--inputs` supplies facts a QRE does not state, such as sample size and anchored options. Agent 1's gate is copied into `agent3_coverage.json`, but a BLOCKED gate does not stop the run.

| Step | What it does |
|---|---|
| **1 Load** · `spec.py`, `semantics.py` | Reads the specification and the survey-wide reading rules, with whether each is confirmed. |
| **2 Paths** · `path_enumerator.py` | Lists the distinct respondent journeys, and a smaller set that takes every branch both ways. |
| **3 B1 Targets** · `b1_targets.py` | Every behaviour that can be proven true or false, in nine dimensions that are never added together. |
| **4 B2 Witnesses** · `b2_witness.py` | For each target, the smallest set of answers that reaches it. |
| **5 B3 Oracle** · `b3_oracle.py` | Predicts what the survey should do with those answers. It never sees the target and shares no code with B2, so a test and its expected result cannot share a bug. |
| **6 B4 Reconcile** · `b4_reconcile.py` | Decides whether each target is covered by comparing witness and prediction. |
| **7 Logical tests** · `compile_logical.py` | Platform-neutral test cases, each ending at the question it tests. |
| **8 Block A** · `a_implementation.py` | *With `--lss`.* Reads the built survey and checks it against the specification. |
| **9 Block C** · `c_compile_executable.py` | *With `--lss`.* Turns logical tests into steps using real field names and answer codes; refuses rather than guesses. |
| **10 Replay** · `run.py` | Runs Agent 1's acceptance scenarios through the B3 oracle. |
| **11 Reports** · `report.py`, `paths_workbook.py`, `qre_validation_workbook.py` | Review files for sign-off. |

Writes to `out/<survey>/agent3/`:

- **Block results:** `agent3_targets`, `_witnesses`, `_expected_states`, `_coverage`, `_scenarios`, `_logical_tests`, `_paths` and `_summary`, all `.json`.
- **Review files:** `agent3_review.md`, `agent3_review.xlsx`, `agent3_test_cases_with_paths.xlsx` and `agent3_test_cases_for_review.xlsx`.
- **With `--lss` only:** `implementation_snapshot.json`, `agent3_conformance.json` and `agent3_executable_tests.json`.

Example output: [`docs/agent3/README.md`](docs/agent3/README.md).

### Agents 4 and 5

`src/agents/respondent_bot/` and `src/agents/qa_adjudication/` contain only a package docstring. Their prompt modules in `src/common/prompts/` are empty.

## Tech stack

| In use | For |
|---|---|
| Python 3.13 | Everything |
| python-docx | Reading QREs |
| Groq, through `instructor` and Pydantic v2 | Structured model output in Agent 1 |
| NetworkX | Agent 1's route and dependency graphs |
| Streamlit, graphviz | Dashboard |
| openpyxl | Agent 3's workbooks |
| pytest | Tests |
| LimeSurvey Community Edition (Docker) | The survey platform Agent 2 targets |

Planned, not yet in the code: LangGraph orchestration, a FastAPI backend, and Playwright for Agent 4. Forsta/Decipher is out of scope for this phase.

## Repository layout

```
├── CLAUDE.md                 Authoritative project instructions
├── .github/workflows/ci.yml  pytest on Linux and Windows on every push
├── config/.env.example       Template for .env (GROQ_API_KEY, GROQ_MODEL)
├── docs/
│   ├── decisions/            Append-only decision log
│   ├── architecture/         how-it-works.md — describes the earlier, since-removed Part 1 design
│   ├── agent3/               Example Agent 3 workbooks
│   └── fix-tracker.md, agent1_validation_*.md, graph_validation_report.md
├── fixtures/
│   ├── qre-samples/          17 synthetic QREs (15 DOCX, 2 PDF) — develop against these
│   └── holdout/              3 QREs held back — do not open (see below)
├── data/                     Git-ignored except:
│   ├── inputs/test_design/   Per-survey facts for Agent 3 (committed)
│   └── ground_truth/
│       ├── Synthetic/        Ground-truth worksheets for the synthetic corpus (committed; none coded yet)
│       └── Client/           Confidential — never committed
├── out/                      All agent output, one folder per survey (committed)
├── src/
│   ├── agents/               One package per agent (see Architecture)
│   ├── common/llm/           The only place a model provider SDK may be imported
│   ├── common/prompts/       Per-agent prompt modules (currently empty)
│   ├── dashboard/            Streamlit app
│   └── orchestration/, backend/, reports/   Empty placeholders
└── tests/
    ├── test_conditions.py, test_part2_graph.py   Agent 1
    ├── survey_builder/       Agent 2, against a known-good S01 build
    ├── test_design/          Agent 3
    ├── agent1_verification/  Agent 1 verification harness, run by hand
    └── unit/, integration/, regression/, uat/   Empty placeholders
```

## Getting started

Requires Python 3.13.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config/.env.example .env        # then set GROQ_API_KEY
python -m pytest
```

Agent 1 needs the Groq key in `.env` at the repository root; `.env` is git-ignored. To run the dashboard, install the graphviz binary (`brew install graphviz` or `apt-get install graphviz`), then:

```bash
PYTHONPATH=. streamlit run src/dashboard/app.py
```

### Changing the Groq API key

1. Create a key at [console.groq.com/keys](https://console.groq.com/keys).
2. Open `.env` in the repository root (copy it from `config/.env.example` if it does not exist) and replace the value:
   ```
   GROQ_API_KEY=gsk_your_new_key
   ```
3. Make sure no older key is set in your shell, because a shell variable takes precedence over `.env`:
   ```bash
   unset GROQ_API_KEY                 # Windows PowerShell: Remove-Item Env:GROQ_API_KEY
   ```

The key is read when an agent starts, so the next run — from the command line or the dashboard — uses the new key with no restart. `GROQ_MODEL` in the same file changes the model the same way. Never commit `.env`; it is git-ignored.

### Working with the corpus

- **Do not open `fixtures/holdout/`.** It measures whether Agent 1 generalises beyond the documents it was built against, and reading it destroys that measurement (decision 0002). The automated guard was removed in the `main` cleanup, so this now rests on discipline alone; CI only checks that `ESCALENT_ALLOW_HOLDOUT` is not set.
- **Never place client-derived material in a committed folder.** Confidential QREs and ground truth belong in `data/ground_truth/Client/` or outside the repository (`CLAUDE.md` Sections 51–53).

## Team

| Role | Name | Email |
|---|---|---|
| Team | Anoop Kumar | Anoop_Kumar_ampba2026S@isb.edu |
| Team | Sanskar Jain | Sanskar_Jain_ampba2026S@isb.edu |
| Team | Anmol Jindal | anmol_jindal_ampba2026S@isb.edu |
| Team | Raveena Mallina | Raveena_Mallina_ampba2026S@isb.edu |
| Team | Atishi | Atishi_0099_ampba2026S@isb.edu |
| Client Mentor | Sameer Saurabh | sameer.saurabh@escalent.co |
| Faculty Mentor | Ram Vempati | ramakrishna.vempati@gmail.com |

## Milestones

| Gate | Date | Due |
|---|---|---|
| M1 | 14 Aug | Scope agreed, platform feasibility proven |
| M2 | 11 Sep | Full pipeline runs end to end |
| M3 | 9 Oct | Every agent meets accuracy targets |
| M4 | 16 Oct | Soft launch, UAT, final benchmark |
