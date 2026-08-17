# Escalent Agentic Survey QA Platform

Agent 1 (QRE Interpreter) reads a questionnaire requirement document (QRE) and
turns it into a structured, machine-readable survey specification. This repo
implements **Steps 1, 2 and 4** of Agent 1 Part 1.

Input scope: **`.docx` only.** Authoritative project rules live in `CLAUDE 1.md`.

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

Works without a key: leave it blank or set `LLM_PROVIDER=none`, and every step
falls back to deterministic logic, flagging what it cannot resolve.

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

Prints a per-step summary and writes one JSON artifact per step to
`data/outputs/qre_interpretation/`.

```bash
python3 -m pytest tests/unit/ -q
```

75 tests, no network or key required.

```bash
python3 scripts/benchmark_section_classifier.py
```

Scores the models your Groq account can reach against the Step 2 task. Makes live
calls; run after any prompt change.

### Running one step at a time

No per-step CLI — each step is a function. Steps chain, so Step 4 needs 1 and 2.

```python
import sys; sys.path.insert(0, "src")

from agents.qre_interpretation.ingestion.docx_reader import read_docx
from agents.qre_interpretation.extraction.section_detector import detect_sections
from agents.qre_interpretation.extraction.question_parser import parse_questions

document  = read_docx("fixtures/qre-samples/S01_campus_cafeteria_experience.docx")
sectioned = detect_sections(document)     # Step 2
questions = parse_questions(sectioned)    # Step 4

for q in questions.questions:
    print(q.id, q.type, q.wording)
```

Pass `classifier=` to either step to enable its LLM fallback:

```python
from common.prompts.qre_interpretation import (
    classify_section_heading, classify_table_column,
)
sectioned = detect_sections(document, classifier=classify_section_heading)
questions = parse_questions(sectioned, classifier=classify_table_column)
```

---

## Architecture

```
QRE .docx
    ▼
Step 1  Document ingestion ──────► NormalizedDocument
    │                              ordered paragraphs + tables as grids
    ▼
Step 2  Section detection ───────► SectionedDocument
    │                              {section_label: content_block}
    ▼
Step 3  Study specification        ✗ omitted
    ▼
Step 4  Understand the questions ► list[RawQuestion]
    │                              {id, wording, type,
    ▼                               options_raw, display_validation_raw}
Steps 5–9  per-question logic, routing graph, quotas,     ✗ not built
           acceptance tests, confidence + review queue
    ▼
Step 10    QREExtractionIR                                ✗ not built
```

Part 1 ends at `QREExtractionIR`. Interpreting routing and display *semantics* is
Part 2's job — Part 1 captures what the document says, Part 2 decides what it
means.

### Four rules that shape the code

1. **Extraction never interprets.** `"Yes; No"` stays one string; `Validate:
   {...}` is not parsed; `"—"` is not turned into "no options". Splitting and
   parsing belong to Step 5.
2. **Nothing is silently dropped.** Unrecognized headings, unmapped columns and
   unreadable content are preserved and pushed to a review queue.
3. **Deterministic first, LLM only where semantics are genuinely required.**
4. **No single point of failure.** Every recognition task has layered fallbacks,
   and each fallback that fires is reported, not passed off as fact.

Every extracted value carries provenance (`source_reference`) back to a position
in the source document.

### Handling an unfamiliar QRE

Nothing depends on the sample corpus's wording. Both steps degrade in stages and
record which stage they used.

**Step 2 — naming a section:** heading matches the vocabulary (`extracted`) → LLM
classifies it (`inferred`) → neither, content preserved and flagged (`unknown`).

**Step 4 — finding the table and reading its columns:**

| | Mechanism | Cost |
|---|---|---|
| 1 | Table in the section Step 2 labelled `questionnaire` | free |
| 2 | Else any table anywhere with an identifiable id **and** wording column | free |
| 3 | Column header matches the alias vocabulary, by token coverage | free |
| 4 | LLM classifies headers the vocabulary could not place | 1 call per unknown header |
| 5 | Required role still missing → inferred from **value shape**: short unique code-like values are an id; longest sentence-like column is wording | free, sends nothing |
| 6 | Still unresolved → no questions extracted, reported plainly | — |

