# How the QRE Reader works — in plain terms

**Updated:** 18 August 2026 · Covers Agent 1, Part 1

This explains what has been built so far, without assuming you have read the
code. It ends with the complete output for one real sample QRE, so you can see
exactly what the system produces.

---

## The problem in one paragraph

Escalent writes a questionnaire requirement document (a QRE) describing how a
survey should behave. A programmer reads it and builds the survey in a survey
platform. Today, checking that the built survey matches the document is done by
hand, one click-path at a time, and a survey with 18 branch points has more
paths than anyone can click. Before a machine can check the survey, the machine
has to understand the document. **That is all Part 1 does: turn a human-readable
QRE into structured data, without guessing.**

The words "without guessing" are doing a lot of work. A tool that quietly
invents a plausible answer is worse than one that says "I don't know", because
everything downstream will trust it.

---

## The six pieces, in order

Each piece hands its output to the next. Nothing skips ahead.

### 1. Environment — the workbench

*CLAUDE.md Stage 1*

Python, a fixed list of libraries with exact version numbers, and automated
tests that run on every change.

Versions are pinned exactly rather than "roughly this or newer" because a
library that silently updates could change what the reader extracts without
anyone changing a line of code. If a result cannot be reproduced, it cannot be
trusted.

### 2. Reading the file — getting words off the page

*Stage 2 · `ingestion/docx_reader.py`, `ingestion/pdf_reader.py`*

**In:** a `.docx` or `.pdf` file. **Out:** the text, the tables, and where each
piece sits in the document.

Word and PDF files are completely different underneath, so each gets its own
reader. Two things it is careful about:

- **Order is preserved.** In Word, paragraphs and tables are stored in separate
  lists — read them naively and every table ends up after every paragraph. That
  matters because position carries meaning: an instruction written under a
  question usually belongs to that question.
- **A scanned PDF is reported, not silently skipped.** If a page is a photo of
  text, the reader says so rather than returning an empty page that looks like a
  successful read.

### 3. One common shape — so later steps don't care about the format

*Stage 3 · `ingestion/normalized_document.py`*

Both readers produce the same structure: a list of text blocks, a list of
tables, and for every single one, a note of exactly where it came from —
document, page, table, row, column.

That "where it came from" is the point. Every later claim can be traced back to
a specific spot in the original document, so a reviewer can always ask "where
did you get that?" and get an answer.

### 4. Finding the survey content — the reader

*Stage 4 · `extraction/reader.py`, `extraction/extractor.py`*

**In:** the common shape. **Out:** questions, answer options, instructions,
sections.

This is the interesting part, and the important thing to understand is what it
**refuses** to do.

Given a cell reading `Show if: Q5 == 'Yes'`, it records: *this is an
instruction, it says exactly those characters, it belongs to question Q6, and it
came from row 7 column 5.* It does **not** work out that this means "only
display Q6 when Q5 was answered Yes". That interpretation is deliberately left
to a later stage, so that a mistake in reading and a mistake in understanding
never get mixed together.

It also does not assume a QRE looks like the samples we have. The sample
documents put questions in a table headed `ID / Wording / Type / Options /
Display`. Reading those five names directly would work perfectly on every
document we own — and break on the first real Escalent QRE. So the column names
live in a settings file (`config/extraction_patterns.toml`), and if a document
uses headers the system does not recognise, it keeps the table intact and asks a
human rather than guessing.

Three rules it never breaks:

| Rule | Why |
|---|---|
| Nothing is thrown away | Anything it cannot classify is kept and marked "unparsed". You cannot notice content that was silently deleted. |
| Instructions are kept word for word | Tidying up the wording is already interpreting it. |
| No invented answer codes | If the QRE gives an option without a number, the number stays empty. A made-up code looks exactly like a real one. |

### 5. The output format — a fixed structure downstream can rely on

*Stage 5 · `common/schemas/qre_extraction.py`*

The result is a single structured file (the "extraction IR"). It holds the
questions, options, instructions, sections, everything unparsed, a list of
things needing human review, and a confidence score for each item — **with the
reason attached**, not just a number. "0.9 because 4 of 5 column headers matched
and this came from a question table" can be checked; "0.9" cannot.

This format is version-stamped and currently marked **0.1.0 — not final**. It
gets frozen once we have measured whether it is the right shape.

### 6. Checking the result — validation

*Stage 6 · `validators.py`*

Before anything is trusted, fourteen automatic checks run over it. They split
into two kinds:

- **Errors** — the output is broken. Two questions with the same ID, a question
  with no ID and no wording, an answer option with a blank label. Anything with
  an error is blocked from going further.
- **Warnings** — it looks odd and a human should glance at it. An instruction
  mentioning a question that was never found, or options where only some have
  codes.

The split is deliberate. If an instruction refers to a question that does not
exist, that might be a mistake in the QRE itself rather than a mistake by the
reader — so it is raised for a person, not treated as a failure.

### And the one that is not built yet: measuring whether it is right

*Stages 7–8 · ground truth*

Everything above proves the reader is **consistent**. None of it proves the
reader is **correct**. To know that, people have to read the QREs themselves and
write down what the questions actually are, and then we compare.

