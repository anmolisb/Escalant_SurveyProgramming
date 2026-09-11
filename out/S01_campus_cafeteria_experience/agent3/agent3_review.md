# Agent 3 test design report - S01_campus_cafeteria_experience

Agent 3 v0.1. Blocks B1 to B4 implemented and run. Blocks A and C are blocked on Agent 2's build manifest; D, E and F are pending design.

## Headline

- **35 coverage targets** enumerated across nine dimensions
- **35 logically covered**, each with an independently predicted outcome
- **35 logical test cases** generated, with steps and assertions
- **0 executable tests** - Block C cannot bind a canonical id to a LimeSurvey field without Agent 2's build manifest
- **Coverage floor 100.0%** (D1). Reported as a floor, never a sum or an average
- **Specification replay: 3 agree / 0 disagree / 0 unresolved of 3** against the QRE's own acceptance scenarios

## Coverage vector

Nine dimensions, reported side by side. They count different kinds of unit, so a total would be meaningless.

| Dim | Measures | Enumerated | Covered | Logical % | Status | Why not covered |
|---|---|---|---|---|---|---|
| D1 | Visibility | 14 | 14 | 100.0% | EXHAUSTIVE | - |
| D2 | Terminal outcome | 3 | 3 | 100.0% | EXHAUSTIVE | - |
| D3 | Validation (explicit) | 6 | 6 | 100.0% | EXHAUSTIVE | - |
| D4 | Validation (mandatory) | 10 | 10 | 100.0% | EXHAUSTIVE | - |
| D6 | Text-pipe dependency | 1 | 1 | 100.0% | EXHAUSTIVE | - |
| D9 | Interaction | 1 | 1 | 100.0% | BOUNDED | - |

**Floor: 100.0% (D1).** FLOOR - lowest dimension. Never a sum or an average.

**Executable coverage: 0.0%.** 0% for every target and every survey. Block C cannot bind a canonical id to a LimeSurvey field without Agent 2's build manifest, which is not published yet. Logical and executable coverage are tracked separately precisely so this gap is visible.

## Survey-wide semantics

B3's interpreter cannot run without these. They are read from Agent 1's `semantics` block and decision register, never hardcoded, so a change of ruling regenerates the tests instead of requiring a rewrite.

| Reading | Value | Origin | Status | Blocking | Agent 1 decision |
|---|---|---|---|---|---|
| unasked_reference | `condition_false` | inferred | PROVISIONAL | yes | 134511cac21dfa7d |
| rule_precedence | `document_order_first_match` | inferred | PROVISIONAL | yes | 3c988435446a4710 |
| multi_equality | `set_equality` | derived | CONFIRMED | no | - |
| default_mandatory | `True` | derived | CONFIRMED | no | - |

2 reading(s) still provisional. **4 of 35 generated tests lean on at least one of them** and are tagged accordingly, so a change of ruling shows exactly which tests must be regenerated.

## Specification replay

Agent 1's own acceptance scenarios walked through B3. If B3 disagreed with a scenario the QRE author wrote, either B3 is wrong or the QRE contradicts itself.

**3 agree, 0 disagree, 0 unresolved, of 3.**

| Scenario | Purpose | Outcome | Problem |
|---|---|---|---|
| T1 | recent-use screenout | AGREE | - |
| T2 | eligible with problem | AGREE | - |
| T3 | eligible without problem | AGREE | - |

_UNRESOLVED means B3 declined to evaluate a condition it cannot read, which is not the same as disagreeing with the QRE. Only DISAGREE indicates a real conflict._

## Sample generated tests

### `TC-611fbac190` - answering Q1 normally moves the respondent on to the question that should come next

Dimension D1. Traces to Q1.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `Q1` = `Q1-O1`
- `Q2` = `Q2-O1`
- `Q3` = `Q3-O1`
- `Q4` = `['Q4-O1']`
- `Q5` = `Q5-O1`
- `Q6` = `xxxxxxxxxx`
- `Q7` = `Q7-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `Q1` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `Q2` = `Q2`
  - and the very next question the respondent sees must be this one

### `TC-86937a6bf5` - answering Q2 normally moves the respondent on to the question that should come next

Dimension D1. Traces to Q2.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `Q1` = `Q1-O1`
- `Q2` = `Q2-O1`
- `Q3` = `Q3-O1`
- `Q4` = `['Q4-O1']`
- `Q5` = `Q5-O1`
- `Q6` = `xxxxxxxxxx`
- `Q7` = `Q7-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `Q2` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `Q3` = `Q3`
  - and the very next question the respondent sees must be this one

