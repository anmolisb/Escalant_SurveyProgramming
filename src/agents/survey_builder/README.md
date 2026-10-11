# Survey Builder

The Survey Builder takes the QRE Interpreter's canonical specification,
`part2_canonical.json`, and builds a `.lss` file, which is an XML file that LimeSurvey can import to create the whole
survey in one step.

## Running it

Build it:

```bash
python -m src.agents.survey_builder.build out/S01_campus_cafeteria_experience
```

The file lands in the run's `agent2/` folder. In LimeSurvey, go to Surveys, Import, and upload it.

A build prints one line saying where the file went. If it cannot go ahead it
says why instead.

Some inputs build correctly but contain fields LimeSurvey has no equivalent
for, which are dropped. Those are not errors, so they are not printed by
default. To see them:

```bash
python -m src.agents.survey_builder.build out/S01_campus_cafeteria_experience --notes
```

When meeting a new QRE, run preflight first. It checks the input without
building anything and reports everything it finds in one pass:

```bash
python -m src.agents.survey_builder.preflight out/S01_campus_cafeteria_experience
```

## What goes in

One file from the QRE Interpreter, `part2_canonical.json`, read from the run's
`agent1/` folder. The parts the builder uses:

| Part | Holds |
|---|---|
| `survey` | Title, QRE id and description |
| `questions` | Each question, its answer options, validation, display guard and option source |
| `randomization` | Which questions shuffle their answers |
| `rules` | Termination, skip, show and reject rules, with conditions as parsed trees |
| `dispositions` | The messages shown at the end |

## What each file does

- **`models.py`** describes the shape of a survey. Groups hold questions,
  questions hold answer options. Nothing happens here, it just defines what a
  survey looks like so the other files agree on it.

- **`loader.py`** reads the canonical specification and works out what the
  survey should be. This is where the thinking happens: it gives every answer option a code,
  turns "stop if S1 is No" into a rule LimeSurvey understands, and decides which
  questions belong in the screening section.

- **`emitter.py`** takes that and writes it out as LimeSurvey's XML. It knows
  the quirks of the format, listed further down.

- **`preflight.py`** checks the input before anything is built and reports
  everything it cannot handle. Without it you fix one problem, rerun, and meet
  the next.

- **`build.py`** runs the whole thing: preflight, then load, then emit.

- **`tests/survey_builder/`** rebuilds S01 and compares it against a saved copy
  of known-good output, and checks preflight catches what it should. If a change breaks something that used to work, this catches it.

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

**There is no "terminate" in LimeSurvey.** A rule saying "stop if S1 is No"
becomes two things: every later question in the same group gets a condition
saying "only show this if S1 is not No", and the main section gets the same
condition for every terminate rule, combined. The respondent is not stopped,
they simply run out of questions and reach the end screen.

**The survey shows one question per page.** With a whole group per page,
nothing is evaluated until the page is submitted, so a respondent who fails the
first screening question still works through the rest of the screener before
being let go. The setting is `format` in `emitter.py`.

**Randomising answers is a word, not a flag.** The `answer_order` attribute
takes `random` or `normal`.

**A text display is type `X` with the `boilerplate` theme.** It shows its
wording and asks nothing, so it is never mandatory. The S, M and C QREs use it
for messages such as "You're almost done!".

**Numeric bounds have an `_n` suffix.** They are `min_num_value_n` and
`max_num_value_n`. There are similarly named settings without the suffix that
do something else.

## What is not supported yet

- Question types other than single choice, multiple choice, free text, array,
  constant sum, numeric and text display. Preflight will name any others it finds.
- Quota controls. The specification carries them, but nothing builds them yet.
- Conditions using `sum()` or `count()`, `answered` / `unanswered`, an exact
  answer set (`Q1 == ['None of these']`), or comparing one question against
  another. The supported operators are listed in `SUPPORTED_OPS` in
  `loader.py`.
- Randomised rows on a grid. The build shuffles the answers instead, and
  preflight says so.
- Anything the QRE Interpreter puts in a question's `extra`, which is dropped.
  Preflight lists it so you can check whether it mattered.

Preflight reports all of these before building rather than failing partway.

## Adding support for a new question type

The reliable route, and the one that produced everything above:

1. Build a question of that type by hand in LimeSurvey.
2. Export the survey as `.lss`.
3. Read the file to see what LimeSurvey actually wrote for it.
4. Add the mapping to `loader.py` and `emitter.py`.
5. Run the tests to confirm the existing surveys still build.

Step 3 matters. Guessing at the format has been wrong every time it was tried.