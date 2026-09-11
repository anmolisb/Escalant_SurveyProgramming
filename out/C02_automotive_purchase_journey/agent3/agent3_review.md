# Agent 3 test design report - C02_automotive_purchase_journey

Agent 3 v0.1. Blocks B1 to B4 implemented and run. Blocks A and C are blocked on Agent 2's build manifest; D, E and F are pending design.

## Headline

- **163 coverage targets** enumerated across nine dimensions
- **162 logically covered**, each with an independently predicted outcome
- **162 logical test cases** generated, with steps and assertions
- **0 executable tests** - Block C cannot bind a canonical id to a LimeSurvey field without Agent 2's build manifest
- **Coverage floor 98.3%** (D1). Reported as a floor, never a sum or an average
- **Specification replay: 6 agree / 0 disagree / 1 unresolved of 7** against the QRE's own acceptance scenarios

## Coverage vector

Nine dimensions, reported side by side. They count different kinds of unit, so a total would be meaningless.

| Dim | Measures | Enumerated | Covered | Logical % | Status | Why not covered |
|---|---|---|---|---|---|---|
| D1 | Visibility | 59 | 58 | 98.3% | PARTIAL | `INFEASIBLE` x1 |
| D2 | Terminal outcome | 6 | 6 | 100.0% | EXHAUSTIVE | - |
| D3 | Validation (explicit) | 24 | 24 | 100.0% | EXHAUSTIVE | - |
| D4 | Validation (mandatory) | 31 | 31 | 100.0% | EXHAUSTIVE | - |
| D5 | Option-source dependency | 2 | 2 | 100.0% | EXHAUSTIVE | - |
| D6 | Text-pipe dependency | 4 | 4 | 100.0% | EXHAUSTIVE | - |
| D7 | Randomization configuration | 13 | 13 | 100.0% | EXHAUSTIVE | - |
| D8 | Quota cell state | 20 | 20 | 100.0% | EXHAUSTIVE | - |
| D9 | Interaction | 4 | 4 | 100.0% | BOUNDED | - |

**Floor: 98.3% (D1).** FLOOR - lowest dimension. Never a sum or an average.

**Executable coverage: 0.0%.** 0% for every target and every survey. Block C cannot bind a canonical id to a LimeSurvey field without Agent 2's build manifest, which is not published yet. Logical and executable coverage are tracked separately precisely so this gap is visible.

## Survey-wide semantics

B3's interpreter cannot run without these. They are read from Agent 1's `semantics` block and decision register, never hardcoded, so a change of ruling regenerates the tests instead of requiring a rewrite.

| Reading | Value | Origin | Status | Blocking | Agent 1 decision |
|---|---|---|---|---|---|
| unasked_reference | `condition_false` | inferred | PROVISIONAL | yes | 9b354f3c76403871 |
| rule_precedence | `document_order_first_match` | inferred | PROVISIONAL | yes | b6ec9432e013d044 |
| multi_equality | `set_equality` | derived | PROVISIONAL | yes | 3a56161f7945542e |
| default_mandatory | `True` | derived | CONFIRMED | no | - |

3 reading(s) still provisional. **155 of 162 generated tests lean on at least one of them** and are tagged accordingly, so a change of ruling shows exactly which tests must be regenerated.

## Specification replay

Agent 1's own acceptance scenarios walked through B3. If B3 disagreed with a scenario the QRE author wrote, either B3 is wrong or the QRE contradicts itself.

**6 agree, 0 disagree, 1 unresolved, of 7.**

| Scenario | Purpose | Outcome | Problem |
|---|---|---|---|
| T1 | age screenout | AGREE | - |
| T2 | conflict screenout | AGREE | - |
| T3 | brand unaware journey | AGREE | - |
| T4 | user, no support, no switch | AGREE | - |
| T5 | unresolved support and other switch reason | AGREE | - |
| T6 | constant-sum under 100 | AGREE | - |
| T7 | piped option violation | UNRESOLVED | expected_validation_error Q6: no error raised |

_UNRESOLVED means B3 declined to evaluate a condition it cannot read, which is not the same as disagreeing with the QRE. Only DISAGREE indicates a real conflict._

## Sample generated tests

### `TC-9d345eef73` - answering D1 normally moves the respondent on to the question that should come next

