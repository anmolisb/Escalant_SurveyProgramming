# Escalent Agentic Survey QA Platform

ISB AMPBA 2026S capstone for **Escalent India Pvt. Ltd.**, August to October 2026.

A pipeline of AI agents that reads a questionnaire requirement document (QRE),
builds the survey it describes in LimeSurvey, designs the tests that prove the
built survey behaves as specified, runs those tests in a real browser, and
reports what the results mean. Checking a survey by hand does not scale: one
with 18 branch points has more than 262,000 answer paths.

`CLAUDE.md` is the authoritative project document: scope, contracts,
engineering rules and security.

## Supported QREs

The pipeline reads the **S, M and C QRE format** in `fixtures/qre-samples/`
(15 documents: S01 to S05 simple, M01 to M06 moderate, C01 to C04 complex).
Each has a front page, then headed sections: study specification,
questionnaire table, routing table, quotas, completion messages, programming
requirements and acceptance scenarios. Questionnaires may include display
messages (a "text display" row with nothing to answer).

QREs in a different format need changes to the agents, described in the
project report.

## Agents

| # | Agent | Does | Model use |
|---|---|---|---|
| 1 | QRE Interpreter | Turns a QRE into the Canonical Survey Specification | Only where plain code cannot read the text |
| 2 | Survey Builder | Builds a LimeSurvey `.lss` file from the specification | None |
| 3 | Test Designer | Works out every respondent journey and the tests that prove the survey | None |
| 4 | Respondent Bot | Runs the tests in a real browser against the live survey | None |
| 5 | QA Adjudicator | Decides what each failure means and who should act on it | None |

## How it fits together

Agents are separate command-line programs connected by files. Each reads the
earlier agents' output from `out/<QRE>/` and writes its own into its own
folder. The Streamlit dashboard runs the same commands.

```
QRE (.docx)
  └─▶ Agent 1  QRE Interpreter  ──▶ out/<QRE>/agent1/agent1_canonical_survey_spec.json
        ├─▶ Agent 2  Survey Builder  ──▶ out/<QRE>/agent2/agent2_<QRE>.lss
        │                                  │  imported into LimeSurvey and activated
        └─▶ Agent 3  Test Designer   ──▶ out/<QRE>/agent3/agent3_executable_tests.json
                                           │
              Agent 4  Respondent Bot  ──▶ out/<QRE>/agent4/agent4_results.json
                                           │
              Agent 5  QA Adjudicator  ──▶ out/<QRE>/agent5/agent5_qc_report.xlsx
```

Every output file name starts with its agent (`agent1_...`, `agent2_...`), so
a file is identifiable after it is downloaded. All names are defined in
`src/common/paths.py`.

**Before Agents 2 to 4 run, a readiness check** compares the specification
with what each agent says it supports, and names anything it cannot handle,
before any time is spent on it:

```bash
python -m src.common.readiness out/<QRE>
```

It also runs automatically: the Survey Builder prints it, the Test Designer
refuses to start if anything blocks, and the Respondent Bot checks its test
package before opening a browser.

### Agent 1: QRE Interpreter

`src/agents/qre_interpretation/`

```bash
python -m src.agents.qre_interpretation.orchestrator fixtures/qre-samples/<QRE>.docx
```

Eight stages. **Part 1** (stages 1 to 5) records what the document says without
interpreting it: ingestion, section matching, word-for-word transcription,
typed parsing, and an audit of the parse against the transcription. **Part 2**
(stages 6 to 8) works out what it means: the Canonical Survey Specification,
an independent check of that specification, and the route graph.

Every value in the specification records where it came from (`extracted`,
`derived`, `inferred`, `unknown` or `ambiguous`), so an inference is never
presented as something the QRE stated. Every model answer is saved in
`agent1_llm_cache.json`, so a document reads the same way on every run and a
re-run costs no model calls.

Exit code 0 means the specification was produced and passed its check; 2
means it was produced but the check found something wrong.

Full detail: [`src/agents/qre_interpretation/README.md`](src/agents/qre_interpretation/README.md).

### Agent 2: Survey Builder

`src/agents/survey_builder/`

```bash
python -m src.agents.survey_builder.build out/<QRE>
```

Reads the specification and writes a `.lss` file that LimeSurvey imports in
one step.

- **Question types:** single choice, multiple choice, free text, grid
  (matrix), constant sum, numeric, and text display.
- **Logic:** display conditions, screening terminations (LimeSurvey has no
  terminate action, so each becomes a gate on later questions and an end
  message chosen by why the respondent stopped), exclusive options, piped
  options, validation ranges and lengths, randomised answers.
- **Before building**, `preflight.py` lists everything it cannot build, all at
  once, and stops if any of it would make a wrong survey.

Import the file under **Surveys, Create, Import**, then activate it.

Full detail: [`src/agents/survey_builder/README.md`](src/agents/survey_builder/README.md).

### Agent 3: Test Designer

`src/agents/test_design/`

```bash
python -m src.agents.test_design.run out/<QRE> --lss out/<QRE>/agent2/agent2_<QRE>.lss
```

`--inputs data/inputs/test_design/<QRE>.json` supplies facts a QRE does not
state, such as sample size; `--sample-size` sets it directly.

