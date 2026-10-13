# Maintaining the pipeline

For whoever runs, fixes or extends the pipeline. The README covers setup and
what each agent does. This covers what to do when something goes wrong, and how
to support a QRE in a different format. The reasons behind the design are in
[`principles.md`](principles.md), and the format the pipeline reads today is in
[`qre-format.md`](qre-format.md).

## Running a QRE end to end

```bash
python -m src.agents.qre_interpretation.orchestrator fixtures/qre-samples/<QRE>.docx
python -m src.agents.survey_builder.build out/<QRE>
python -m src.agents.test_design.run out/<QRE> --lss out/<QRE>/agent2/agent2_<QRE>.lss
```

Import `out/<QRE>/agent2/agent2_<QRE>.lss` into LimeSurvey, activate it, note
its survey id, then:

```bash
python -m src.agents.respondent_bot.run_browser out/<QRE> --sid <survey id>
python -m src.agents.qa_adjudication.adjudicate out/<QRE>
```

Every output lands in `out/<QRE>/agent<N>/`, named after its agent. All names
are set in `src/common/paths.py`.

**After a change to Agent 2**, re-import the survey: LimeSurvey keeps the
version it was given. **After a change to Agent 1 or 2**, re-run Agent 3, since
its tests are compiled from both.

## When something goes wrong

### Agent 1 exits with code 2

Stage 7 found the specification disagreeing with the document. The run prints
the findings, and `agent1_s7_validation.json` lists them under `cross_source`.
Each names a check (such as `invented_validation`) and a question or rule.
Either the document says something Part 2 did not read, or Part 2 added
something the document does not say. Fix the reading, never the check.

### `agent1_ready.json` says BLOCKED

Usually a decision is waiting for a person. Open
`out/<QRE>/agent1/agent1_s7_decision_register.md`. Each entry gives the
current reading, the alternatives and what depends on it. To resolve one,
edit its entry in `agent1_s7_decisions.json`:

```json
"status": "RESOLVED",
"decision": "Open-source alternative counts as a brand",
"decision_provenance": "Sameer Saurabh, 14 Oct 2026"
```

Then re-run Agent 1. The ruling is kept on later runs until the document
changes, when it comes back for confirmation. Resolving records the ruling and
lifts the block. If the ruling differs from the current reading, also correct
the QRE wording so the reading follows it.

Agents 2 to 5 still run while Agent 1 is BLOCKED. The status is copied into
Agent 3's coverage file so results can be read with it in mind.

### The readiness check reports a gap

```bash
python -m src.common.readiness out/<QRE>
```

`BLOCKS` means an agent cannot handle something in this QRE (an unknown
question type, say) and its runs would fail. `note` means something will be
skipped or simplified, and says what. Each gap names its question or rule. See
"Supporting a new QRE format" below for where each agent's support lives.

### A model call fails

Agent 1 calls the model through `src/common/llm/groq_client.py`.

- **Rate limits:** a per-minute limit is waited out; a per-day limit stops
  the run. Re-run later. Answers already given are cached, so nothing is
  asked twice.
- **Cut-off answers** are retried with more room, up to 8,000 tokens.
- **A reading looks wrong:** every answer is in `agent1_llm_cache.json` with
  the text it was asked about. To ask again, run with `QRE_LLM_CACHE=off` in
  front of the command. A changed prompt asks again on its own.

To use another provider, add a client beside `groq_client.py` and switch to
it there. No agent imports a provider directly.

### Reading Agent 5's report

Agent 5 gives each test that did not pass one cause and one owner:

| Cause | Meaning | Action |
|---|---|---|
| SURVEY_DEFECT | The built survey does the wrong thing | Fix the survey, or Agent 2 |
| SPECIFICATION_ERROR | The QRE was read wrongly | Fix Agent 1's reading |
| NOT_BUILT_YET | Agent 2 does not build this yet, and said so before the run | None on the test; it is on the builder's list |
| UNSETTLED_QUESTION | It depends on a decision nobody has made | Resolve the decision |
| COVERAGE_GAP | The bot reached the place but cannot observe this claim | Teach the bot, or accept the gap |
| TEST_MODEL_GAP | The bot reached the place but the test gave it nothing it could check | Give the test something observable |
| NEEDS_SAMPLE | Needs many respondents, such as random order or quotas | None in a single run |
| HARNESS_FAULT | The journey never reached what it tested | Fix the bot, then re-run the test |
| UNDECIDED | Nothing above explains it | Read the test's actions and decide by hand |

To re-run one test: `--only <test id>`. A BLOCKED test is retried once
automatically. Note that `--only` overwrites `agent4_results.json` with that
single result, so restore the full file afterwards
(`git checkout -- out/<QRE>/agent4`).

## Supporting a new QRE format