Dimension D1. Traces to D1.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `S3` = `S3-O2`
- `S4` = `S4-O2`
- `Q1` = `['Q1-O1']`
- `Q2` = `['Q2-O1']`
- `Q3` = `Q3-O1`
- `Q4` = `Q4-O1`
- `Q5` = `['Q5-O1']`
- `Q6` = `Q6-O1`
- `Q7` = `Q7-O1`
- `Q8` = `Q8-O1`
- `Q9` = `{'Q9-R1': 'Q9-O1', 'Q9-R2': 'Q9-O1', 'Q9-R3': 'Q9-O1', 'Q9-R4': 'Q9-O1', 'Q9-R5': 'Q9-O1', 'Q9-R6': 'Q9-O1'}`
- `Q10` = `Q10-O1`
- `Q11` = `['Q11-O1']`
- `Q12` = `Q12-O1`
- `Q13` = `Q13-O1`
- `Q15` = `Q15-O1`
- `Q16` = `Q16-O1`
- `Q18` = `{'Q18-O1': 20, 'Q18-O2': 20, 'Q18-O3': 20, 'Q18-O4': 20, 'Q18-O5': 20}`
- `Q19` = `Q19-O1`
- `Q20` = `Q20-O1`
- `Q21` = `xxxxx`
- `D1` = `D1-O1`
- `D2` = `D2-O1`
- `D3` = `D3-O1`
- `D4` = `D4-O1`
- `Q22` = `Q22-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `D1` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `D2` = `D2`
  - and the very next question the respondent sees must be this one

### `TC-a1ac064e4d` - answering D2 normally moves the respondent on to the question that should come next

Dimension D1. Traces to D2.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `S3` = `S3-O2`
- `S4` = `S4-O2`
- `Q1` = `['Q1-O1']`
- `Q2` = `['Q2-O1']`
- `Q3` = `Q3-O1`
- `Q4` = `Q4-O1`
- `Q5` = `['Q5-O1']`
- `Q6` = `Q6-O1`
- `Q7` = `Q7-O1`
- `Q8` = `Q8-O1`
- `Q9` = `{'Q9-R1': 'Q9-O1', 'Q9-R2': 'Q9-O1', 'Q9-R3': 'Q9-O1', 'Q9-R4': 'Q9-O1', 'Q9-R5': 'Q9-O1', 'Q9-R6': 'Q9-O1'}`
- `Q10` = `Q10-O1`
- `Q11` = `['Q11-O1']`
- `Q12` = `Q12-O1`
- `Q13` = `Q13-O1`
- `Q15` = `Q15-O1`
- `Q16` = `Q16-O1`
- `Q18` = `{'Q18-O1': 20, 'Q18-O2': 20, 'Q18-O3': 20, 'Q18-O4': 20, 'Q18-O5': 20}`
- `Q19` = `Q19-O1`
- `Q20` = `Q20-O1`
- `Q21` = `xxxxx`
- `D1` = `D1-O1`
- `D2` = `D2-O1`
- `D3` = `D3-O1`
- `D4` = `D4-O1`
- `Q22` = `Q22-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `D2` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `D3` = `D3`
  - and the very next question the respondent sees must be this one

### `TC-531a6544ed` - answering D3 normally moves the respondent on to the question that should come next

