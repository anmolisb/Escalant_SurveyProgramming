# Agent 4 (Respondent Bot) — Current Status

## What works right now

`smoke_test.py` is a proof-of-concept that proves the core wiring works,
end to end, against a real, live LimeSurvey survey:

1. Opens a live survey in a real browser (via Playwright)
2. Clicks through LimeSurvey's welcome/intro screen automatically
3. Finds whichever question is on the page (free-text or single-choice)
4. Fills it in / selects an answer
5. Clicks "Next"
6. Confirms the page actually moved forward

This does **not** yet read Agent 3's generated test cases — it just proves
the mechanics work. That's the next real piece of work (see below).

## How to run it

```bash
source venv/bin/activate
python src/agents/respondent_bot/smoke_test.py --sid <your survey id> --headed
```

`--headed` shows the browser window so you can watch it work. Drop it to
run invisibly once you trust it.

## Known issue: LimeSurvey's "editor" page is broken in this Docker image

Trying to activate a survey through the normal browser UI (the checkmark
icon on the survey list, or clicking into the survey's editor) fails with
a blank page. Opening the browser console shows several JS files 404ing
(`lib-router.js`, `lib-axios.js`, etc.) — genuinely missing from this image,
not a local misconfiguration. Restarting the container does not fix it.

**Workaround:** `activate_survey.py` (at the repo root) activates a survey
via LimeSurvey's RPC API directly, bypassing the broken page entirely.
Before running it, turn on the RPC interface once via Global Settings →
Interfaces → RPC interface enabled → JSON-RPC (already on by default in
this image) and Publish API on /admin/remotecontrol → On.

```bash
python activate_survey.py
```

Edit `SURVEY_ID` at the top of the file for whichever survey you're
activating.

## What's still TODO (next person to pick this up)

- Read Agent 3's actual `c_executable_tests.json` output instead of just
  finding whatever question is on the page (there's a fuller `run.py`
  scaffold already sketched out for this — reading Agent 3's real schema)
- Handle matrix (F), multi-select (M), and constant-sum (K) question types
  — smoke_test.py only handles free-text and single-choice so far
- Check Agent 3's `assertions` against what actually happened, rather than
  just confirming the page moved forward
- Run more than one test case per invocation
