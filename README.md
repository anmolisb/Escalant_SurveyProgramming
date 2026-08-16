# Escalant_SurveyProgramming
Capstone Project || ISB AMPBA 2026S Storing all shared resources

# Agentic AI Platform for Automated Survey Programming & QA
- **Client:** Escalent India Pvt. Ltd.
- **Program:** ISB AMPBA Capstone Project
- **Timeline:** August–October 2026
- **Status:** Inception & Elaboration (W1–W5)

## What is this?
A platform that automates survey quality assurance using five AI agents. Today, testing a survey with 18 branch points requires checking 262,000+ paths by hand, which is impossible. This platform:
- Extracts survey logic, routing, and structure from QRE documents (QRE Interpreter)
- Generates test cases from interpreted QRE logic (Test Design)
- Builds surveys automatically in LimeSurvey Community Edition (Survey Builder)
- Simulates survey respondents via browser automation (Respondent Bot)
- Validates survey behaviour against expected routing (QA Adjudication)

Output: a reproducible QC report that proves coverage.

## Tech Stack
- **LLM access:** Groq, open-source models
- **Orchestration:** LangGraph
- **Backend:** FastAPI
- **Dashboard:** Streamlit
- **Browser automation:** Playwright
- **Survey platform:** LimeSurvey Community Edition (Docker), standing in for Escalent's production Decipher setup
- **Data validation:** Pydantic

## Repository Structure
```
├── docs/                       # Design docs, charter, decks, weekly progress
│   ├── charter/
│   ├── weekly-progress/
│   ├── decks/
│   └── architecture/
├── fixtures/                   # Static test QREs
│   └── qre-samples/
├── data/                       # Runtime agent inputs/outputs (gitignored)
│   ├── inputs/                 # per agent
│   ├── outputs/                # per agent
│   └── runs/                   # per-run logs and traces
├── src/
│   ├── agents/
│   │   ├── qre_interpretation/
│   │   ├── test_design/
│   │   ├── survey_builder/
│   │   ├── respondent_bot/
│   │   └── qa_adjudication/
│   ├── orchestration/          # LangGraph graph and shared state schema
│   ├── backend/                # FastAPI
│   ├── dashboard/               # Streamlit
│   ├── reports/                 # Report generation
│   └── common/                  # Shared LLM client and prompts
├── tests/
│   ├── unit/
│   └── uat/
├── notebooks/                   # Exploratory work
├── scripts/                     # Setup, data prep
├── config/
│   └── .env.example
├── requirements.txt
└── README.md                    # This file
```

## Documentation
All project details are in the design docs above:
- **Charter** — Full scope, success measures, milestones, risks
- **Weekly progress** — Status updates per week

## Team
| Name | Email |
|---|---|
| Anoop Kumar | Anoop_Kumar_ampba2026S@isb.edu |
| Sanskar Jain | Sanskar_Jain_ampba2026S@isb.edu |
| Anmol Jindal | anmol_jindal_ampba2026S@isb.edu |
| Raveena Mallina | Raveena_Mallina_ampba2026S@isb.edu |
| Atishi | Atishi_0099_ampba2026S@isb.edu |
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
Setup instructions will be added as code is written. For now, see the technical specifications in `docs/`.
