# Agent 1 validation summary

Canonical specification checked against the raw QRE, independently of the
pipeline that produced it. Tests are derived from the document; where the
document does not establish what the right answer is, the test is reported
UNVERIFIED rather than passed.

## Verdict

| Survey | Canonical | Human decision gate | Graph | Agent 3 | Tests | Pass | Fail | Unverified | Blocked |
|---|---|---|---|---|---|---|---|---|---|
| S01 | PASSED_WITH_WARNINGS | PENDING_BLOCKING_DECISIONS | YES | NO | 130 | 123 | 0 | 7 | 0 |
| C01 | PASSED_WITH_WARNINGS | PENDING_BLOCKING_DECISIONS | YES | NO | 445 | 409 | 0 | 36 | 0 |

## S01 — S01_campus_cafeteria_experience

### Logic coverage

| Metric | Result | Target | Unverified (excluded) |
|---|---|---|---|
| Questions | 21/21 (100%) | 100% | 0 |
| Question types | 10/10 (100%) | 100% | 0 |
| Options | 10/10 (100%) | 100% | 0 |
| Display rules | 10/10 (100%) | 100% | 0 |
| Skip rules | 7/7 (100%) | 100% | 1 |
| Routing rules | 8/8 (100%) | 100% | 1 |
| Termination | 16/16 (100%) | 100% | 2 |
| Validation | 14/14 (100%) | 100% | 0 |
| Dependencies / piping | n/a | 100% | 0 |
| Randomization | n/a | 100% | 0 |
| Quotas | n/a | 100% | 0 |
| Dispositions | 2/2 (100%) | 100% | 0 |
| Acceptance scenarios | 9/9 (100%) | 100% | 0 |
| Programming requirements | 6/6 (100%) | 100% | 0 |
| Study metadata | 5/5 (100%) | 100% | 0 |
| Provenance | 4/4 (100%) | 100% | 0 |
| **Critical-rule recall** | 52/52 (100%) | 100% | 7 |

_Critical-rule recall covers executable logic only — display, skip,
routing, termination, validation, dependencies, quotas and randomization._

### Graph build (measured, not assumed)

- 13 nodes, 14 edges; rules mapped 4/4; quotas mapped 0/0; 2 dependency edges
- Fidelity check: **passed** (0 blocking)

### Reproducibility

- Exact: **identical**
- Semantic: **identical**
- Meaningful differences: none

### Cross-source checks

No missing, contradictory, unsupported or invented content found.

### CONFIRMATION_REQUIRED (2)

**semantics_unconfirmed** — affects S01_campus_cafeteria_experience.docx, semantics

- Why it matters: The semantics block records three decisions the QRE never states: that a condition naming an unasked question is false, that the first matching rule wins, and that '==' against a multi-select compares the whole answer set. Each changes which questions appear on many routes and needs confirming.
- Changes downstream: Which questions appear on many routes, which rule wins when two apply, and whether an 'is exactly' test passes on a multi-select answer.
- Decision IDs: —

**text_pipe_inferred** — affects Q4, Q6

- Why it matters: Q4's wording appears to quote the answer given at Q2. No table states this; it was read out of the sentence, so it is worth confirming.
- Changes downstream: Whether this question's wording depends on an earlier answer, which decides the order a bot must answer in and what text it should expect on screen.
- Decision IDs: —

### Human decision register

- 4 total: 4 pending, 0 resolved, 0 not required
- raised this run: 4 · resolved decisions reused: 0 · moved to not-required: 0 · invalidated by a changed context: 0
- blocking and still pending: 134511cac21dfa7d, 376a146526ee8c10, 3c988435446a4710, d4839c48687f65bd
- full register: `out/S01_campus_cafeteria_experience/agent1_decisions.json` · human-readable: `out/S01_campus_cafeteria_experience/agent1_decision_register.md`

### Top issues

- No incorrect or missing content. Everything outstanding is a decision, above.

Agent 3 is blocked by: ambiguous_piping, rule_precedence, unasked_question_semantics

## C01 — C01_chronic_care_patient_journey

### Logic coverage

| Metric | Result | Target | Unverified (excluded) |
|---|---|---|---|
| Questions | 64/64 (100%) | 100% | 0 |
| Question types | 31/31 (100%) | 100% | 0 |
| Options | 32/32 (100%) | 100% | 0 |
| Display rules | 45/45 (100%) | 100% | 3 |
| Skip rules | 7/7 (100%) | 100% | 1 |
| Routing rules | 96/96 (100%) | 100% | 20 |
| Termination | 32/32 (100%) | 100% | 4 |
| Validation | 44/44 (100%) | 100% | 0 |
| Dependencies / piping | 2/2 (100%) | 100% | 0 |
| Randomization | 5/5 (100%) | 100% | 5 |
| Quotas | 9/9 (100%) | 100% | 0 |
| Dispositions | 5/5 (100%) | 100% | 0 |
| Acceptance scenarios | 21/21 (100%) | 100% | 0 |
| Programming requirements | 6/6 (100%) | 100% | 0 |
| Study metadata | 5/5 (100%) | 100% | 0 |
| Provenance | 4/4 (100%) | 100% | 0 |
| **Critical-rule recall** | 220/220 (100%) | 100% | 36 |

