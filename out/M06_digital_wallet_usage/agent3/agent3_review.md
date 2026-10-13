# Agent 3 test design report - M06_digital_wallet_usage

Agent 3 v0.1. Blocks B1 to B4 implemented and run. Blocks A and C are blocked on Agent 2's build manifest; D, E and F are pending design.

## Headline

- **88 coverage targets** enumerated across nine dimensions
- **78 logically covered**, each with an independently predicted outcome
- **78 logical test cases** generated, with steps and assertions
- **0 executable tests** - Block C cannot bind a canonical id to a LimeSurvey field without Agent 2's build manifest
- **Coverage floor 50.0%** (D8). Reported as a floor, never a sum or an average
- **Specification replay: 5 agree / 0 disagree / 0 unresolved of 5** against the QRE's own acceptance scenarios

## Coverage vector

Nine dimensions, reported side by side. They count different kinds of unit, so a total would be meaningless.

| Dim | Measures | Enumerated | Covered | Logical % | Status | Why not covered |
|---|---|---|---|---|---|---|
| D1 | Visibility | 31 | 31 | 100.0% | EXHAUSTIVE | - |
| D2 | Terminal outcome | 4 | 3 | 75.0% | PARTIAL | `QUOTA_SIZE_UNDEFINED` x1 |
| D3 | Validation (explicit) | 12 | 11 | 91.7% | PARTIAL | `INFEASIBLE` x1 |
| D4 | Validation (mandatory) | 20 | 20 | 100.0% | EXHAUSTIVE | - |
| D5 | Option-source dependency | 1 | 1 | 100.0% | EXHAUSTIVE | - |
| D7 | Randomization configuration | 9 | 6 | 66.7% | PARTIAL | `RANDOMIZATION_ANCHOR_UNDEFINED` x3 |
| D8 | Quota cell state | 10 | 5 | 50.0% | PARTIAL | `QUOTA_SIZE_UNDEFINED` x5 |
| D9 | Interaction | 1 | 1 | 100.0% | BOUNDED | - |

**Floor: 50.0% (D8).** FLOOR - lowest dimension. Never a sum or an average.

**Executable coverage: 0.0%.** 0% for every target and every survey. Block C cannot bind a canonical id to a LimeSurvey field without Agent 2's build manifest, which is not published yet. Logical and executable coverage are tracked separately precisely so this gap is visible.

## Survey-wide semantics

B3's interpreter cannot run without these. They are read from Agent 1's `semantics` block and decision register, never hardcoded, so a change of ruling regenerates the tests instead of requiring a rewrite.

| Reading | Value | Origin | Status | Blocking | Agent 1 decision |
|---|---|---|---|---|---|
| unasked_reference | `condition_false` | inferred | PROVISIONAL | yes | b1d1be7181c4be03 |
| rule_precedence | `document_order_first_match` | inferred | PROVISIONAL | yes | 329a4b9757983c67 |
| multi_equality | `set_equality` | derived | PROVISIONAL | yes | b345589864cc101c |
| default_mandatory | `True` | derived | CONFIRMED | no | - |
| whitespace_is_an_answer | `not_an_answer` | agent3_fallback | PROVISIONAL | no | - |

4 reading(s) still provisional. **67 of 78 generated tests lean on at least one of them** and are tagged accordingly, so a change of ruling shows exactly which tests must be regenerated.

## Specification replay

Agent 1's own acceptance scenarios walked through B3. If B3 disagreed with a scenario the QRE author wrote, either B3 is wrong or the QRE contradicts itself.

**5 agree, 0 disagree, 0 unresolved, of 5.**

| Scenario | Purpose | Outcome | Problem |
|---|---|---|---|
| T1 | category non-user | AGREE | - |
| T2 | eligible, no problems | AGREE | - |
| T3 | problem resolved | AGREE | - |
| T4 | problem unresolved | AGREE | - |
| T5 | exclusive response validation | AGREE | - |

_UNRESOLVED means B3 declined to evaluate a condition it cannot read, which is not the same as disagreeing with the QRE. Only DISAGREE indicates a real conflict._

## Sample generated tests

### `TC-a8b01845f7` - answering D1 normally moves the respondent on to the question that should come next

Dimension D1. Traces to D1.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `S3` = `18`
- `Q1` = `Q1-O1`
- `Q2` = `Q2-O1`
- `Q3` = `Q3-O1`
- `Q4` = `Q4-O1`
- `Q5` = `Q5-O1`
- `Q6` = `Q6-O1`
- `Q7` = `['Q7-O1']`
- `Q8` = `Q8-O1`
- `Q9` = `Q9-O1`
- `Q10` = `Q10-O1`
- `Q11` = `Q11-O1`
- `Q12` = `Q12-O1`
- `Q13` = `Q13-O1`
- `D1` = `D1-O1`
- `D2` = `D2-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `D1` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `D2` = `D2`
  - and the very next question the respondent sees must be this one

### `TC-5532fdc6f0` - answering D2 normally moves the respondent on to the question that should come next

Dimension D1. Traces to D2.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `S3` = `18`
- `Q1` = `Q1-O1`
- `Q2` = `Q2-O1`
- `Q3` = `Q3-O1`
- `Q4` = `Q4-O1`
- `Q5` = `Q5-O1`
- `Q6` = `Q6-O1`
- `Q7` = `['Q7-O1']`
- `Q8` = `Q8-O1`
- `Q9` = `Q9-O1`
- `Q10` = `Q10-O1`
- `Q11` = `Q11-O1`
- `Q12` = `Q12-O1`
- `Q13` = `Q13-O1`
- `D1` = `D1-O1`
- `D2` = `D2-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `D2` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `Q14` = `Q14`
  - and the very next question the respondent sees must be this one