| Step | What it does |
|---|---|
| **Load** · `spec.py`, `semantics.py` | Reads the specification and the survey-wide reading rules, with whether each is confirmed |
| **Paths** · `path_enumerator.py` | Lists the distinct respondent journeys, and a smaller set that takes every branch both ways |
| **Targets** · `b1_targets.py` | Every behaviour that can be proven true or false, in nine dimensions that are never added together |
| **Witnesses** · `b2_witness.py` | For each target, the smallest set of answers that reaches it |
| **Oracle** · `b3_oracle.py` | Predicts what the survey should do with those answers. It shares no code with the witness step, so a test and its expected result cannot share a bug |
| **Reconcile** · `b4_reconcile.py` | Decides whether each target is covered |
| **Logical tests** · `compile_logical.py` | Platform-neutral test cases |
| **Implementation check** · `a_implementation.py` | Reads the built `.lss` and checks it against the specification |
| **Executable tests** · `c_compile_executable.py` | Turns logical tests into steps using the survey's real field names and answer codes, and refuses rather than guesses |
| **Reports** · `report.py`, `paths_workbook.py`, `qre_validation_workbook.py` | Review workbooks for sign-off |

Agent 1's ready status is recorded in `agent3_coverage.json`.

### Agent 4: Respondent Bot

`src/agents/respondent_bot/`

```bash
python -m src.agents.respondent_bot.run_browser out/<QRE> --sid <survey id>
```

Opens a browser (Playwright), answers each test's questions as a respondent
would, and records what it saw. Useful options: `--base` for a LimeSurvey other
than `http://localhost:8080` (for example a LimeSurvey Cloud site), `--headed`
to watch it, `--limit N` and `--only <test id>` to run a few tests.

Each test ends in one of five outcomes: **PASSED**, **FAILED**, **BLOCKED** (the
journey could not finish, so nothing was checked), **INCONCLUSIVE** (the check
could not be observed) or **SKIPPED** (needs many respondents, such as a quota).

### Agent 5: QA Adjudicator

`src/agents/qa_adjudication/`

```bash
python -m src.agents.qa_adjudication.adjudicate out/<QRE>
```

A failing test is not necessarily a survey defect. This gives every test that
did not pass one cause and one owner (survey defect, specification error, not
built yet, unsettled question, test model gap or harness fault), and reports
each respondent journey as working, broken or not yet proven, naming the step
where it broke. Writes `agent5_qc_report.xlsx` and `agent5_findings.json`.

## Results on the supported QREs

All 15 QREs go through Agents 1 to 3. Live runs against LimeSurvey:

| QRE | Tests | Passed | Failed | Blocked | Inconclusive | Skipped |
|---|---|---|---|---|---|---|
| S01 | 42 | 42 | 0 | 0 | 0 | 0 |
| M01 | 82 | 68 | 2 | 0 | 9 | 3 |
| C01 | 160 | 133 | 5 | 0 | 17 | 5 |

The failures are real findings about the built survey, chiefly that a
respondent can select "None of these" together with other options.

## Tech stack

| In use | For |
|---|---|
| Python 3.13 | Everything |
| python-docx | Reading QREs |
| Groq, through `instructor` and Pydantic v2 | Structured model answers in Agent 1 |
| NetworkX | Agent 1's route and dependency graphs |
| Playwright | Agent 4's browser |
| openpyxl | Agent 3, 4 and 5 workbooks |
| Streamlit, graphviz | Dashboard |
| pytest | Tests |
| LimeSurvey (Community Edition in Docker, or LimeSurvey Cloud) | The survey platform |

## Repository layout

```
├── CLAUDE.md                 Authoritative project instructions
├── .github/workflows/ci.yml  pytest on Linux and Windows on every push
├── config/.env.example       Template for .env (GROQ_API_KEY, GROQ_MODEL)
├── docs/decisions/           Decision log
├── fixtures/
│   ├── qre-samples/          The 15 supported QREs
│   └── holdout/              QREs kept back to measure how well the pipeline generalises
├── data/inputs/test_design/  Facts a QRE does not state, per survey, for Agent 3
├── out/                      All agent output, one folder per QRE
├── scripts/                  One-off maintenance scripts
├── src/
│   ├── agents/               One package per agent
│   ├── common/llm/           The only place a model provider is called
│   ├── common/paths.py       Every output folder and file name
│   ├── common/readiness.py   The readiness check for Agents 2 to 4
│   └── dashboard/            Streamlit app
└── tests/
    ├── test_conditions.py, test_stage5_content.py, test_stage8_graph.py   Agent 1
    ├── survey_builder/       Agent 2, including a known-good S01 build
    ├── test_design/          Agent 3
    └── test_readiness.py     The readiness check
```

## Getting started

Requires Python 3.13.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # the browser Agent 4 drives
cp config/.env.example .env        # then set GROQ_API_KEY
python -m pytest
```

Agent 1 needs a Groq key in `.env` at the repository root. `.env` is ignored
by git. A key already set in your shell takes precedence over `.env`, so clear
an old one with `unset GROQ_API_KEY` (PowerShell: `Remove-Item
Env:GROQ_API_KEY`). `GROQ_MODEL` in the same file selects the model.

To run the dashboard, install the graphviz binary (`brew install graphviz` or
`apt-get install graphviz`), then:

```bash
PYTHONPATH=. streamlit run src/dashboard/app.py
```

**LimeSurvey.** Run LimeSurvey Community Edition locally in Docker (it serves on
`http://localhost:8080`), or use a LimeSurvey Cloud site with `--base`. Each test
the bot runs submits one response, so on a plan with a response limit, check it
covers the number of tests.

**Long bot runs.** A C QRE takes about 30 minutes. On a Mac, start it with
`caffeinate -i` in front so the machine does not sleep mid-run.

## Working with the QREs

- **Do not develop against `fixtures/holdout/`.** It measures whether the
  pipeline works on documents it was not built against, and reading it
  destroys that measurement (decision 0002).
- **Never place client material in a committed folder.** Confidential QREs and
  ground truth belong in `data/ground_truth/Client/`, which is never committed,
  or outside the repository (`CLAUDE.md` Sections 51 to 53).

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
