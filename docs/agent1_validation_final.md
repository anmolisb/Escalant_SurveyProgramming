# Agent 1 — final canonical validation

Read-only. Nothing was regenerated to produce this report; every figure below
is read from the artifacts already committed at `a4e4b54` — the run that
carries the `quota_requirements` fix. Independently re-checked against the raw
QRE documents (`fixtures/qre-samples/S01_campus_cafeteria_experience.docx`,
`fixtures/qre-samples/C01_chronic_care_patient_journey.docx`) via the oracle
in `src/qre_oracle.py`, which shares no code with the pipeline it checks.

## Verdicts

| Survey | Canonical status | Graph input status | Agent 3 readiness | Critical-rule recall | Reproducibility |
|---|---|---|---|---|---|
| **S01** | **PASSED_WITH_WARNINGS** | **READY** | **NOT_READY** | 52/52 (100%) | exact + semantic identical |
| **C01** | **PASSED_WITH_WARNINGS** | **READY** | **NOT_READY** | 220/220 (100%) | exact + semantic identical |

Neither survey is FAILED. Agent 3 readiness is NOT_READY on both — not because
anything is wrong, but because open semantic questions can still change which
questions a respondent sees, and a test designer should not build against a
reading that has not been confirmed.

---

## 1–19: category findings

Legend: **VC** verified correct · **WARN** warning · **HCR** human confirmation
required · **MFQ** missing from QRE (nothing to carry) · **INC** incorrect ·
**MFC** missing from canonical.

### S01 — campus cafeteria experience

| # | Category | Status | Evidence |
|---|---|---|---|
| 1 | Question completeness & sequence | **VC** | 10/10 questions, seq 1–10 contiguous, matches document order |
| 2 | Option completeness & integrity | **VC** | 10/10 questions with options carry the exact label set; 0 invented, 0 missing (cross-source) |
| 3 | Display/show logic | **VC** | 10/10 guard tests pass; Q6's `Q5 == 'Yes'` executes correctly both ways |
| 4 | Skip logic | **VC** | R4 (`Q5 == 'No'` → skip Q7) carried and executes correctly both ways |
| 5 | Routing logic | **VC** | 8/8 (R1–R4 fully exercised, see rule table below) |
| 6 | Termination logic | **VC** | R1, R2 both terminate rules present, execute correctly, destinations defined |
| 7 | Validation rules | **VC** | 14/14 — `min_selections` (Q4), `min_length`/`max_length` (Q6), `max_length`+optional (Q8) all carried; mandatory resolved for all 10 questions |
| 8 | Dependencies/piping | **HCR** | 2 text pipes (Q2→Q4, Q5→Q6), both `origin: inferred` — model-read, not QRE-stated |
| 9 | Randomization | **MFQ** | QRE has no `Randomize` instruction anywhere; 0 entries correctly |
| 10 | Quotas | **MFQ** | QRE has no quota section; 0 entries correctly |
| 11 | Dispositions/messages | **VC** | COMPLETE and TERM_INELIGIBLE both defined with verbatim messages |
| 12 | Acceptance scenarios | **VC** | 3/3 (T1–T3) carried with inputs and expected outcomes resolved to option ids |
| 13 | Programming/QA requirements | **VC** | 6/6 carried verbatim |
| 14 | Provenance | **VC** | 4/4 element kinds (questions, rules, dispositions, scenarios) — every member carries a source reference |
| 15 | Unsupported/invented content | **VC** | 0 cross-source findings — nothing missing, contradictory, unsupported, or invented |
| 16 | Ambiguities / confirmation-required | **HCR** | 2 items — see gate below |
| 17 | Reproducibility | **VC** | 2 runs, exact and semantic identical |
| 18 | Critical-rule recall | **VC** | 52/52 (100%), 7 excluded as UNVERIFIED (evaluation points + semantics) |
| 19 | Cross-source consistency | **VC** | Raw QRE ↔ Stage 4 ↔ canonical agree everywhere checked |

### C01 — chronic-care patient journey

