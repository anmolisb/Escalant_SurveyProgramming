# Test Designer

The Test Designer takes the specification from the QRE Interpreter and, where
one exists, the `.lss` the Survey Builder produced. It works out every distinct
journey a respondent can take, writes a test case for every behaviour the
questionnaire claims, and names anything it cannot test along with the reason.

It never opens the survey. Everything here is worked out on paper, so a run
takes seconds. Actually running the tests is the Respondent Bot's job.

## Running it

With only the specification:

```bash
python -m src.agents.test_design.run out/S01_campus_cafeteria_experience
```

With the built survey and the project's declared inputs:

```bash
python -m src.agents.test_design.run out/C02_automotive_purchase_journey \
    --lss out/C02_automotive_purchase_journey_generated.lss \
    --inputs out/C02_automotive_purchase_journey/agent3_inputs.json
```

Everything lands in `out/<survey>/agent3/`.

Both flags are optional and the run degrades honestly without them rather than
guessing. Without `--lss` every test is designed but marked not runnable,
because there is no built survey to bind field names against. Without
`--inputs` the quota and shuffling checks report as blocked on a missing
number.

## What goes in

| File | Required | Holds |
|---|---|---|
| `part2_canonical.json` | Yes | The specification. Everything is derived from it |
| `agent1_decisions.json` | Recommended | Whether the three survey-wide reading rules have been signed off |
| `agent1_stage9_gate.json` | Optional | Echoed into the coverage output for traceability |
| `<survey>_generated.lss` | Optional | The built survey, passed with `--lss` |
| `agent3_inputs.json` | Optional | Two facts the questionnaire never states, passed with `--inputs` |

The inputs file supplies what the questionnaire leaves out:

```json
{
  "sample_size": 1200,
  "anchors": { "Q1": ["None of these"], "Q16": ["Other"], "Q19": [] }
}
```

`sample_size` turns a quota stated as *North = 20%* into a countable target of
240 respondents, which is the moment a test can check for. `anchors` says which
options stay pinned while the rest shuffle, because without it there is no
position to check: is "None of these" appearing third a bug or correct? An
empty list is an answer too, meaning the project has confirmed nothing is
pinned, so that check does not exist rather than sitting untested.

Every value is stamped with its origin in the output, so a reviewer can tell a
fact that came from the project from one the agent worked out itself.

## What comes out

Two files a person opens: `agent3_test_cases_with_paths.xlsx`, whose three tabs
hold the survey's distinct journeys, every test case in questionnaire order,
and what was deliberately not enumerated; and `agent3_review.md`, the whole run
in prose.

`agent3_executable_tests.json` is the Respondent Bot's input, carrying real
field names and values.

The rest are the record of every step: what needed testing, which answers were
chosen and why, what was predicted, and how each claim was judged. That is not
housekeeping. When a test fails you have to be able to say whether the survey
is wrong, the chosen answers were wrong, or the prediction was wrong.

## What each file does

- **`spec.py`** reads the QRE Interpreter's `part2_canonical.json` and turns it
  into objects. Parsing only, nothing is interpreted. It raises rather than
  defaulting, because a silently defaulted specification produces tests that
  look fine and prove nothing.

- **`semantics.py`** holds the three questions the questionnaire never answers.
  What happens when a rule mentions a question the respondent never saw? Which
  rule wins when two apply? What does "equals" mean for a set of tick-boxes? It
  reads the Interpreter's reading of each and whether a human signed it off.

- **`path_enumerator.py`** finds every point where the survey can branch, then
  builds the set of distinct journeys. Two properties are proven, not asserted:
  no two paths walk the same journey, and every branch is taken in both
  directions by at least one path.

- **`b1_targets.py`** lists every behaviour worth checking, in both directions.
  "Q6 appears when Q5 is Yes" and "Q6 does not appear when Q5 is No" are two
  separate things to prove.

- **`b2_witness.py`** works backwards from a rule to the answers that would
  trigger it, keeping the respondent alive so they actually reach the question.
  The largest file, because this is where the solving lives.