Dimension D1. Traces to D3.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `S3` = `S3-O2`
- `S4` = `S4-O2`
- `Q1` = `['Q1-O1']`
- `Q2` = `['Q2-O1']`
- `Q3` = `Q3-O1`
- `Q4` = `Q4-O1`
- `Q5` = `['Q5-O1']`
- `Q6` = `Q6-O1`
- `Q7` = `Q7-O1`
- `Q8` = `Q8-O1`
- `Q9` = `{'Q9-R1': 'Q9-O1', 'Q9-R2': 'Q9-O1', 'Q9-R3': 'Q9-O1', 'Q9-R4': 'Q9-O1', 'Q9-R5': 'Q9-O1', 'Q9-R6': 'Q9-O1'}`
- `Q10` = `Q10-O1`
- `Q11` = `['Q11-O1']`
- `Q12` = `Q12-O1`
- `Q13` = `Q13-O1`
- `Q15` = `Q15-O1`
- `Q16` = `Q16-O1`
- `Q18` = `{'Q18-O1': 20, 'Q18-O2': 20, 'Q18-O3': 20, 'Q18-O4': 20, 'Q18-O5': 20}`
- `Q19` = `Q19-O1`
- `Q20` = `Q20-O1`
- `Q21` = `xxxxx`
- `D1` = `D1-O1`
- `D2` = `D2-O1`
- `D3` = `D3-O1`
- `D4` = `D4-O1`
- `Q22` = `Q22-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `D3` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `D4` = `D4`
  - and the very next question the respondent sees must be this one

## Uncovered targets

No target is ever silently dropped. Each carries one specific reason.

**`INFEASIBLE`** - 1 target(s)

- D1 Q6 / hidden

## Block A - implementation conformance

Derived from the emitted `.lss` (sha `d509b2e92178`), not from a self-reported manifest.

- Questions specified: 31
- Questions built: 31
- Options bound to a physical identifier: 126
- Verdict: **CONFORMS_WITH_FINDINGS** (0 blocking)

| Finding | Severity | Count | Subjects |
|---|---|---|---|
| DISPOSITION_NOT_DISTINGUISHABLE | HIGH | 1 | TERM_AGE, TERM_CONFLICT, TERM_INVOLVEMENT, TERM_RECENT_RESEARCH |
| QUOTAS_NOT_BUILT | HIGH | 1 | QUOTA_REGION, QUOTA_AGE |
| RANDOMIZATION_NOT_BUILT | HIGH | 5 | Q1, Q5, Q9, Q16, Q19 |
| REJECT_RULE_NOT_BUILT | HIGH | 3 | R18, R19, R20 |
| SKIP_RULE_NOT_BUILT | NORMAL | 1 | R5 |
| TERMINATION_MODEL_DIFFERS | NORMAL | 1 | TERM_AGE, TERM_CONFLICT, TERM_INVOLVEMENT, TERM_RECENT_RESEARCH |

**TERMINATION_MODEL_DIFFERS** - LimeSurvey has no terminate action. The build inverts every terminate rule into the main group's relevance and nests the disposition messages into one end screen. Message text recovered for 4 of 4 screenout destinations. Assertions must test 'main group suppressed' plus 'end screen shows this text', never a page named after the disposition.

## Block C - executable compilation

- Logically covered: 162
- **Compiled to executable tests: 162**
- Refused rather than guessed: 0
- Executable coverage: **99.4%**

## Sample executable test

### `EX-eb089961e3` - answering D1 normally moves the respondent on to the question that should come next

Survey id 900001. Dimension D1. Traces to D1.

| Step | Action | Field | SGQA | Value |
|---|---|---|---|---|
| 1 | set_field | `S1` | `900001X100X1000` | `A001` |
| 2 | set_field | `S2` | `900001X100X1001` | `A001` |
| 3 | set_field | `S3` | `900001X100X1002` | `A002` |
| 4 | set_field | `S4` | `900001X100X1003` | `A002` |
| 5 | submit_page | `` | `` | `` |
| 6 | set_field | `Q1_SQ001` | `900001X101X1004SQ001` | `Y` |
| 7 | set_field | `Q2_SQ001` | `900001X101X1010SQ001` | `Y` |
| 8 | set_field | `Q3` | `900001X101X1015` | `A001` |
| 9 | set_field | `Q4` | `900001X101X1016` | `A001` |
| 10 | set_field | `Q5_SQ001` | `900001X101X1017SQ001` | `Y` |
| 11 | set_field | `Q6` | `900001X101X1025` | `A001` |
| 12 | set_field | `Q7` | `900001X101X1026` | `1` |
| 13 | set_field | `Q8` | `900001X101X1027` | `A001` |
| 14 | set_field | `Q9_SQ001` | `900001X101X1028SQ001` | `1` |
| 15 | set_field | `Q9_SQ002` | `900001X101X1028SQ002` | `1` |
| 16 | set_field | `Q9_SQ003` | `900001X101X1028SQ003` | `1` |
| 17 | set_field | `Q9_SQ004` | `900001X101X1028SQ004` | `1` |
| 18 | set_field | `Q9_SQ005` | `900001X101X1028SQ005` | `1` |
| 19 | set_field | `Q9_SQ006` | `900001X101X1028SQ006` | `1` |
| 20 | set_field | `Q10` | `900001X101X1035` | `A001` |
| 21 | set_field | `Q11_SQ001` | `900001X101X1036SQ001` | `Y` |
| 22 | set_field | `Q12` | `900001X101X1042` | `A001` |
| 23 | set_field | `Q13` | `900001X101X1043` | `1` |
| 24 | set_field | `Q15` | `900001X101X1045` | `A001` |
| 25 | set_field | `Q16` | `900001X101X1046` | `A001` |
| 26 | set_field | `Q18_SQ001` | `900001X101X1048SQ001` | `20` |
| 27 | set_field | `Q18_SQ002` | `900001X101X1048SQ002` | `20` |
| 28 | set_field | `Q18_SQ003` | `900001X101X1048SQ003` | `20` |
| 29 | set_field | `Q18_SQ004` | `900001X101X1048SQ004` | `20` |
| 30 | set_field | `Q18_SQ005` | `900001X101X1048SQ005` | `20` |
| 31 | set_field | `Q19` | `900001X101X1054` | `A001` |
| 32 | set_field | `Q20` | `900001X101X1055` | `1` |
| 33 | set_field | `Q21` | `900001X101X1056` | `xxxxx` |
| 34 | set_field | `D1` | `900001X101X1057` | `A001` |
| 35 | set_field | `D2` | `900001X101X1058` | `A001` |
| 36 | set_field | `D3` | `900001X101X1059` | `A001` |
| 37 | set_field | `D4` | `900001X101X1060` | `A001` |
| 38 | set_field | `Q22` | `900001X101X1061` | `A001` |
| 39 | submit_page | `` | `` | `` |

Assertions:

- **field_present** on `D1` = `True`
  - the question must be on screen so it can be answered
- **next_field_present** on `D2` = `D2`
  - and the very next question the respondent sees must be this one

## What v0.1 does not do

- **Block A** (implementation conformance): not implemented. Needs Agent 2's build manifest.
- **Block C** (executable compilation): logical half only. The physical half needs the manifest.
- **Blocks D, E, F**: pending design.
- **Z3**: not wired. Arithmetic and question-to-question conditions are reported `BOUND_REACHED`, never guessed.
- **B4's blind spot**: it compares, it does not re-derive. Two independently-wrong components that agree would pass. Mitigated by B2/B3 structural independence, not by a check in B4.