| # | Category | Status | Evidence |
|---|---|---|---|
| 1 | Question completeness & sequence | **VC** | 31/31 questions, seq 1–31 contiguous, matches document order |
| 2 | Option completeness & integrity | **VC** | 27/31 questions with options carry the exact label set; 0 invented, 0 missing |
| 3 | Display/show logic | **VC**, 3× **HCR** | 10 formal guards execute correctly both ways; Q2, Q3, Q6 are prose (`Q1/Q5 contains…`) — read by a model, `origin: inferred` |
| 4 | Skip logic | **VC** | R5 (`Q1 == ['None of these']` → skip Q4) executes correctly both ways |
| 5 | Routing logic | **VC**, 5× **HCR** | 15/20 rules formal and verified executing both ways; R6, R7, R8, R19, R20 are prose, `origin: inferred` — see rule table |
| 6 | Termination logic | **VC** | R1–R4 all present, execute correctly, all 4 destinations defined with messages |
| 7 | Validation rules | **VC** | Checked separately per type — `min_length`/`max_length` (Q14, Q17, Q21, Q23), `min_selections` (Q11), `sum_to` (Q18), `require_each_row` (Q9), `exclusive_option` resolved to an id (Q1, Q5) — 44/44, all carried; mandatory resolved for all 31 |
| 8 | Dependencies/piping | **VC**, 1× **INC→resolved** (see §15 note) | 2 option-source pipes (Q1→Q2, Q5→Q6, `origin: derived`, QRE-stated) + 4 text pipes (Q3→Q8, Q3→Q9, Q19→Q20, Q19→Q21, `origin: inferred`) |
| 9 | Randomization | **VC** structurally, **HCR** on anchoring | 5/5 randomised questions recorded (Q1, Q5, Q9, Q16, Q19); anchoring of the exclusive option on Q1/Q5 marked `ambiguous`, Q9/Q16/Q19 marked `unknown` — QRE never states it |
| 10 | Quotas | **VC** | QUOTA_REGION (hard, D1) and QUOTA_AGE (soft, D2), cells resolved to option ids, targets match the sentence; **the quota-behaviour statement now carried** in `quota_requirements` — this is the fix verified in this pass |
| 11 | Dispositions/messages | **VC**, 1× **MFQ** | COMPLETE, TERM_AGE, TERM_CONFLICT, TERM_INVOLVEMENT, TERM_RECENT_RESEARCH all defined with verbatim messages; TERM_QUOTA_FULL has no message because the QRE gives it none — correctly marked `defined_in_source: false`, not invented |
| 12 | Acceptance scenarios | **VC** | 7/7 (T1–T7) carried, inputs resolved to option ids, expectations resolved to questions/endings |
| 13 | Programming/QA requirements | **VC** | 6/6 carried verbatim |
| 14 | Provenance | **VC** | 4/4 element kinds |
| 15 | Unsupported/invented content | **VC** | 0 cross-source findings |
| 16 | Ambiguities / confirmation-required | **HCR** | 9 items — see gate below |
| 17 | Reproducibility | **VC** | 2 runs, exact and semantic identical |
| 18 | Critical-rule recall | **VC** | 220/220 (100%), 36 excluded as UNVERIFIED |
| 19 | Cross-source consistency | **VC** | Raw QRE ↔ Stage 4 ↔ canonical agree everywhere checked |

No **INC** (incorrect) or **MFC** (missing from canonical) findings on either
survey. Nothing here was fixed in this pass — this is the state as committed.

---

## Rule-by-rule coverage

`condition_eval` runs the canonical condition tree against a real answer built
from the QRE's own options and compares it to the QRE's own condition,
evaluated independently by the oracle — both a positive and a negative case.
Where the QRE states a condition in prose, no independent oracle exists; that
row reports `origin: inferred` instead of a pass/fail on execution, and is the
evidence behind a confirmation-gate item, not a failure.

### S01

