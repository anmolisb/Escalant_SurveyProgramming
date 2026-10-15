# Web app

The browser front end for the pipeline: upload a questionnaire, run the
agents, and see what every agent produced. It talks to a small Python API
(`src/api/`), which reads the run folders under `out/` and starts the agents.

## Run it

The built site (`frontend/dist`) is committed, so using the app needs only
Python:

```bash
python -m src.api.server
```

and open http://localhost:8000.

## After changing the frontend

Whoever changes the code in `frontend/src` rebuilds the site and commits
`frontend/dist` in the same commit. Otherwise everyone else keeps seeing the
old version. This needs Node.js:

```bash
cd frontend
npm install
npm run build
cd ..
```

## Checking a questionnaire

1. **Check a questionnaire** (top of the page): upload the `.docx`. Agents 1
   to 3 start straight away; the survey's page shows each one working and what
   it prints.
2. Download the survey file, import it into LimeSurvey and activate it.
3. On the survey's page, give the survey id and LimeSurvey's address, then
   **Run the tests**. Agent 4 runs, then Agent 5. The app first checks that
   LimeSurvey answers and the survey is active, so a wrong id cannot replace
   the last results with blocked tests.

Each stage on the survey's overview has its own button to run it again. A
button runs that agent and every later one that needs nothing from a person.

The agents run exactly as they do from the command line, one process each.
What they print is kept in `out/<survey>/run.log`. Uploads are kept in
`data/uploads/`, which git ignores, so a client's questionnaire is never
committed. Agent 1 needs the Groq key in `.env`, as on the command line.

Results made from older tests are not shown as current. Agent 4 records which
tests it ran and Agent 5 which bot run it explained, so after the tests are
designed again the earlier run shows as "not run yet" until it is repeated.

The app runs one job per survey at a time. Stopping the server stops tracking
a running job, so let a run finish before stopping it.

## While changing the frontend

Run the API and Vite's dev server side by side; the page reloads on every
save and forwards `/api` to the API:

```bash
python -m src.api.server        # terminal 1
cd frontend && npm run dev      # terminal 2, then open http://localhost:5173
```

The flow graph and journey diagrams are drawn by Graphviz on the API side, so
the Graphviz program must be installed.

## Mac and Windows

Everything runs the same on both. The differences are only in setup:

| | Mac | Windows |
|---|---|---|
| Node.js (only to change the frontend) | `brew install node` | installer from nodejs.org |
| Graphviz | `brew install graphviz` | the zip from graphviz.org, unzipped, with its `bin` folder on PATH |
| Python packages | `pip install -r requirements.txt` | the same, in PowerShell |

The commands in this file are identical on both.
