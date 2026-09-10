# Dashboard

A single Streamlit page over the three agents. Upload a QRE, interpret it,
build the survey, design the tests.

## Running it

```bash
pip install -r requirements.txt
brew install graphviz          # or: apt-get install graphviz
PYTHONPATH=. streamlit run src/dashboard/app.py
```

`PYTHONPATH=.` is needed because Streamlit puts the script's own directory on
`sys.path`, not the repository root, so `src` would not be importable. The
graphviz *binary* is separate from the Python package of the same name; without
it the flow graph fails with "dot not found".

Agent 1 needs a Groq key in `.env` at the repository root. See
`config/.env.example`.

## What it does

| Step | Runs | Unlocked when |
|---|---|---|
| 1. Interpret the QRE | `src.agents.qre_interpretation.orchestrator` | a DOCX is uploaded |
| 2. Build the survey | `src.agents.survey_builder.build` | step 1 has written a run directory |
| 3. Design the tests | `src.agents.test_design.run` | step 2 has written a `.lss` |

Each step shells out to the agent's own entry point rather than importing it,
so the dashboard holds no pipeline logic and an agent can change without this
file changing.

## Where things are read from

Everything is read off disk, so any run can be reopened without re-running
anything. A run directory is `out/<survey>/`.

- `stage4_*.json` for the questions and routing tables
- `route_graph.gexf` for the flow graph
- `agent1_stage9_gate.json` for the approval status
- `agent3/agent3_summary.json` and `agent3/agent3_paths.json` for the test
  design figures
- `out/<survey>_generated.lss` for the survey file, which sits beside the run
  directory rather than inside it

Test design inputs, the sample size and the anchored options, are project facts
a person supplies. They live in `data/inputs/test_design/<survey>.json` and are
passed to the designer when present. Without them the quota and shuffling
checks report as blocked on a missing number.

## Known limits

The flow graph is a static image with zoom, not a pan-and-zoom canvas. For a
long questionnaire the download is easier to read than the inline view.

A run takes several minutes and holds the page while it runs. Groq's free tier
caps tokens per minute and per day, so a large QRE can exhaust the budget
partway and degrade rather than fail outright.