_Critical-rule recall covers executable logic only — display, skip,
routing, termination, validation, dependencies, quotas and randomization._

### Graph build (measured, not assumed)

- 38 nodes, 39 edges; rules mapped 20/20; quotas mapped 2/2; 15 dependency edges
- Fidelity check: **passed** (0 blocking)

### Reproducibility

- Exact: **identical**
- Semantic: **identical**
- Meaningful differences: none

### Cross-source checks

No missing, contradictory, unsupported or invented content found.

### CONFIRMATION_REQUIRED (9)

**randomization_anchoring** — affects Q1, Q16, Q19, Q5, Q9

- Why it matters: Q1 shuffles its options and has 'None of these' as an exclusive option. Convention keeps such an option at the bottom, but the QRE does not say so.
- Changes downstream: Where an exclusive option appears when the list is shuffled, which decides whether a displayed-order assertion is right.
- Decision IDs: 95eaab2b4ebfe62e

**condition_inferred** — affects Q2, Q6, R19, R20

- Why it matters: Q2's display condition was prose, so a model proposed a reading which the parser then accepted. Worth a human eye.
- Changes downstream: Whether this rule fires for a given respondent, so which questions they see and which ending they reach.
- Decision IDs: —

**inferred_condition_partial_options** — affects Q2, Q3, R6, R7

- Why it matters: Rule R6 was read as naming 3 of Q1's 4 selectable answers, leaving out ['Independent provider']. A model chose which ones count and the QRE does not say.
- Changes downstream: Which answers satisfy the rule. Respondents choosing an omitted answer take a different path than they should.
- Decision IDs: 756d035e6abbdf43

**text_pipe_inferred** — affects Q20, Q21, Q8, Q9

- Why it matters: Q8's wording appears to quote the answer given at Q3. No table states this; it was read out of the sentence, so it is worth confirming.
- Changes downstream: Whether this question's wording depends on an earlier answer, which decides the order a bot must answer in and what text it should expect on screen.
- Decision IDs: —

**quota_inferred** — affects QUOTA_AGE, QUOTA_REGION

- Why it matters: Quota QUOTA_REGION was read out of a sentence by a model and passed the checks. Worth a human eye.
- Changes downstream: Which respondents are counted against which quota, and when they are turned away.
- Decision IDs: —

**semantics_unconfirmed** — affects C01_chronic_care_patient_journey.docx, semantics

- Why it matters: The semantics block records three decisions the QRE never states: that a condition naming an unasked question is false, that the first matching rule wins, and that '==' against a multi-select compares the whole answer set. Each changes which questions appear on many routes and needs confirming.
- Changes downstream: Which questions appear on many routes, which rule wins when two apply, and whether an 'is exactly' test passes on a multi-select answer.
- Decision IDs: —

**guard_single_source** — affects Q15

- Why it matters: Q15 has a display condition in the questionnaire but no matching rule in the routing table, so reading only the routing table would miss it.
- Changes downstream: A display condition stated in only one place. Anyone reading the other place builds a survey without it.
- Decision IDs: 74f6f819e190cab4

**partial_option_codes** — affects Q13

- Why it matters: Q13 has codes on 2 of 5 options. A bot told to answer by code cannot resolve the rest, and inventing the missing codes is not allowed.
- Changes downstream: A bot told to answer by code cannot resolve the uncoded options.
- Decision IDs: —

**quota_ending_missing** — affects TERM_QUOTA_FULL

- Why it matters: Quota QUOTA_REGION sends a full group to 'TERM_QUOTA_FULL', which no completion message defines. Nothing can show that respondent anything.
- Changes downstream: Nothing can be asserted about what a quota-full respondent is shown.
- Decision IDs: —

### Human decision register

- 18 total: 18 pending, 0 resolved, 0 not required
- raised this run: 18 · resolved decisions reused: 0 · moved to not-required: 0 · invalidated by a changed context: 0
- blocking and still pending: 00db7d74442cb17d, 0430c3303a173c36, 5c5b9104ff079c25, 70e04d836cb40d1b, 71002f0c34af1fbc, 756d035e6abbdf43, 8009e053dcf0c019, 8c69b2c506c9955a, ae7f9449c4271f16, b90d8580babbddab, c417f67cdc3ab8cb, d04e54c7a70f655f, d1c767adabb142b1, e4c971197a4cd683, f6de93712798f5f5
- full register: `out/C01_chronic_care_patient_journey/agent1_decisions.json` · human-readable: `out/C01_chronic_care_patient_journey/agent1_decision_register.md`

### Top issues

- No incorrect or missing content. Everything outstanding is a decision, above.

Agent 3 is blocked by: ambiguous_piping, ambiguous_routing_condition, inferred_condition_partial_options, missing_option_codes, multi_select_equality, quota_behaviour, rule_precedence, unasked_question_semantics
