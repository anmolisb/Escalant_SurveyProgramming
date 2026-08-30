# Survey Builder

The Survey Builder takes the JSON files from the QRE Interpreter and builds a
`.lss` file, which is an XML file that LimeSurvey can import to create the whole
survey in one step.

## Running it

Check that the input can be built:

```bash
python -m src.agents.survey_builder.preflight fixtures/stage4-outputs/S01
```

Build it:

```bash
python -m src.agents.survey_builder.build fixtures/stage4-outputs/S01
```

The file lands in `out/`. In LimeSurvey, go to Surveys, Import, and upload it.

## What goes in

Four JSON files from the QRE Interpreter, in one folder:

| File | Holds |
|---|---|
| `stage4_survey.json` | Title and description |
| `stage4_questionnaire.json` | The questions, their answer options and any validation |
| `stage4_routing.json` | Skip and termination rules |
| `stage4_messages.json` | The messages shown at the end |

## What each file does

- **`models.py`** describes the shape of a survey. Groups hold questions,
  questions hold answer options. Nothing happens here, it just defines what a
  survey looks like so the other files agree on it.

- **`loader.py`** reads the four JSON files and works out what the survey should
  be. This is where the thinking happens: it gives every answer option a code,
  turns "stop if S1 is No" into a rule LimeSurvey understands, and decides which
  questions belong in the screening section.

- **`emitter.py`** takes that and writes it out as LimeSurvey's XML. It knows
  the quirks of the format, listed further down.

- **`preflight.py`** checks the input before anything is built and reports
  everything it cannot handle. Without it you fix one problem, rerun, and meet
  the next.

- **`build.py`** runs the whole thing: preflight, then load, then emit.

- **`tests/`** rebuilds S01 and compares it against a saved copy of known-good
  output. If a change breaks something that used to work, this catches it.

## Things LimeSurvey does that are not obvious

Every one of these caused a bug that imported cleanly and produced a broken
survey. All were found by building a survey by hand in LimeSurvey, exporting it,
and reading what LimeSurvey itself wrote.

**Answer options are stored by code, not by text.** "Yes" is stored as `A001`,
"No" as `A002`. A rule that says `S1 == 'No'` has to become `S1.NAOK == "A002"`.
Get the code wrong and the survey screens out exactly the wrong people, with no
error anywhere.

**Answer text is linked by a separate id.** The list of options and the list of
their labels are joined by an `aid` number. Join them any other way and every
option imports blank.

**Multiple-choice options are not answers.** They are "subquestions", and they
live in their own section of the file. Put them with the ordinary answers and
the question imports with no options at all.

**Question ids must not look like question names.** LimeSurvey rewrites a rule
mentioning `Q5` as though the 5 were an internal id number. If an internal id
happens to be 5, the rule is corrupted. Ids here start at 1000 to avoid that.

**Some settings need a language tag.** Anything holding text shown to the
respondent is dropped on import without one, silently.

**There is no "terminate" in LimeSurvey.** Two rules saying "stop if S1 is No"
and "stop if S2 is No" become one rule on the main section saying "only show
this if S1 is not No and S2 is not No". The logic is inverted and combined.

## What is not supported yet

- Question types other than single choice, multiple choice, free text, array
  and constant sum. Preflight will name any others it finds.
- Quota controls. The QRE Interpreter does not extract them.
- Rules combining several conditions with AND and OR in one expression.
- Rules comparing one question against another rather than against a fixed
  answer.

Preflight reports all of these before building rather than failing partway.

## Adding support for a new question type

The reliable route, and the one that produced everything above:

1. Build a question of that type by hand in LimeSurvey.
2. Export the survey as `.lss`.
3. Read the file to see what LimeSurvey actually wrote for it.
4. Add the mapping to `loader.py` and `emitter.py`.
5. Run the tests to confirm the existing surveys still build.

Step 3 matters. Guessing at the format has been wrong every time it was tried.
