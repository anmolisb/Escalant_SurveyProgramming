# The supported QRE format

The pipeline reads questionnaire requirement documents (QREs) written in the
format of the 15 documents in `fixtures/qre-samples/`: five simple (S01 to
S05), six moderate (M01 to M06) and four complex (C01 to C04). This page
describes that format. A QRE that follows it can be run end to end; one that
departs from it needs the changes in [`maintenance.md`](maintenance.md).

## The document

A Word document (`.docx`) with a front page and up to seven sections, each
under a heading set in a Word heading style.

**Front page.** Plain lines before the first heading: a reference such as
`M01 • MEDIUM`, the survey title, and `Questionnaire Requirement Document
(QRE)`. The title becomes the survey's title.

**Sections.** Matched by heading name. The names below are the ones the
pipeline knows; a heading worded differently is still recognised when its
content has the expected shape (a table with question columns, for instance).
Every section is optional, and a section the pipeline does not recognise is
kept and reported rather than dropped.

| Section | Form | Holds |
|---|---|---|
| Study specification | `Label: value` lines | Business objective, target population, mode, length |
| Questionnaire | Table | One row per question or message |
| Routing and termination | Table | One row per rule |
| Quota controls | Lines | Quota groups and what happens when one is full |
| Completion messages | `CODE: message` lines | The text shown at each ending |
| Programming and QA requirements | Lines | Instructions to whoever programs and tests the survey |
| Acceptance test scenarios | Table | The QRE's own test cases |

## The questionnaire table

| ID | Wording / instruction | Type | Options / scale | Display / validation |
|---|---|---|---|---|
| S1 | Have you used or purchased mobile network services in the past 6 months? | single | Yes; No | Always show |
| Q7 | Did you experience any of the following problems? | multi | Dropped calls; Slow data; Unexpected charge; Coverage gap; Support delay; None of these | Validate: {"exclusive_option": "None of these"} *(new line)* Randomize |
| DT2 | You're almost done! Thank you for your answers. … | text display | (none) | Always show |

Rows from M01.

Columns are found by what their names mean, not by exact name, so "Question
text" works as well as "Wording / instruction".

- **ID.** Screening questions `S1`, `S2`…, main questions `Q1`…, demographics
  `D1`…, display messages `DT1`….
- **Options.** Separated by semicolons. Codes are used only where the QRE
  writes them; none are invented.
- **Type.** One of the types below.
- **Display / validation.** One instruction per line, in these forms:

| Line | Meaning |
|---|---|
| `Always show` | No display condition |
| `Show if: <condition>` | Display condition |
| `Validate: {...}` | Rules in JSON: `min_length`, `max_length`, `min`, `max`, `min_selections`, `sum`, `exclusive_option`, `require_each_row` |
| `Randomize` | Shuffle the options (or a grid's rows) |
| `Show only <items> selected at Qn` | Options narrowed to an earlier answer |
| `Optional` / `Mandatory` | Whether an answer is required |

A line in none of these forms is read by the model and flagged for review.

## Question types

| Type | What it is | Built in LimeSurvey as |
|---|---|---|
| `single` | Choose one | List (radio) |
| `multi` | Choose any | Multiple choice |
| `text` | Free text | Long free text |
| `matrix` | Grid: rows rated on one scale | Array |
| `constant_sum` | Numbers that must add to a total | Multiple numerical input |
| `integer`, `number` | A number | Numerical input |
| `text display` | A message with nothing to answer | Text display |

## The routing table

| Rule | Condition | Action | Destination |
|---|---|---|---|
| R1 | `S1 == 'No'` | terminate | TERM_INELIGIBLE |
| R3 | `S3 < 18 or S3 > 80` | reject | S3 |
| R4 | Q7 contains any problem | show | Q8 |
| R9 | Q7 includes 'None of these' plus another option | reject | Q7 |

Rows from M01.

- **Actions:** `terminate` (end the survey at the named ending), `show`,
  `skip` and `reject` (refuse the answer).
- **Conditions** may be formal (`S1 == 'No'`, `Q12 in ['Fully','Partly']`,
  `S3 < 18`, `sum(Q18) != 100`) or prose. Formal ones are read by code. Prose
  is read by the model in the same grammar and flagged for review.

## Quotas, endings and scenarios

- **Quotas:** `CODE: soft quota on D1: North=20%, South=20%, …`, plus a line
  naming the ending a respondent reaches when their cell is full.
- **Endings:** `COMPLETE: Thank you…`, `TERM_INELIGIBLE: …`. Every ending a
  rule or quota names should have a message here.
- **Scenarios:** ID, purpose, key inputs and expected outcome, with inputs and
  outcomes in JSON (`{"S1": "No"}` and `{"expected_end": "TERM_INELIGIBLE"}`).

## What is not supported yet

- PDF QREs. Only `.docx` is read.
- Question types other than those above: dropdowns, yes/no and 5-point
  shortcuts, ranking, dates, short and multiple short text, and the other array
  types.
- Quotas are read and tested for, but not built into the survey.
- Wording that shows an earlier answer ("the selected proposition") is kept as
  written; the answer is not inserted.
- Conditions using `count()`, comparing one question with another, or an exact
  answer set are read, but not all of them can be built or tested.

Before a run, `python -m src.common.readiness out/<QRE>` lists anything in a
specific QRE that a later agent cannot handle.