### `TC-f4e1e7e3f0` - answering DT1 normally moves the respondent on to the question that should come next

Dimension D1. Traces to DT1.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `S3` = `18`
- `Q1` = `Q1-O1`
- `Q2` = `Q2-O1`
- `Q3` = `Q3-O1`
- `Q4` = `Q4-O1`
- `Q5` = `Q5-O1`
- `Q6` = `Q6-O1`
- `Q7` = `['Q7-O1']`
- `Q8` = `Q8-O1`
- `Q9` = `Q9-O1`
- `Q10` = `Q10-O1`
- `Q11` = `Q11-O1`
- `Q12` = `Q12-O1`
- `Q13` = `Q13-O1`
- `D1` = `D1-O1`
- `D2` = `D2-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `DT1` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `Q1` = `Q1`
  - and the very next question the respondent sees must be this one

## Uncovered targets

No target is ever silently dropped. Each carries one specific reason.

**`INFEASIBLE`** - 1 target(s)

- D3 R9 / satisfied

**`QUOTA_SIZE_UNDEFINED`** - 6 target(s)

- D2 TERM_QUOTA_FULL / reachable
- D8 QUOTA_REGION:D1-O1 / over_target_admits
- D8 QUOTA_REGION:D1-O2 / over_target_admits
- D8 QUOTA_REGION:D1-O3 / over_target_admits
- D8 QUOTA_REGION:D1-O4 / over_target_admits
- D8 QUOTA_REGION:D1-O5 / over_target_admits

**`RANDOMIZATION_ANCHOR_UNDEFINED`** - 3 target(s)

- D7 Q13 / anchors_held
- D7 Q3 / anchors_held
- D7 Q7 / anchors_held

## Block A - implementation conformance

Derived from the emitted `.lss` (sha `7ec10128c05d`), not from a self-reported manifest.

- Questions specified: 21
- Questions built: 21
- Options bound to a physical identifier: 82
- Verdict: **CONFORMS_WITH_FINDINGS** (0 blocking)

| Finding | Severity | Count | Subjects |
|---|---|---|---|
| CARRY_FORWARD_CODE_MISMATCH | HIGH | 1 | Q7->Q8 |
| QUOTAS_NOT_BUILT | HIGH | 1 | QUOTA_REGION |
| REJECT_RULE_NOT_BUILT | HIGH | 2 | R3, R9 |
| SKIP_RULE_NOT_BUILT | NORMAL | 2 | R6, R8 |
| TERMINATION_MODEL_DIFFERS | NORMAL | 1 | TERM_INELIGIBLE |

**TERMINATION_MODEL_DIFFERS** - LimeSurvey has no terminate action. The build inverts every terminate rule into the main group's relevance and nests the disposition messages into one end screen. Message text recovered for 1 of 1 screenout destinations. Assertions must test 'main group suppressed' plus 'end screen shows this text', never a page named after the disposition.

## Block C - executable compilation

- Logically covered: 78
- **Compiled to executable tests: 78**
- Refused rather than guessed: 0
- Executable coverage: **88.6%**

## Sample executable test

### `EX-ebe4ea25c7` - answering D1 normally moves the respondent on to the question that should come next

Survey id 900001. Dimension D1. Traces to D1.

| Step | Action | Field | SGQA | Value |
|---|---|---|---|---|
| 1 | set_field | `S1` | `900001X100X1000` | `A001` |
| 2 | set_field | `S2` | `900001X100X1001` | `A001` |
| 3 | set_field | `S3` | `900001X100X1002` | `18` |
| 4 | submit_page | `` | `` | `` |
| 5 | set_field | `Q1` | `900001X101X1004` | `A001` |
| 6 | set_field | `Q2` | `900001X101X1005` | `A001` |
| 7 | set_field | `Q3` | `900001X101X1006` | `A001` |
| 8 | set_field | `Q4` | `900001X101X1007` | `1` |
| 9 | set_field | `Q5` | `900001X101X1008` | `1` |
| 10 | set_field | `Q6` | `900001X101X1009` | `1` |
| 11 | set_field | `Q7_SQ001` | `900001X101X1010SQ001` | `Y` |
| 12 | set_field | `Q8` | `900001X101X1017` | `A001` |
| 13 | set_field | `Q9` | `900001X101X1018` | `A001` |
| 14 | set_field | `Q10` | `900001X101X1019` | `1` |
| 15 | set_field | `Q11` | `900001X101X1020` | `A001` |
| 16 | set_field | `Q12` | `900001X101X1021` | `A001` |
| 17 | set_field | `Q13` | `900001X101X1022` | `A001` |
| 18 | set_field | `D1` | `900001X101X1024` | `A001` |
| 19 | set_field | `D2` | `900001X101X1025` | `A001` |
| 20 | submit_page | `` | `` | `` |

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