- **`b3_oracle.py`** walks the questionnaire forwards with those answers and
  predicts what should happen. It shares no code with the file above and its
  entry point takes no target argument, so it cannot lean towards a hoped-for
  result. See the note below.

- **`b4_reconcile.py`** judges whether the answers and the prediction actually
  prove the claim, and records a specific reason when they do not.

- **`compile_logical.py`** writes the test in the questionnaire's own language.
  **`a_implementation.py`** reads the built `.lss` and maps every question and
  option to its physical field. **`c_compile_executable.py`** translates the
  test into those fields, and refuses to emit anything rather than guess a
  missing identifier.

- **`paths_workbook.py`** and **`report.py`** write the reviewable output.
  **`run.py`** runs the lot. **`models.py`** defines the records passed between
  steps, using standard-library dataclasses so this module needs nothing beyond
  `openpyxl`. Swapping to Pydantic touches that one file and no field names.

## Why two of those files duplicate each other

`b2_witness.py` chooses the test answers and `b3_oracle.py` predicts the
result, working in opposite directions and sharing no code. That looks like
waste. It is the most important decision here.

If one file did both, a bug in it would produce a test and an answer key that
agree with each other and are both wrong. The test would pass and nothing
downstream could catch it, because there would be nothing to catch it against.

Three of the self-tests enforce the separation. One fails if either file
imports the other, one fails if the oracle's inputs ever change to include the
behaviour under test, and one deliberately corrupts the specification the
oracle reads and confirms the reconciler then throws the test out.

## Things LimeSurvey does that affect the tests

**There is no "terminate".** The Survey Builder handles a screen-out by hiding
the whole main section and putting a message on the final page. So a test
cannot check "the respondent reached the age screen-out". It is rewritten into
the two things actually visible: no main-section question appeared, and the end
page showed that screen-out's wording.

**Screen-outs sharing wording cannot be told apart.** C02 has four that all say
"Thank you for your interest. You do not qualify for this survey." A test
proves a screen-out happened, not which one, and is marked non-conclusive
rather than claiming full coverage. The fix is in the questionnaire.

**A tick-box option is its own field.** Single choice writes one field holding
an answer code; a tick-box answer with three options ticked writes three fields
each holding `Y`. This is why a mapping layer is unavoidable rather than a
convenience.

## What is not supported yet

- A general constraint solver. There is targeted solving for the two hard
  shapes our questionnaires contain: sums across a question's own fields, and
  rules comparing one question against another. Anything else is reported as
  "search stopped" rather than "impossible", and the two are never merged.
- The last three components: an independent second review of the finished
  tests, a running ledger of untested behaviours across surveys, and the
  packaged handoff to the Respondent Bot.
- A second structurally different complex survey. C01 and C02 share a skeleton,
  so that tier has only been exercised against one shape.

Everything the agent cannot do is named in `agent3_scenarios.json` with one of
eight reasons, never left blank.

## Tests

```bash
python -m pytest tests/test_design -q
```

Eleven checks, each guarding against a specific way this kind of tool goes
wrong. The one that matters most: it must never report a behaviour as
impossible when it is not, because that silently drops a test and the coverage
report just shows one fewer thing to do. It has caught three real bugs.

Fixtures live in `tests/test_design/canonical-outputs/`, beside the tests that
use them, the same way the Survey Builder keeps its `stage4-outputs`. The suite
refuses to run if it finds none, rather than reporting success having checked
nothing.

## A note on determinism

There is no model call anywhere in this package and no network access, so the
same specification always produces the same tests. That is the point rather
than a limitation: if the same survey produced slightly different tests each
run, a failure could never be attributed to the survey rather than to the tool.

The specification it reads is a different matter. The QRE Interpreter uses a
model where the questionnaire wrote an instruction as prose, and marks each
result extracted, derived or inferred. So the accurate claim is narrower than
"no AI in the test design": the tests follow deterministically from the
specification, and part of that specification was a model's reading of English.

For the reasoning behind the five-step design, the path selection and the
coverage model, see `docs/agent3/`.