Stage 5 is why extraction works with **no model at all** on a QRE whose columns
are named nothing like the samples: a column headed "Marker" is unidentifiable
from its header, but values `A_01, A_02, A_03` settle it. That keeps the
capability usable on confidential QREs where sending cell content is not
acceptable.

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
│   │   ├── ingestion/               Step 1
│   │   │   ├── docx_reader.py
│   │   │   └── normalized_document.py
│   │   └── extraction/              Steps 2 and 4
│   │       ├── section_detector.py
│   │       ├── sectioned_document.py
│   │       ├── question_parser.py
│   │       ├── raw_question.py
│   │       └── label_matching.py
│   └── common/                      shared infrastructure
│       ├── config.py
│       ├── llm/groq_client.py
│       └── prompts/qre_interpretation.py
│
├── fixtures/qre-samples/            QRE corpus (17 .docx)
│   ├── S01–S05  simple    (10 questions each)
│   ├── M01–M06  medium    (19 questions each)
│   ├── C01–C04  complex   (31 questions each)
│   └── Z01–Z02  adversarial, hand-written for generalization testing
│
├── tests/unit/                      75 tests
├── scripts/                         dev tooling
├── docs/decisions/                  decision log
└── data/outputs/                    generated artifacts (gitignored)
```

Contracts live beside the step that produces them (`normalized_document.py`,
`sectioned_document.py`, `raw_question.py`) and hold only dataclasses, no logic.

---

## File index

| File | What it does | In → Out |
|---|---|---|
| `run_pipeline.py` | Runs each implemented step, prints summaries, writes JSON. No extraction logic of its own. | `.docx` path → stdout + JSON |
| **Step 1** | | |
| `ingestion/docx_reader.py` | Reads a `.docx` into ordered blocks, walking the body XML so paragraphs and tables keep their true interleaved order. Raises `DocxReadError` rather than returning partial output. | path → `NormalizedDocument` |
| `ingestion/normalized_document.py` | Contract: `NormalizedParagraph` (text, `style_name`, `is_bold`), `NormalizedTable` (`rows` grid), `SourceReference`. | — |
| **Step 2** | | |
| `extraction/section_detector.py` | Finds headings by Word style, matches them to a known section vocabulary, slices the document at heading boundaries. Optional LLM handles headings the vocabulary misses; the rest are flagged. | `NormalizedDocument` → `SectionedDocument` |
| `extraction/sectioned_document.py` | Contract: `Section`, `ReviewItem`, `SectionedDocument` (`.by_label()` gives the `{label: blocks}` dict). | — |
| **Step 4** | | |
| `extraction/question_parser.py` | Parses the question table row by row. Resolves columns to roles in the layers above, finds the table even when Step 2 could not name its section, flags duplicate ids and inferred roles. | `SectionedDocument` → `QuestionExtraction` |
| `extraction/raw_question.py` | Contract: `RawQuestion` (the five specified fields + provenance), `ExtraColumn`, `QuestionExtraction`. | — |
| **Shared** | | |
| `extraction/label_matching.py` | `score_label` matches a label to a vocabulary by token-subsequence coverage, so "Base / Validation" matches the alias "validation". Used by Steps 2 and 4. | label + vocabulary → `{canonical: score}` |
| `common/config.py` | Loads settings from environment and `.env`. `Settings.llm_enabled` is true only with a provider *and* a key. Masks the key in every repr. | — → `Settings` |
| `common/llm/groq_client.py` | The only module touching a provider SDK, so the runtime is auditable and swappable in one place. Temperature 0 + JSON mode. | prompts → parsed JSON |
| `common/prompts/qre_interpretation.py` | Agent 1's prompts, each version-stamped. `classify_section_heading` and `classify_table_column` match the steps' classifier signatures and return `None` rather than guessing. | text + options → label or `None` |
| `scripts/benchmark_section_classifier.py` | Scores available models on Step 2 classification, reporting synonym recall and decline rate separately. | — → per-model report |

---

## Configuration

`.env` (gitignored); `.env.example` is the template. Real environment variables
override the file.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `none` | `groq` to enable model calls, `none` for deterministic-only |
| `GROQ_API_KEY` | *(empty)* | Blank = LLM disabled |
| `GROQ_MODEL` | `qwen/qwen3.6-27b` | Best on this account (13/13 on the benchmark) |
| `GROQ_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `GROQ_MAX_RETRIES` | `2` | Retries on transient failure |

