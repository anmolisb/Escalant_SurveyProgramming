# Escalent Agentic Survey QA Platform

Agent 1 (the QRE Interpreter) reads a questionnaire requirement document — the
Word file that tells a survey programmer what to build — and turns it into
structured data a machine can act on.

This repo implements **Steps 1, 2, 4 and 5** of Agent 1 Part 1. Input scope is
**`.docx` only**.

---

## Setup

```bash
pip3 install -r requirements.txt
```

```bash
cp .env.example .env
```

Add your Groq key to `.env` (`GROQ_API_KEY=…`, from
<https://console.groq.com/keys>). `.env` is gitignored — never commit a key.

The pipeline runs without a key. Leave it blank or set `LLM_PROVIDER=none`, and
every step falls back to its deterministic path, flagging anything it cannot
work out on its own.

---

## How to run

```bash
python3 run_pipeline.py
```

Defaults to `fixtures/qre-samples/S01_campus_cafeteria_experience.docx`. For your
own file:

```bash
python3 run_pipeline.py path/to/your.docx
```

Prints a summary of each step and writes one JSON artifact per step to
`data/outputs/qre_interpretation/`.

```bash
python3 -m pytest tests/unit/ -q
```

138 tests. No network or API key needed: `tests/conftest.py` forces
`LLM_PROVIDER=none` for the whole session, and the tests that exercise the model
path inject their own stub.

```bash
python3 scripts/benchmark_section_classifier.py
```

Scores the models your Groq account can reach against the Step 2 task. Makes
live calls, so run it after changing a prompt, not routinely.

### Running one step at a time

Each step is a plain function, and they chain — Step 5 needs 1, 2 and 4 first.

```python
import sys; sys.path.insert(0, "src")

from agents.qre_interpretation.ingestion.docx_reader import read_docx
from agents.qre_interpretation.extraction.section_detector import detect_sections
from agents.qre_interpretation.extraction.question_parser import parse_questions
from agents.qre_interpretation.extraction.question_logic import build_questions

document  = read_docx("fixtures/qre-samples/S01_campus_cafeteria_experience.docx")
sectioned = detect_sections(document)              # Step 2
extracted = parse_questions(sectioned)             # Step 4
logic     = build_questions(extracted.questions)   # Step 5

for q in logic.questions:
    print(q.id, q.type, [o.label for o in q.options], q.display_condition)
```

**The LLM is wired in automatically.** Each step reaches for the configured
model on its own when its deterministic path runs out, so the calls above already
use it if a key is set. Nothing needs passing in.

To force a step to stay deterministic, pass `None`:

```python
sectioned = detect_sections(document, classifier=None)
extracted = parse_questions(sectioned, classifier=None)
logic     = build_questions(extracted.questions, converter=None)
```

Or set `LLM_PROVIDER=none` to disable it everywhere. To substitute your own
implementation, pass a callable in place of `None`.

---

## What each step does

```
QRE .docx
    ▼
Step 1   Read the document ──────────► NormalizedDocument
    ▼
Step 2   Find the sections ──────────► SectionedDocument
    ▼
Step 3   Study specification            ✗ skipped
    ▼
Step 4   Read the question table ─────► list[RawQuestion]
    ▼
Step 5   Interpret each question ─────► list[Question]
    ▼
Steps 6–9   routing graph, quotas, acceptance tests, confidence   ✗ not built
    ▼
Step 10     QREExtractionIR                                       ✗ not built
```

**Step 1 — Read the document.** Pulls out every paragraph and table in the order
they appear, keeping tables as row/column grids rather than flattening them to
text. It records each paragraph's Word style and whether it is bold, because
later steps use those to work out the document's shape.

**Step 2 — Find the sections.** A QRE is organised under headings: study
specification, questionnaire, routing, quotas, and so on. This step finds the
headings, works out which known section each one is, and slices the document at
those boundaries. A heading it cannot place is kept and flagged, never guessed.

**Step 4 — Read the question table.** Goes through the questionnaire table row by
row and pulls out each question's id, wording, type, options and instructions —
as written, without interpreting them. It also **separates the instruction cell**:
a single cell often holds a display rule, a validation rule and a randomisation
note on separate lines, and the survey builder needs those apart, not as one
string.

**Step 5 — Interpret each question.** Turns Step 4's strings into structures that
can actually be acted on:

| Step 4 gives | Step 5 produces |
|---|---|
| `"Yes; No"` | a list of two options |
| `"1 - Very poor; 2 - Poor"` | options carrying the codes `1` and `2` |
| `"Rows: Access; Comms⏎Scale: 1 - Poor…"` | a matrix with rows and a shared scale |
| `'Validate: {"min_length": 10}'` | a decoded rule `{min_length: 10}` |
| `"Show if: Q5 == 'Yes'"` | `equals(Q5, "Yes")` |
| `"Show if: Q7 contains any problem"` | `contains_any(Q7, [the actual problem options])` |

That last row is the interesting one. A survey builder cannot act on "contains
any problem" — it needs to know *which* options count as a problem. Step 5 looks
up the options Q7 actually offers and resolves the phrase against them.

### What is not here yet

Step 5 covers the logic written **on each question's own row**. It does not cover
the separate routing table (`Rule | Condition | Action | Destination`), which is
Step 6's job — and Step 6 does more than read it. It cross-checks the two
against each other, since the same rule is often stated in both places, and a
disagreement between them is a genuine defect in the QRE worth surfacing.

Of the eight sections Step 2 finds, only `questionnaire` feeds anything so far.
The rest are already extracted and waiting: `routing_and_termination` and
`completion_messages` for Step 6, `quota_controls` for Step 7,
`acceptance_test_scenarios` for Step 8.

**This is not what goes into LimeSurvey.** Three transformations remain: Steps
6–10 produce `QREExtractionIR`, Part 2 turns that into a platform-neutral survey
specification, and only then does Agent 2 generate LimeSurvey XML. Nothing in
this repo knows LimeSurvey exists — deliberately, so Agent 1 stays reusable if
the platform changes.

---

## Four rules that shape the code

1. **Read before you interpret.** Step 4 stores what the document says; Step 5
   decides what it means. Keeping those apart means a wrong interpretation can
   always be checked against the original text.
2. **Never drop anything silently.** Unrecognised headings, unmapped columns and
   unreadable instructions are all preserved and added to a review queue.
3. **Deterministic code first; the model only where meaning is genuinely
   required.** Each step calls the model itself, but only after its deterministic
   path runs out. Across the 15-QRE corpus that means 14 calls in total, all in
   Step 5 — Steps 1, 2 and 4 make none, because every heading and column name
   matches without help.
4. **No single point of failure.** Every recognition task has fallbacks, and each
   fallback that fires says so rather than passing its guess off as fact.

Every extracted value carries a `source_reference` pointing back to where it came
from in the document.

### How the steps cope with an unfamiliar QRE

Nothing depends on the sample corpus's exact wording. Each step degrades in
stages and records which stage it used.

**Step 2, naming a section:** the heading matches a known name → a model
classifies it → neither, so it is flagged and its content kept.

**Step 4, finding the table and its columns:**

| | How | Cost |
|---|---|---|
| 1 | The table in the section Step 2 called `questionnaire` | free |
| 2 | Otherwise any table with a recognisable id **and** wording column | free |
| 3 | Column header matches a known name | free |
| 4 | A model classifies headers the names did not cover | one call per header |
| 5 | Still missing a required column → work it out from the **values**: short unique codes are ids, the longest sentence-like column is wording | free, sends nothing |
| 6 | Still stuck → extract nothing, say so plainly | — |

Stage 5 is why a QRE whose columns are named nothing like the samples still
parses with no model at all. A column headed "Marker" says nothing useful, but
values `A_01, A_02, A_03` settle it.

**Step 5, converting a display condition:** operator forms like `==`, `!=` and
`in [...]` are parsed directly → prose like "contains any touchpoint" goes to a
model along with the referenced question's options → otherwise flagged. On the
corpus, 200 of 224 conditions (89%) resolve with no model.

---

## Folder structure

```
.
├── run_pipeline.py                  ← the file you run
├── requirements.txt
├── .env / .env.example              config (.env is gitignored)
│
├── src/
│   ├── agents/qre_interpretation/
│   │   ├── ingestion/                       Step 1
│   │   │   ├── docx_reader.py
│   │   │   └── normalized_document.py
│   │   └── extraction/                      Steps 2, 4, 5
│   │       ├── section_detector.py          Step 2
│   │       ├── sectioned_document.py
│   │       ├── question_parser.py           Step 4
│   │       ├── raw_question.py
│   │       ├── instruction_splitter.py      Step 4 — separates the instruction cell
│   │       ├── question_logic.py            Step 5
│   │       ├── question.py
│   │       └── label_matching.py            shared by Steps 2 and 4
│   └── common/
│       ├── config.py                        .env loading
│       ├── llm/groq_client.py               the only module touching a provider SDK
│       └── prompts/qre_interpretation.py    all three prompts, version-stamped
│
├── fixtures/qre-samples/            17 .docx
│   ├── S01–S05  simple    (10 questions each)
│   ├── M01–M06  medium    (19 questions each)
│   ├── C01–C04  complex   (31 questions each)
│   └── Z01–Z02  adversarial, written to break the deterministic paths
│
├── tests/
│   ├── conftest.py                  forces LLM off for the test session
│   └── unit/                        138 tests
├── scripts/                         dev tooling
├── docs/decisions/                  decision log
└── data/outputs/                    generated artifacts (gitignored)
```

Each step keeps its data definitions in a file next to its logic
(`normalized_document.py`, `sectioned_document.py`, `raw_question.py`,
`question.py`). Those files hold dataclasses only, no behaviour.

---

## File index

| File | What it does | In → Out |
|---|---|---|
| `run_pipeline.py` | Runs each step in order, prints summaries, writes JSON. No extraction logic of its own. | `.docx` path → stdout + JSON |
| **Step 1** | | |
| `ingestion/docx_reader.py` | Reads a `.docx` into ordered blocks, walking the document XML so paragraphs and tables keep their real interleaved order. Raises rather than returning partial output. | path → `NormalizedDocument` |
| `ingestion/normalized_document.py` | `NormalizedParagraph` (text, style, bold), `NormalizedTable` (row/column grid), `SourceReference`. | — |
| **Step 2** | | |
| `extraction/section_detector.py` | Finds headings by Word style, matches them to known section names, slices the document at those boundaries. Optional model handles headings the names miss. | `NormalizedDocument` → `SectionedDocument` |
| `extraction/sectioned_document.py` | `Section`, `ReviewItem`, `SectionedDocument` (`.by_label()` gives `{label: blocks}`). | — |
| **Step 4** | | |
| `extraction/question_parser.py` | Reads the question table row by row, matching columns to roles, finding the table even when Step 2 could not name its section. | `SectionedDocument` → `QuestionExtraction` |
| `extraction/instruction_splitter.py` | Splits an instruction cell on its line breaks and labels each line — display condition, validation, randomisation, piping, optionality. | cell text → `tuple[Instruction, …]` |
| `extraction/raw_question.py` | `RawQuestion` (the five specified fields plus the separated instructions), `ExtraColumn`, `QuestionExtraction`. | — |
| **Step 5** | | |
| `extraction/question_logic.py` | Splits option lists, parses matrix rows/scale, decodes validation JSON, converts display conditions into typed operators. | `list[RawQuestion]` → `QuestionLogic` |
| `extraction/question.py` | `Question`, `Option`, `ValidationRule`, `DisplayCondition`, `MatrixSpec`, `QuestionLogic`. | — |
| **Shared** | | |
| `extraction/label_matching.py` | Matches a label to a known name by how much of it the name covers, so "Base / Validation" matches "validation". Used by Steps 2 and 4. | label + names → `{name: score}` |
| `common/config.py` | Loads settings from the environment and `.env`. The API key is masked in every printed form. | — → `Settings` |
| `common/llm/groq_client.py` | The single place a provider SDK is touched, so the runtime can be audited and swapped from one file. Temperature 0, JSON mode. | prompts → parsed JSON |
| `common/prompts/qre_interpretation.py` | The three prompts — section heading, table column, display condition — each version-stamped, each returning `None` rather than guessing. | text + options → answer or `None` |
| `scripts/benchmark_section_classifier.py` | Scores available models on Step 2, reporting how often they match correctly and how often they correctly decline. | — → per-model report |

---

## Configuration

Settings live in `.env` (gitignored); `.env.example` is the template. A real
environment variable always beats the file.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `none` | `groq` to enable model calls, `none` for deterministic only |
| `GROQ_API_KEY` | *(empty)* | Blank means the LLM is disabled |
| `GROQ_MODEL` | `qwen/qwen3.6-27b` | Best on this account — 13/13 on the benchmark |
| `GROQ_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `GROQ_MAX_RETRIES` | `2` | Retries on a transient failure |

**What is sent to the provider:** section headings, column headers, and a display
condition with the option labels it references. Never question wording, never
document content, never respondent data.

**Groq is a recorded deviation.** `CLAUDE.md` §52 names Azure OpenAI as the
approved runtime; Groq is interim, at the project team's direction. The
reasoning, the model benchmark and the conditions for revisiting it are in
[`docs/decisions/0001`](docs/decisions/0001-groq-as-interim-llm-runtime.md).
Steps depend on a function signature rather than on Groq, so switching provider
touches only the prompt layer.

---

## Verified output

### The 15-QRE corpus

Run with `LLM_PROVIDER=none` — entirely deterministic, no model calls at all.

| Tier | Files | Sections | Questions each |
|---|---|---|---|
| Simple | S01–S05 | 7 | 10 |
| Medium | M01–M06 | 8 | 19 |
| Complex | C01–C04 | 8 | 31 |

**288 questions. 0 unclassified sections. 0 review items.**

- 364 instruction lines separated, every one classified, none lost
- 1,153 options parsed, 4 matrices, all 69 validation payloads decoded
- 200 of 224 display conditions (89%) converted with no model; the remaining 24
  are prose, which the model resolves

### Adversarial fixtures

Written to break the deterministic paths:

| Fixture | Built to defeat | Result |
|---|---|---|
| `Z02_different_naming` | Unfamiliar section names, columns reordered with an extra one | 5 questions; section labels resolved by the model, `Q No`→`id`, `Base / Validation`→`display_validation_raw` |
| `Z01_hostile_naming` | Unclassifiable section, six headers matching nothing | 3 questions — table found without a section name, `id` worked out from the values; runs with no model at all |

Between them they raise 6 unclassified sections and 8 review items — every
fallback firing and saying so, which is the point of the fixtures.

---

## Known gaps

Ordered by how much they matter.

1. **No independent ground truth.** The tests confirm the pipeline is
   self-consistent, not that its output is *correct*. `CLAUDE.md` §33 asks for
   ground truth produced independently of the system being tested, and none
   exists yet. This is the biggest gap and more tests will not close it.
2. **The corpus is synthetic.** 15 QREs across three complexity tiers is real
   coverage, but no actual Escalent QRE has been processed, and they all share
   one house style.
3. **Working a column out from its values is a heuristic.** It reads shape, not
   meaning: a table whose id column repeats values, or whose longest column is a
   notes field, will get it wrong. It only runs when a required column cannot be
   identified any other way, and always says when it has — treat those rows as
   needing a look.
4. **Model judgment on prose conditions needs review.** On "Q1 contains at least
   one brand" the model returned three named brands and excluded "Independent
   provider", which is arguably also selectable. It is marked `inferred` so it is
   traceable, but a human should confirm it.
5. **No run ledger.** The model and prompt version are printed but not saved.
   Document hash, code version and run id are absent, so a run cannot be
   reproduced from its artifact alone (§50).
6. **Contracts are unversioned.** Fine while they are moving; a problem once
   Step 10 depends on them.
7. **Step 3 is not built** (skipped by request). Step 10 will need its study
   specification — objective, population, mode, length, standing instructions.
8. **Step 4 reads tables only.** A QRE listing its questions as numbered prose is
   reported, not parsed. Deliberately not built: with no real example, both the
   format and the parser would be guesswork.
9. **Sub-heading nesting.** A `Heading 2` under a `Heading 1` becomes a sibling
   section rather than a child.
10. **Hosted models drift.** Temperature 0 is deterministic for a given model
    version, but a hosted model is not frozen. The model id is recorded so drift
    is detectable, not prevented.
