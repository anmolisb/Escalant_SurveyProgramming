# 0005 — Record of holdout use, and scope reduced to S01, M01 and C01

**Date:** 2026-10-11
**Status:** Accepted (2026-10-11: holdouts retired, section 5)
**Affects:** `fixtures/`, `out/`, `tests/agent1_verification/` (removed), `data/ground_truth/Synthetic/`, decisions 0002 and 0003

## 1. Scope reduction

Escalent (Sameer Saurabh) asked the team not to take on new QRE formats and to
state that limitation in the report. The supported formats are the S, M and C
QREs. For the current refactor of Agent 1 the development corpus is reduced to
three of them:

| Kept in `fixtures/qre-samples/` | Tier |
|---|---|
| `S01_campus_cafeteria_experience.docx` | Simple |
| `M01_mobile_network_experience.docx` | Moderate |
| `C01_chronic_care_patient_journey.docx` | Complex |

The other development QREs, their run outputs under `out/`, and their ground
truth under `tests/agent1_verification/ground_truth/` were removed. They remain
in git history.

`fixtures/holdout/` is unchanged, and so is the M04 ground truth file, which
belongs to the holdout rather than to the development corpus.

## 2. What the holdout has been used for

Decision 0002 allows the holdout to be run once ground truth exists, to
measure extraction. It is burned only if it is used to debug a specific
failure, and a burn must be recorded here. No burn was recorded. This is what
the repository shows:

| Holdout | Use found | Commit |
|---|---|---|
| C03 | Agent 1 run output committed at `out/C03_b2b_saas_decision_journey/` | `10d682c` (2026-09-12, an Agent 3 commit) |
| M04 | Ground truth committed at `tests/agent1_verification/ground_truth/M04_hotel_stay_experience.truth.json` | `95d57dc` (2026-09-08) |
| M04 | Scored in `tests/agent1_verification/comparison.json` | `5da45ff` (2026-09-10) |

The M04 uses are measurement, which 0002 permits. The C03 output arrived in an
Agent 3 commit, so it may have served as a development input for Agent 3
rather than as a measurement of Agent 1. No commit message records a change
made in response to either document.

**Decided (section 5):** rather than settle whether C03 is burned, all three
holdouts are retired. No accuracy claim in the report rests on any of them.

## 3. What a reader of the report should know

- Agent 1 is evaluated on S01, M01 and C01 only. Accuracy on other formats is
  not claimed.
- The verification report (`tests/agent1_verification/`) was regenerated for
  these three documents before the harness was removed (section 4). C01's Q6
  display condition (`Q5 contains any touchpoint`) is reported as declined: the
  2026-10-05 canonical output leaves it unread for a person to confirm, where
  the 2026-09-10 report scored an older output that had read it.

## 4. One ground-truth check: Stage 7 (agreed by the team)

Three independent readings of the document existed:

| Reading | What it did | Outcome |
|---|---|---|
| Stage 7 (`qre_oracle.py`, `agent1_eval.py`) | Runs on every pipeline run. Executes each formal condition against test answers and checks question, type and option coverage. Its verdict drives the Agent 3 gate and the dashboard. | **Kept** |
| `tests/agent1_verification/` | Run by hand. Compared the canonical specification field by field against machine-generated truth files and wrote an Excel report. | Removed |
| `data/ground_truth/Synthetic/*.gt.csv` | Worksheets for human coding under decision 0003. Never filled in: every file held only its header row. | Removed |

Stage 7 is kept because the pipeline depends on it and it tests behaviour, not
only text. Field-level fidelity is checked on every run by Stage 5's
`content_fidelity` check (Stage 4 against the literal Stage 3 cells).

Last results from the removed harness, kept for the report (2026-10-11,
canonical outputs of 2026-10-05):

| QRE | Correct | Missed | Mismatch | Invented | Declined |
|---|---|---|---|---|---|
| S01 | 99 | 0 | 0 | 0 | 0 |
| M01 | 201 | 0 | 0 | 0 | 3 |
| C01 | 345 | 0 | 0 | 0 | 6 |

"Declined" counts values the pipeline deliberately left for a person to
confirm, such as a condition it would not guess at.

**Limitation for the report:** decision 0003's human-coded ground truth was
never produced. Every accuracy figure above compares the pipeline with another
automated reading of the same document, not with a person's reading.

## 5. Holdouts retired, and new ones to be written (2026-10-11)

The three holdout documents (`C03_b2b_saas_decision_journey.docx`,
`M04_hotel_stay_experience.docx`, `QRE_2_Moderate_Cloud_Storage_Concept_Test.pdf`)
and their manifest are removed from `fixtures/holdout/`. Reasons:

- C03 may already be burned (section 2), and M04 has been read to build its
  ground truth, so neither still measures unseen material with confidence.
- The development QREs now carry display messages (Escalent's request), and
  the old holdouts do not, so they no longer match the supported format.
- The PDF is outside the supported S, M and C format.

They remain in git history.

New holdouts will be written in the same S, M and C format, with display
messages, and with different questions, including question types the
development corpus does not use. They test whether the pipeline generalises
within the supported format, not whether it handles other formats. Until they
exist, the folder holds only `.gitkeep`, and the rules of 0002 apply to them as
soon as they are added: nobody develops against them, and any use to debug a
specific failure burns them and is recorded here.

## 6. The development corpus grows back to 15 QREs (2026-10-11)

With display-message support finished and checked end to end on S01, M01 and
C01, the corpus is widened again, this time with display messages in every
document, so all of it matches the supported format:

| Tier | QREs |
|---|---|
| Simple | S01, S02, S03, S04, S05 |
| Moderate | M01, M02, M03, M04, M05, M06 |
| Complex | C01, C02, C03, C04 |

S02 to S05, M02, M03, M05, M06, C02 and C04 come from the corpus before section
1's reduction. M04 and C03 are the two retired holdouts (section 5), now
ordinary development documents. Each has the same display rows as S01, M01 and
C01: one after screening for an S QRE, plus an "almost done" message before the
demographics for an M QRE, plus a mid-survey message before the support
questions for a C QRE.

F01, F02, Z01 and Z02 stay out: they are not in the S, M and C format.