Blank worksheets are ready and the scoring tool is written. **Nobody has filled
them in yet, so the accuracy of this system is currently unknown** — not high,
not low, unknown. It cannot be claimed until it is measured.

---

## A real example: `S01_campus_cafeteria_experience.docx`

A short QRE: some background text, one table of 10 questions, a table of routing
rules, and a table of test scenarios.

### What goes in

```
[Normal]     S01 • SIMPLE
[Normal]     Campus Cafeteria Experience
[Heading 1]  Study specification
[Normal]     Business objective: Measure satisfaction and identify operational...
[Heading 1]  Questionnaire

  ID | Wording / instruction              | Type   | Options / scale | Display / validation
  S1 | Have you purchased food or a bev.. | single | Yes; No         | Always show
  Q5 | Did you encounter a problem?       | single | Yes; No         | Always show
  Q6 | Please describe the main problem.  | text   | —               | Show if: Q5 == 'Yes'
```

### What comes out

**10 questions**, each with its type, options, instruction and section:

```
S1  [single]  conf=0.9  Have you purchased food or a beverage from the campus...
      options: ['Yes', 'No']          instr: ['Always show']
Q1  [single]  conf=0.9  Which channel did you primarily use for this cafeteria...
      options: ['Counter', 'Mobile pre-order', 'Vending kiosk']
Q2  [single]  conf=0.9  Overall, how satisfied were you with the cafeteria visit?
      options: ['1 - Very poor', '2 - Poor', '3 - Fair', '4 - Good', '5 - Excellent']
Q4  [multi]   conf=0.9  Which aspects influenced your rating? Select all that...
      options: ['Food quality', 'Menu variety', 'Waiting time', 'Cleanliness',
                'Staff behaviour', 'Price']
      instr:   ['Validate: {"min_selections": 1}']
Q6  [text]    conf=0.9  Please describe the main problem.
      instr:   ['Show if: Q5 == \'Yes\'  Validate: {"min_length": 10, ...}']
Q7  [single]  conf=0.9  How likely are you to recommend this service?
      options: ['0','1','2','3','4','5','6','7','8','9','10']
```

Note `Q6`: the instruction is stored exactly as written. The reader has **not**
decided it means "show Q6 only when Q5 is Yes" — that is the next agent's job.

**14 instructions**, sorted into rough categories:

```
display         Q6    Show if: Q5 == 'Yes' ...
randomization   —     Capture displayed random order for every randomized item.
disposition     —     TERM_INELIGIBLE: Thank you for your interest. You do not q...
disposition     —     COMPLETE: Thank you. Your response has been recorded.
validation      —     General instruction: All questions are mandatory unless...
unclassified    S1    Always show
```

`Always show` lands in "unclassified" because none of the configured cue words
match it. It is kept in full and attached to its question — the system simply
does not claim to know what kind of instruction it is.

**8 items flagged for a human**, out of 21 things it could not classify:

```
S01 • SIMPLE                                    <- looks like a question ID but is not
R1 | S1 == 'No'    | terminate | TERM_INELIGIBLE
R3 | Q5 == 'Yes'   | show      | Q6
T2 | eligible with problem | {"S1":"Yes","S2":"Yes","Q5":"Yes"} | ...
```

**Validation: clean.**

```
VALID  S01_campus_cafeteria_experience.docx  0 error(s), 0 warning(s)
```

---

## What this example shows about the current limits

Two honest observations, both visible above.

**The routing table was not understood.** Rows `R1`–`R4` hold the survey's
actual routing rules — `S1 == 'No' → terminate` — in a neat table headed
`Rule / Condition / Action / Destination`. Only one of those four headers is in
the settings file, so the table scored 0.25 against a 0.60 threshold and was
kept as unparsed content with a review flag.

That is the system behaving correctly: it did not pretend to understand a table
it did not recognise, and it did not throw the rows away. But it is a real gap,
and closing it is a change to the settings file rather than to the code —
exactly as designed. The same applies to the test-scenario table (`T1`–`T3`).

**`S01 • SIMPLE` was nearly mistaken for a question.** The document's title
starts with something shaped like a question ID. An earlier version of the
reader did record it as a question — inventing a question the QRE never asked.
It now requires a line to actually look like a question before accepting it, and
the title is flagged for a human instead.

---

## Running it yourself

```bash
.venv\Scripts\python.exe scripts/extract_qre.py
```

Processes all 15 development QREs, writes the full structured output and the
validation report to `data/outputs/qre_interpretation/`, and exits with an error
if any document fails validation.

For a single document:

```bash
.venv\Scripts\python.exe scripts/extract_qre.py fixtures/qre-samples/S01_campus_cafeteria_experience.docx
```

**Do not point it at `fixtures/holdout/`.** Those three documents are held back
to test whether the reader works on material it was not built against, and
reading them destroys that. The script refuses them, and so does the test suite.

---

## Where to read more

- `docs/decisions/` — why the significant choices were made
- `docs/weekly-progress/2026-08-17-status.md` — current risks and blockers
- `CLAUDE.md` — the full technical specification