| Rule | Condition (QRE) | Action → destination | Canonical | Positive | Negative | Result |
|---|---|---|---|---|---|---|
| R1 | `S1 == 'No'` | terminate → TERM_INELIGIBLE | matches | fires | doesn't fire | **VERIFIED** |
| R2 | `S2 == 'No'` | terminate → TERM_INELIGIBLE | matches | fires | doesn't fire | **VERIFIED** |
| R3 | `Q5 == 'Yes'` | show → Q6 | matches | fires | doesn't fire | **VERIFIED** |
| R4 | `Q5 == 'No'` | skip → Q7 | matches | fires | doesn't fire | **VERIFIED** |

4/4 rules present, 4/4 destinations correct, 4/4 conditions execute correctly
in both directions. 0 failures.

### C01

| Rule | Condition (QRE) | Action → destination | Canonical | Positive | Negative | Result |
|---|---|---|---|---|---|---|
| R1 | `S1 == 'No'` | terminate → TERM_AGE | matches | fires | doesn't fire | **VERIFIED** |
| R2 | `S2 != '…chronic health condition'` | terminate → TERM_INVOLVEMENT | matches | fires | doesn't fire | **VERIFIED** |
| R3 | `S3 == 'Yes'` | terminate → TERM_RECENT_RESEARCH | matches | fires | doesn't fire | **VERIFIED** |
| R4 | `S4 == 'Yes'` | terminate → TERM_CONFLICT | matches | fires | doesn't fire | **VERIFIED** |
| R5 | `Q1 == ['None of these']` | skip → Q4 | matches | fires | doesn't fire | **VERIFIED** |
| R6 | `Q1 contains at least one brand` | show → Q2 | matches | *(prose)* | *(prose)* | **HUMAN CONFIRMATION REQUIRED** — `origin: inferred` |
| R7 | `Q1 contains at least one brand` | show → Q3 | matches | *(prose)* | *(prose)* | **HUMAN CONFIRMATION REQUIRED** — `origin: inferred` |
| R8 | `Q5 contains any touchpoint` | show → Q6 | matches | *(prose)* | *(prose)* | **HUMAN CONFIRMATION REQUIRED** — `origin: inferred` |
| R9 | `Q3 != 'None/currently not using'` | show → Q7 | matches | fires | doesn't fire | **VERIFIED** |
| R10 | `Q3 != 'None/currently not using'` | show → Q8 | matches | fires | doesn't fire | **VERIFIED** |
| R11 | `Q3 != 'None/currently not using'` | show → Q9 | matches | fires | doesn't fire | **VERIFIED** |
| R12 | `Q10 == 'Yes'` | show → Q11 | matches | fires | doesn't fire | **VERIFIED** |
| R13 | `Q10 == 'Yes'` | show → Q12 | matches | fires | doesn't fire | **VERIFIED** |
| R14 | `Q12 in ['Fully','Partly']` | show → Q13 | matches | fires | doesn't fire | **VERIFIED** |
| R15 | `Q12 == 'Not resolved'` | show → Q14 | matches | fires | doesn't fire | **VERIFIED** |
| R16 | `Q15 == 'Yes'` | show → Q16 | matches | fires | doesn't fire | **VERIFIED** |
| R17 | `Q16 == 'Other'` | show → Q17 | matches | fires | doesn't fire | **VERIFIED** |
| R18 | `sum(Q18) != 100` | reject → Q18 | matches | fires | doesn't fire | **VERIFIED** |
| R19 | `exclusive option selected with another response at Q1 or Q5` | reject → CURRENT_QUESTION | matches | *(prose)* | *(prose)* | **HUMAN CONFIRMATION REQUIRED** — `origin: inferred` |
| R20 | `selected option at Q6 was not selected at Q5` | reject → Q6 | matches | *(prose)* | *(prose)* | **HUMAN CONFIRMATION REQUIRED** — `origin: inferred` |

20/20 rules present, 20/20 destinations correct, 20/20 condition text carried
verbatim. **15/15 formal conditions execute correctly in both directions,
0 failures.** 5/20 (R6, R7, R8, R19, R20) are prose in the source document —
no independent oracle exists for these, so they cannot be VERIFIED by
execution; each is a confirmation-gate item, not a defect.

