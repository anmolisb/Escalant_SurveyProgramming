# Escalant_SurveyProgramming
Capstone Project || ISB AMPBA 2026S Storing all shared resources

# Agentic AI Platform for Automated Survey Programming & QA
- **Client:** Escalent India Pvt. Ltd.
- **Program:** ISB AMPBA Capstone Project
- **Timeline:** August–October 2026
- **Status:** Inception & Elaboration (W1–W5)

## What is this?
A platform that automates survey quality assurance using five AI agents. Today, testing a survey with 18 branch points requires checking 262,000+ paths by hand, which is impossible.

The five agents, in pipeline order:

| # | Agent | Does | Status |
|---|---|---|---|
| 1 | QRE Interpreter | Extracts survey logic, routing, and structure from QRE documents | **Being built** |
| 2 | Survey Builder | Builds the survey in LimeSurvey Community Edition | **In scope, after Agent 1** |
| 3 | Test Design | Generates test cases from the interpreted QRE logic | Stub |
| 4 | Respondent Bot | Simulates survey respondents via browser automation | Stub |
| 5 | QA Adjudication | Validates observed survey behaviour against the expected spec | Stub |

Output: a reproducible QC report that proves coverage.

**Current build status.** Only Agents 1 and 2 receive real implementation in this phase. Agents 3, 4 and 5 exist as stubs wired into the orchestration graph, returning placeholder output, so that the full pipeline runs end to end early and integration failures surface while there is still time to fix them. They receive real logic only when the team explicitly moves them into the active build phase. A folder or stub existing is not authorization to build the agent behind it — see `CLAUDE.md` Section 3.

## Tech Stack
- **LLM access:** Groq, open-source models
- **Orchestration:** LangGraph
- **Backend:** FastAPI
- **Dashboard:** Streamlit
- **Browser automation:** Playwright
- **Survey platform:** LimeSurvey Community Edition (Docker). Forsta/Decipher is out of scope for the current phase and may be added later as a second platform adapter; Agent 1 stays platform-neutral so that remains possible
- **Data validation:** Pydantic

## Repository Structure
```
├── CLAUDE.md                    # Authoritative project instructions (read first)
├── docs/
│   ├── charter/
│   ├── weekly-progress/
│   ├── decks/
│   ├── architecture/            # Current-state architecture notes
│   └── decisions/               # Append-only decision log: what changed and why
├── fixtures/                    # Synthetic QRE corpus (committed), split by
│   │                            #   role; each folder mixes DOCX and PDF
│   ├── qre-samples/             # 15 QREs - develop against these
│   └── holdout/                 # 3 QREs - do not read during development
├── data/                        # Runtime data. Ignored by git EXCEPT where noted
│   ├── inputs/                  # per agent (ignored)
│   ├── outputs/                 # per agent (ignored)
│   ├── ground_truth/
│   │   ├── Synthetic/           # COMMITTED - reviewed ground truth for the
│   │   │                        #   synthetic corpus, so evaluation is
│   │   │                        #   reproducible from a clone
│   │   └── Client/              # Never committed - confidential
│   └── runs/                    # per-run logs and traces (ignored)
├── src/
│   ├── agents/
│   │   ├── qre_interpretation/  # Agent 1 - real implementation
│   │   ├── survey_builder/      # Agent 2 - real implementation
│   │   ├── test_design/         # Agent 3 - stub
│   │   ├── respondent_bot/      # Agent 4 - stub
│   │   └── qa_adjudication/     # Agent 5 - stub
│   ├── orchestration/           # LangGraph graph and shared state schema
│   ├── backend/                 # FastAPI
│   ├── dashboard/               # Streamlit
│   ├── reports/                 # Report generation
│   ├── evaluation/              # Scoring harness; scores all agents
│   └── common/
│       ├── llm/                 # Shared LLM client - the only place a
│       │                        #   provider SDK may be imported
│       ├── prompts/             # Per-agent prompt modules
│       └── schemas/             # Cross-agent contracts: QREExtractionIR and
│                                #   the Canonical Survey Specification
├── tests/
│   ├── unit/                    # Components, with mocked model responses
│   ├── integration/             # Full graph through the supervisor
│   ├── regression/              # Re-runs the evaluation set after every change
│   └── uat/                     # Sponsor acceptance scripts
├── notebooks/                   # Exploratory work
├── scripts/                     # Setup, data prep
├── config/
│   └── .env.example
├── requirements.txt
└── README.md                    # This file
```

**A note on `data/`.** Everything under `data/` is gitignored by default, with one deliberate exception: `data/ground_truth/Synthetic/` is committed, because evaluation has to be reproducible by anyone who clones the repository. `data/ground_truth/Client/` stays ignored. Write ground-truth artifacts into the folder matching their provenance — a client-derived artifact placed in `Synthetic/` would be committed.

## Documentation
- **`CLAUDE.md`** — the authoritative project document: scope, architecture, agent contracts, engineering rules, evaluation strategy and security requirements. Start here.
- **`docs/decisions/`** — append-only log of architectural decisions and their rationale.
- **`docs/architecture/`** — current-state architecture notes.
- **`docs/charter/`**, **`docs/weekly-progress/`**, **`docs/decks/`** — sponsor-facing material. Currently empty; the charter content has been folded into `CLAUDE.md`.

## Team
| Role | Name | Email |
|---|---|---|
| Team | Anoop Kumar | Anoop_Kumar_ampba2026S@isb.edu |
| Team | Sanskar Jain | Sanskar_Jain_ampba2026S@isb.edu |
| Team | Anmol Jindal | anmol_jindal_ampba2026S@isb.edu |
| Team | Raveena Mallina | Raveena_Mallina_ampba2026S@isb.edu |
| Team | Atishi | Atishi_0099_ampba2026S@isb.edu |
| Client Mentor | Sameer Saurabh | sameer.saurabh@escalent.co |
| Faculty Mentor | Ram Vempati | ramakrishna.vempati@gmail.com |

## Milestones
| Gate | Date | What's due |
|---|---|---|
| M1 | 14 Aug | Scope agreed, platform feasibility proven |
| M2 | 11 Sep | Full pipeline runs end-to-end |
| M3 | 9 Oct | Every agent meets accuracy targets |
| M4 | 16 Oct | Soft launch, UAT, final benchmark |

## Building
No application code exists yet. Setup instructions and pinned dependencies will be added with the first implementation. For scope, architecture and engineering rules in the meantime, see `CLAUDE.md`.