**What reaches the provider:** section headings and column headers only — never
question wording, options, routing rules or cell content.

**Groq is a logged deviation.** `CLAUDE.md` §52 names Azure OpenAI as the approved
runtime; Groq is interim, at the project team's direction. Rationale, model
benchmark and revisit triggers:
[`docs/decisions/0001`](docs/decisions/0001-groq-as-interim-llm-runtime.md).
Steps depend on a callable signature, not on Groq, so switching providers touches
only the prompt layer.

---

## Verified output

### The 15-QRE corpus

Run with `LLM_PROVIDER=none` — **entirely deterministic, zero model calls.**

| Tier | Files | Sections | Questions each | Step 4 review items |
|---|---|---|---|---|
| Simple | S01–S05 | 7 | 10 | 0 |
| Medium | M01–M06 | 8 | 19 | 0 |
| Complex | C01–C04 | 8 | 31 | 0 |

**288 questions extracted, 0 unclassified sections, 0 Step 4 review items.** The
only flags raised are 5 × `known_section_not_found` for `quota_controls` on the
simple QREs, which genuinely have no quota section.

Quality holds on the complex tier: `matrix` and `constant_sum` question types,
multi-line display/validation cells, and matrix row/scale notation all arrive
verbatim with newlines intact — unsplit and unparsed, as Step 5 requires.

### Adversarial fixtures

Hand-written to break the deterministic paths and exercise the fallbacks:

| Fixture | Built to defeat | Result |
|---|---|---|
| `Z02_different_naming` | Heading 2, unfamiliar section names, 6 columns reordered + 1 extra | 5 questions; 3 section labels LLM-inferred, `Q No`→`id`, `Base / Validation`→`display_validation_raw` |
| `Z01_hostile_naming` | Heading 3, unclassifiable section, 6 headers matching nothing | 3 questions — table found without a section name, `id` inferred from value shape; works with no LLM at all |

No content is lost between steps: on S01, Step 1's 25 blocks = 19 section-content
blocks + 6 headings consumed as section titles.

---

## Known gaps

Ordered by how much they matter.

1. **No independent ground truth.** Tests verify the pipeline is self-consistent,
   not that its output is *correct*. `CLAUDE.md` §33 requires ground truth
   produced independently of the system under test; none exists. Largest gap, and
   not closable by adding tests.
2. **The corpus is synthetic.** 15 QREs across three complexity tiers is real
   coverage, but no actual Escalent QRE has been processed. They also share one
   house style — the two adversarial fixtures exist because the corpus does not
   vary its section or column naming.
3. **Value-shape inference is a heuristic.** It reads column shape, not meaning: a
   table whose id column repeats values, or whose longest column is a notes
   field, will mis-infer. It fires only when a required role is otherwise
   unidentifiable and always reports itself — treat those rows as needing review.
4. **No run ledger.** Model and prompt version print to stdout but are not
   persisted; document hash, code version and run ID are absent, so a run is not
   reproducible from its artifact alone (§50).
5. **Contracts are unversioned.** Fine while they move; a liability once Step 10
   consumes them.
6. **Step 3 not built** (omitted by request). Step 10 will need its `StudySpec` —
   objective, population, mode, length, standing instructions.
7. **Step 4 reads tables only.** A QRE listing questions as numbered prose is
   reported, not parsed. Deliberately not built — without a real example, both the
   format and the parser would be guesswork.
8. **Sub-heading nesting.** `Heading 2` under `Heading 1` becomes a sibling
   section, not a child.
9. **Hosted-model drift.** Temperature 0 is deterministic per model version, but a
   hosted model is not a frozen artifact. Model ID is recorded so drift is
   detectable, not prevented.