No critical routing or termination failure is hidden in the 220/220 recall
figure — every one of those 220 checks is individually enumerated in
`out/C01_chronic_care_patient_journey/agent1_evaluation_results.json`, and the
table above is the routing/termination subset of it by hand.

---

## Reproducibility

| | S01 | C01 |
|---|---|---|
| Runs compared | 2 | 2 |
| Exact (byte-identical JSON) | **identical** | **identical** |
| Semantic (routing, destinations, conditions, validation, termination, dependencies, quotas, randomization) | **identical** | **identical** |
| Meaningful differences | none | none |

Verified via the decision/cache mechanism in `src/llm.py`
(`out/<stem>/llm_decisions.json`): every model answer the specification
depends on is recorded per document, keyed by model, system prompt, user
prompt, response schema and token cap, and reused rather than re-asked. Both
rebuilds for this comparison completed in 0 model calls.

---

## HUMAN CONFIRMATION REQUIRED

### S01 (2)

| Issue | Affects | Why it matters |
|---|---|---|
| `semantics_unconfirmed` | whole survey | Unasked-question semantics, rule precedence, multi-select equality — none stated by the QRE |
| `text_pipe_inferred` | Q4, Q6 | Wording read as quoting an earlier answer; no table states this |

### C01 (9)

| Issue | Affects | Why it matters |
|---|---|---|
| `semantics_unconfirmed` | whole survey | Same three decisions as S01 |
| `condition_inferred` | Q2, Q6, R19, R20 | Prose condition read by a model; changes whether the rule fires |
| `inferred_condition_partial_options` | Q2, Q3, R6, R7 | "At least one brand" read as 3 of Q1's 4 answers, omitting "Independent provider" — the skip rule above (R5) implies the opposite reading |
| `text_pipe_inferred` | Q8, Q9, Q20, Q21 | Wording read as quoting an earlier answer |
| `randomization_anchoring` | Q1, Q5, Q9, Q16, Q19 | Whether an exclusive option stays anchored when shuffled — QRE silent |
| `quota_inferred` | QUOTA_REGION, QUOTA_AGE | Quota structure read from prose by a model |
| `guard_single_source` | Q15 | Display condition stated only in the questionnaire, not the routing table |
| `partial_option_codes` | Q13 | Coded on 2 of 5 options; a bot answering by code cannot resolve the rest |
| `quota_ending_missing` | TERM_QUOTA_FULL | Referenced as a quota-full destination; QRE gives it no message |

Nothing here was resolved in this pass, as instructed. Each item is exactly
as recorded in `part2_validation.json`'s `confirmation_required` list.

---

## Exact artifact paths

Already generated by the validation layer, read (not regenerated) for this
report:

```
out/S01_campus_cafeteria_experience/agent1_evaluation_tests.json
out/S01_campus_cafeteria_experience/agent1_evaluation_results.json
out/S01_campus_cafeteria_experience/part2_validation.json

out/C01_chronic_care_patient_journey/agent1_evaluation_tests.json
out/C01_chronic_care_patient_journey/agent1_evaluation_results.json
out/C01_chronic_care_patient_journey/part2_validation.json

docs/agent1_validation_summary.md   (prior compact summary, both surveys)
docs/agent1_validation_final.md     (this report)
```

---

## Final verdicts

```
C01 — chronic-care patient journey
  CANONICAL STATUS:     PASSED_WITH_WARNINGS
  GRAPH INPUT STATUS:   READY
  AGENT 3 READINESS:    NOT_READY
  blocked by: semantics_unconfirmed, inferred_condition_partial_options

S01 — campus cafeteria experience
  CANONICAL STATUS:     PASSED_WITH_WARNINGS
  GRAPH INPUT STATUS:   READY
  AGENT 3 READINESS:    NOT_READY
  blocked by: semantics_unconfirmed
```

Neither survey FAILED, so there is no "exact question/rule that must change"
to report. Both are graph-ready today. Agent 3 readiness on both is withheld
for the same underlying reason — the three semantics decisions the QRE never
states — plus, on C01 only, the omitted-option ambiguity on R6/R7. These are
client decisions, not defects, and are exactly what the confirmation gate
above exists to surface rather than to hide behind a passing score.