Run the new QRE through Agent 1 first and read what it reports. Stage 2 lists
sections it could not match, Stage 5 scores how much of each section became
data, and review items mark every line that needed the model. Then work
through the agents in order. Most changes are an entry in a table.

### Agent 1: reading the document

| What differs | Where to change it |
|---|---|
| A section is named differently | Nothing, usually. Unmatched headings are matched by content shape. To add a section kind, extend `TargetHeading` in `models.py` and describe its shape in `_TARGET_SHAPES` in `stage2_headings.py` |
| Table columns are named differently | The keyword lists in `stage4_deep_parse.py` (`_QUESTION_HINTS`, `_ROUTING_HINTS`, `_SCENARIO_HINTS`). Columns are matched by meaning, so add words, never exact names |
| Instruction lines use other wording | `_LABELLED_LINES` in `stage4_deep_parse.py`, one pattern per form. Lines matching no pattern still work, through the model, but cost a call each |
| A new `Validate:` key | Read it in `_apply_validation` in `stage4_deep_parse.py`, and add it to `_VALIDATION_ALIASES` in `stage7_tests.py` so Stage 7 recognises it as stated. Missing the second step makes Stage 7 report the value as invented |
| A new question type | The type is carried through as written. Add it to the agents below. If it asks nothing, add it to `DISPLAY_KINDS` in `models.py` |
| A new condition form | Conditions already in the grammar are read by code. Prose goes to the model, which is told the grammar in `stage6_conditions.py`. Extend the grammar there and in its parser |

After a change, re-run Agent 1 on the 15 corpus QREs (cached, so free) and
check every one still exits 0.

### Agent 2: building the survey

| What differs | Where to change it |
|---|---|
| A new question type | `_TYPE_MAP` in `survey_builder/loader.py`, plus `emitter.py` if it needs its own attributes or theme |
| Randomisation of a new type | `SHUFFLE_SETTINGS` in `loader.py` |
| A new condition operator | `SUPPORTED_OPS` and `_relevance` in `loader.py` |

Never guess LimeSurvey's settings. Build the question by hand in LimeSurvey,
export the survey as `.lss`, and read what it wrote. Each question type uses
different attribute names: randomising a single choice, a multiple choice
and a grid's rows takes three different settings.

If the S01 build changes on purpose, update
`tests/survey_builder/S01_expected.lss` to match.

### Agent 3: designing the tests

| What differs | Where to change it |
|---|---|
| A new question type | `SUPPORTED_KINDS` in `test_design/b2_witness.py`, with answers for it in `_concretise` and `_fill_journey` |
| How its answer is written into the survey | `VALUE_KIND_BY_TYPE` in `c_compile_executable.py` |
| A new condition operator | `SUPPORTED_CONDITIONS` in both `b2_witness.py` (making it true or false) and `b3_oracle.py` (predicting the outcome) |
| A new LimeSurvey setting to verify | `a_implementation.py`, which checks the built survey against the specification |

### Agent 4: the respondent bot

A new kind of answer needs a branch in `Bot.fill` in
`respondent_bot/run_browser.py` and its name in `FILLABLE_VALUE_KINDS`. A new
kind of check needs a branch in `observe`. Test page handling against a local
HTML page with Playwright before a live run: a live run submits real
responses.

### Agent 5: the report

A new finding kind from Agent 3 that means "not built yet" goes in the list in
`_decide` and, if it concerns only some tests, in `_explains`, both in
`qa_adjudication/adjudicate.py`.

### Worked example: a dropdown question

A QRE marks a question `dropdown`:

1. **Agent 1** carries `dropdown` as the kind. If the QRE's type column uses
   another word, nothing else changes.
2. **Agent 2:** build a dropdown in LimeSurvey by hand, export it, and read
   its type letter and any attributes. Add `"dropdown": "<letter>"` to
   `_TYPE_MAP`, and to `SHUFFLE_SETTINGS` if it can be randomised.
3. **Agent 3:** add `dropdown` to `SUPPORTED_KINDS` and answer it like a
   single choice in `_concretise` and `_fill_journey`. Map its type letter in
   `VALUE_KIND_BY_TYPE`.
4. **Agent 4:** a dropdown is a `<select>`, not radio buttons, so `Bot.fill`
   needs a branch that picks the option from the list.
5. Run `python -m src.common.readiness out/<QRE>`. Each agent's declarations
   feed it, so it now reports nothing for the dropdown.
6. Run the pipeline on one QRE that uses it, and add that QRE to the corpus.

## Tests and the corpus

- `python -m pytest` runs the unit tests. CI runs them on every push, on
  Linux and Windows.
- `fixtures/qre-samples/` is the development corpus. A new format earns a new
  sample here once it works.
- `fixtures/holdout/` is for measuring, never for developing (principle 10).
- Client QREs never go in a committed folder (principle 12).