### `TC-98e19afc55` - answering Q3 normally moves the respondent on to the question that should come next

Dimension D1. Traces to Q3.

Setup, to reach the question under test:

- `S1` = `S1-O1`
- `S2` = `S2-O1`
- `Q1` = `Q1-O1`
- `Q2` = `Q2-O1`
- `Q3` = `Q3-O1`
- `Q4` = `['Q4-O1']`
- `Q5` = `Q5-O1`
- `Q6` = `xxxxxxxxxx`
- `Q7` = `Q7-O1`

Action: Answer through the whole survey as listed, then observe where it ends.

Then check:

- **question_visible** `Q3` = `True`
  - the question must be on screen so it can be answered
- **next_question_is** `Q4` = `Q4`
  - and the very next question the respondent sees must be this one

## Uncovered targets

No target is ever silently dropped. Each carries one specific reason.

## Block A - implementation conformance

Derived from the emitted `.lss` (sha `13d9f0778d10`), not from a self-reported manifest.

- Questions specified: 10
- Questions built: 10
- Options bound to a physical identifier: 36
- Verdict: **CONFORMS_WITH_FINDINGS** (0 blocking)

| Finding | Severity | Count | Subjects |
|---|---|---|---|
| SKIP_RULE_NOT_BUILT | NORMAL | 1 | R4 |
| TERMINATION_MODEL_DIFFERS | NORMAL | 1 | TERM_INELIGIBLE |

**TERMINATION_MODEL_DIFFERS** - LimeSurvey has no terminate action. The build inverts every terminate rule into the main group's relevance and nests the disposition messages into one end screen. Message text recovered for 1 of 1 screenout destinations. Assertions must test 'main group suppressed' plus 'end screen shows this text', never a page named after the disposition.

## Block C - executable compilation

- Logically covered: 35
- **Compiled to executable tests: 35**
- Refused rather than guessed: 0
- Executable coverage: **100.0%**

## Sample executable test

### `EX-2684e791b9` - answering Q1 normally moves the respondent on to the question that should come next

Survey id 900001. Dimension D1. Traces to Q1.

| Step | Action | Field | SGQA | Value |
|---|---|---|---|---|
| 1 | set_field | `S1` | `900001X100X1000` | `A001` |
| 2 | set_field | `S2` | `900001X100X1001` | `A001` |
| 3 | submit_page | `` | `` | `` |
| 4 | set_field | `Q1` | `900001X101X1002` | `A001` |
| 5 | set_field | `Q2` | `900001X101X1003` | `1` |
| 6 | set_field | `Q3` | `900001X101X1004` | `1` |
| 7 | set_field | `Q4_SQ001` | `900001X101X1005SQ001` | `Y` |
| 8 | set_field | `Q5` | `900001X101X1012` | `A001` |
| 9 | set_field | `Q6` | `900001X101X1013` | `xxxxxxxxxx` |
| 10 | set_field | `Q7` | `900001X101X1014` | `A001` |
| 11 | submit_page | `` | `` | `` |

Assertions:

- **field_present** on `Q1` = `True`
  - the question must be on screen so it can be answered
- **next_field_present** on `Q2` = `Q2`
  - and the very next question the respondent sees must be this one

## What v0.1 does not do

- **Block A** (implementation conformance): not implemented. Needs Agent 2's build manifest.
- **Block C** (executable compilation): logical half only. The physical half needs the manifest.
- **Blocks D, E, F**: pending design.
- **Z3**: not wired. Arithmetic and question-to-question conditions are reported `BOUND_REACHED`, never guessed.
- **B4's blind spot**: it compares, it does not re-derive. Two independently-wrong components that agree would pass. Mitigated by B2/B3 structural independence, not by a check in B4.
