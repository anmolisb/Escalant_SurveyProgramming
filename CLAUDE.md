# CLAUDE.md

This file provides the operating context, architecture, engineering rules,
scope boundaries, and implementation guidance for Claude Code working on this
repository.

Claude Code must treat this file as the primary project-level instruction
document.

---

# 1. PROJECT IDENTITY

## Project

Escalent Agentic Survey QA Platform

## Client

Escalent India Pvt. Ltd.

## Official Project Title

Agentic AI Platform for Automated Survey Programming, Route Discovery, and Quality
Assurance using Large Language Models

## Project Team

- Anmol Jindal
- Anoop Kumar
- Atishi
- Raveena Mallina
- Sanskar Jain

## Client Mentor

Sameer Saurabh

## Project Period

10 August 2026 – 30 October 2026

---

# 2. PROJECT PURPOSE

This repository contains the working prototype of an Agentic AI platform for
interpreting survey programming requirements and using the interpreted
requirements to build, test, and eventually quality-assure surveys.

The current platform workflow is:

QRE document
    ↓
Agent 1 — QRE Interpreter
    ↓
Canonical Survey Specification
    ↓
Agent 2 — Basic Survey Builder
    ↓
LimeSurvey-compatible XML
    ↓
LimeSurvey

Later phases may extend this workflow to route discovery, automated respondent
execution, and QA adjudication.

The core objective is not to assume that a QRE follows a fixed template.
Escalent QREs are not guaranteed to use one fixed document format. The system
must therefore learn to recognize and interpret the information represented in
a QRE while remaining adaptable to changes in document structure, wording,
question types, and programming conventions.

The currently available QRE corpus is synthetic and is designed to be close to
realistic Escalent QREs for development and testing. These synthetic QREs are
useful development fixtures, but they are NOT the authoritative schema for all
future QREs.

---

# 3. CURRENT PROJECT SCOPE

Two agents receive real implementation in the current phase:

1. Agent 1 — QRE Interpreter (`qre_interpretation`)
2. Agent 2 — Basic Survey Builder using LimeSurvey (`survey_builder`)

Agent 1 converts QRE documents into a structured, machine-readable survey
specification.

Agent 2 converts that canonical specification into LimeSurvey-compatible XML
and supports the basic workflow required to create/import a survey in
LimeSurvey.

Three further agents exist as STUBS ONLY. They are present in the
orchestration graph and have a reserved input/output folder and prompt module,
but return canned placeholder output rather than real logic:

- Agent 3 — Test Designer (`test_design`)
- Agent 4 — Respondent Bot (`respondent_bot`)
- Agent 5 — QA Adjudicator (`qa_adjudication`)

Stubbing all five agents early is deliberate. It allows the full pipeline to
run end to end from an early stage, so that integration failures surface while
there is still time to correct them. A crude end-to-end pipeline is a more
useful signal of project health than individually passing components that have
never been connected.

Agents 3, 4 and 5 receive real implementation only when the project team
explicitly moves them into the active build phase, in descending order of
risk.

Do not implement real logic for Agent 3, 4 or 5 merely because their folders,
stub interfaces, or prompt modules already exist. A scaffolded folder is not
authorization to build the agent behind it.

The following remain out of scope in all current phases:

- Forsta/Decipher integration
- production-grade deployment (multi-tenancy, SSO, high availability, SLA)
- translation QA
- conjoint and MaxDiff designs

---

# 4. CURRENT END-TO-END WORKFLOW

The active workflow is:

                    QRE Document
                         │
                         ▼
              ┌──────────────────────┐
              │ Agent 1              │
              │ QRE Interpreter      │
              │                      │
              │ Reader + Interpreter │
              └──────────┬───────────┘
                         │
                         ▼
              Canonical Survey
                 Specification
                         │
                         ▼
              ┌──────────────────────┐
              │ Agent 2              │
              │ Basic Survey Builder │
              └──────────┬───────────┘
                         │
                         ▼
                LimeSurvey XML
                         │
                         ▼
                  LimeSurvey
                         │
                         ▼
                  Imported Survey

The architecture must keep the canonical survey specification separate from
LimeSurvey-specific XML.

Agent 1 must NOT generate LimeSurvey XML directly.

Agent 2 is responsible for translating the canonical platform-neutral survey
specification into LimeSurvey-specific output.

---

# 5. AGENT 1 — QRE INTERPRETER

## 5.1 Purpose

Agent 1 reads a QRE and converts it into a structured representation of what
the QRE means.

Agent 1 is a compiler/interpreter-like system, not a generic chatbot.

The QRE is a human-readable specification. It is not assumed to be executable
code.

Agent 1 must preserve a chain of evidence from:

source QRE
    → extracted content
    → interpreted meaning
    → canonical specification

---

# 6. AGENT 1 INTERNAL PARTS

Agent 1 is deliberately divided into two implementation parts.

## Part 1 — QRE Reader / Extractor

Purpose:

> Faithfully extract what is present in the document before attempting to
> interpret survey semantics.

Input:

- DOCX
- PDF

Output:

- QRE Extraction Intermediate Representation (QREExtractionIR)

Part 1 is the current immediate implementation target.

## Part 2 — QRE Semantic Interpreter

Input:

- QREExtractionIR

Output:

- Canonical Survey Specification

Part 2 interprets relationships and meaning, including where applicable:

- routing
- display conditions
- skip/goto behavior
- branching
- termination
- qualification/disqualification
- validations and dependencies
- quotas
- piping
- randomization
- loops
- pivots
- route-relevant questions
- semantic question classification
- normalized predicates
- cross-reference relationships
- ambiguity

Part 2 is built only after Part 1 has a sufficiently stable extraction contract.

---

# 7. AGENT 1 PART 1 — QRE READER / EXTRACTOR

## 7.1 Objective

The objective of Part 1 is:

> Capture what the QRE says before deciding what the QRE means.

Part 1 should favor deterministic extraction over interpretation wherever
possible.

Example:

Input text:

"Show if: Q5 contains any touchpoint"

Part 1 should preserve something conceptually like:

```json
{
  "instruction_type": "display_instruction",
  "raw_text": "Show if: Q5 contains any touchpoint",
  "source_reference": {}
}
```

Part 1 should NOT decide that the semantic operator is `contains_any`.
That interpretation belongs to Part 2.

---

# 8. PART 1 INPUTS

Initial supported inputs:

- `.docx`
- `.pdf`

Initial implementation assumes text-bearing documents.

Scanned/image-only PDFs must be detected explicitly. The system must not
silently produce incomplete extraction when document content cannot be read.

Do not add support for additional document formats until representative
requirements justify it.

---

# 9. DYNAMIC QRE STRUCTURE

IMPORTANT:

Escalent QREs do not follow one fixed format.

The current synthetic QREs are realistic development fixtures and are intended
to resemble likely survey programming specifications, but their structure,
headings, field names, syntax, question types, and programming conventions are
NOT universal requirements.

The system must NOT hard-code:

- fixed section names;
- fixed section order;
- fixed table names;
- fixed column names;
- fixed question IDs;
- fixed question wording;
- fixed option names;
- fixed response codes;
- fixed routing phrases;
- fixed validation syntax;
- fixed quota syntax;
- fixed piping notation;
- fixed randomization notation;
- fixed document formatting;
- any other convention derived only from a synthetic sample.

The parser should dynamically inspect the document and identify its structure.

Known structures may be recognized when present, but unknown structures must be
preserved and surfaced rather than rejected solely because they differ from a
sample template.

---

# 10. SAMPLE QRE RULE

Synthetic QREs are development fixtures.

Use them to discover possible patterns in:

- document structure;
- question representation;
- response representation;
- instruction representation;
- routing representation;
- validation representation;
- quota representation;
- piping representation;
- randomization representation;
- ambiguity patterns.

Do NOT treat a sample QRE as the production schema.

Do NOT write code equivalent to:

```python
if section_name == "Questionnaire":
    ...
```

unless the implementation is part of a configurable/general section-detection
mechanism and does not require the section to exist in every QRE.

The correct principle is:

> Learn the concepts and patterns from the samples; do not hard-code the
> samples themselves.

---

# 11. DOCUMENT ADAPTER ARCHITECTURE

DOCX and PDF should be treated as separate ingestion problems.

Conceptually:

Document
  |
  +-- DOCX adapter
  |
  +-- PDF adapter
  |
  v
Normalized Document Representation
  |
  v
QRE Reader / Extractor

The normalized document representation should preserve, where available:

- page number;
- paragraph order;
- table structure;
- headings;
- section boundaries;
- source text;
- document position;
- source references;
- basic formatting metadata when it affects interpretation.

Do not assume DOCX and PDF have identical layout behavior.

---

# 12. PART 1 EXTRACTION CONTRACT

The output of Part 1 is an intermediate artifact.

Call it:

`QREExtractionIR`

Do NOT call it the final `SurveySpecification`.

Conceptual structure:

```text
QREExtractionIR
├── document_metadata
├── sections[]
├── questions[]
├── instructions[]
├── routing_blocks[]
├── validation_blocks[]
├── quota_blocks[]
├── randomization_blocks[]
├── piping_blocks[]
├── disposition_blocks[]
├── programming_notes[]
├── acceptance_tests[]
├── unparsed_content[]
├── extraction_review_queue[]
└── provenance[]
```

The exact field set must evolve from the QRE corpus.

Do not create a giant schema containing every hypothetical survey feature just
because such features might exist in the future.

---

# 13. PART 1 QUESTION EXTRACTION

For each detected question, capture observable information such as:

- question ID;
- question wording;
- raw question type;
- response options;
- response codes where explicitly supplied;
- scales;
- matrix rows/columns where explicit;
- raw instructions;
- validation blocks;
- routing text;
- source location.

Example:

```json
{
  "qid": "Q6",
  "text": "Which touchpoint was most influential?",
  "raw_type": "single",
  "options": [
    {"label": "Manufacturer website", "code": null},
    {"label": "Dealer visit", "code": null}
  ],
  "raw_instructions": [
    "Show if: Q5 contains any touchpoint",
    "Show only touchpoints selected at Q5."
  ],
  "source_reference": {}
}
```

Do not invent missing response codes.

If the source contains labels but no codes, use `null` rather than fabricating
codes.

---

# 14. RAW VS INFERRED INFORMATION

This distinction is mandatory.

Every important field should distinguish:

- `extracted` — directly observed in the QRE;
- `derived` — deterministically derived from extracted information;
- `inferred` — created through semantic reasoning;
- `unknown` — not available from the source;
- `ambiguous` — multiple plausible interpretations exist.

Part 1 should primarily produce `extracted` and limited `derived` information.

Part 2 may produce `inferred` and normalized information.

Never present an inference as if it were explicitly stated in the QRE.

---

# 15. PROVENANCE

Every important extracted or interpreted element should retain provenance.

The system must be able to answer:

> Where did this information come from in the QRE?

Where available, provenance should include:

- document name or identifier;
- page;
- section;
- table;
- row/column;
- paragraph/order index;
- source text;
- extraction/interpretation stage.

Example:

```json
{
  "source_reference": {
    "document": "example.qre.docx",
    "page": 4,
    "section": "Questionnaire",
    "text": "Show if: Q5 contains any touchpoint"
  }
}
```

Provenance is required for:

- review;
- debugging;
- evaluation;
- auditability;
- future QA defect traceability.

---

# 16. UNPARSED / UNKNOWN CONTENT

Never silently discard content that cannot be confidently classified.

Use an explicit structure such as:

```json
{
  "unparsed_content": [
    {
      "text": "...",
      "location": {},
      "reason": "instruction_type_not_recognized",
      "requires_review": true
    }
  ]
}
```

Unknown content is preferable to silent loss.

Part 2 may later interpret content retained by Part 1.

---

# 17. DYNAMIC ATTRIBUTE DISCOVERY

The QRE Reader must be flexible enough to encounter attributes not anticipated
by the initial schema.

However, the runtime schema must not be reinvented independently for every QRE.

Use this model:

```text
Known attribute
    → existing field

Unknown attribute
    → proposed extension
    → preserve raw value + provenance
    → review / validation
    → schema registry update if justified
```

The LLM may propose an attribute, but it must not silently change the stable
contract between agents.

Do not allow:

QRE A → schema A
QRE B → unrelated schema B
QRE C → unrelated schema C

The downstream agents need stable contracts.

---

# 18. FIELD APPLICABILITY VS FIELD REQUIREMENT

Do not use only `primary` and `secondary` to describe fields.

For each field distinguish:

1. applicability — whether the field makes sense for this object;
2. requirement — whether it must be populated when applicable.

Example:

```json
{
  "field": "matrix_rows",
  "applicability": "conditional",
  "applicable_when": {
    "question_type": ["matrix"]
  },
  "required": true
}
```

For a non-matrix question:

```json
{
  "field": "matrix_rows",
  "applicability": "not_applicable",
  "required": false
}
```

A field can therefore be:

- always applicable and required;
- always applicable but optional;
- conditionally applicable and required when applicable;
- conditionally applicable and optional;
- not applicable.

If the project uses `primary`/`secondary` terminology, treat it as presentation
metadata only, not as the underlying schema semantics.

---

# 19. PART 1 MUST NOT NORMALIZE LOGIC PREMATURELY

Part 1 may extract:

"Show if: Q5 contains any touchpoint"

Part 1 stores the statement and evidence.

Part 2 may normalize it to:

```json
{
  "operator": "contains_any",
  "source_question": "Q5",
  "values": []
}
```

Likewise:

"If Q3 = 2, skip Q4-Q7 and go to Q8"

should be preserved as source text in Part 1 and semantically normalized in
Part 2.

This boundary is essential for debugging, evaluation, and generalization.

---

# 20. PART 2 — QRE SEMANTIC INTERPRETER

Part 2 consumes QREExtractionIR and produces the Canonical Survey
Specification.

The canonical specification is platform-neutral and is not a LimeSurvey XML
file.

Part 2 may use LLM reasoning for:

- semantic question classification;
- interpreting natural-language programming instructions;
- routing conditions;
- display conditions;
- skip/goto semantics;
- branching;
- termination/disqualification;
- piping;
- randomization;
- quota semantics;
- loop semantics;
- contextual dependencies;
- pivot identification;
- route-relevant path identification;
- ambiguity handling.

Part 2 should output typed, machine-evaluable structures rather than opaque
condition strings wherever possible.

For example, prefer:

```json
{
  "operator": "contains_any",
  "question_id": "Q1",
  "values": [1, 2, 3, 4]
}
```

over:

```text
Q1 & [1,2,3,4] != []
```

The canonical form should be easy for deterministic downstream code to
validate and evaluate.

---

# 21. CANONICAL SURVEY SPECIFICATION

The Canonical Survey Specification is the stable contract consumed by Agent 2
and future agents.

It must be:

- machine-readable;
- typed;
- platform-neutral;
- versioned;
- schema validated;
- traceable to the QRE;
- reproducible;
- extensible without silently changing existing meaning.

Conceptual structure:

```text
SurveySpecification
├── metadata
├── sections[]
├── questions[]
├── response_options[]
├── display_conditions[]
├── routing_rules[]
├── validation_rules[]
├── quotas[]
├── randomization_groups[]
├── piping_rules[]
├── loops[]
├── dispositions[]
├── dependencies[]
├── pivots[]
├── path_relevant_elements[]
├── ambiguities[]
└── provenance[]
```

This is conceptual, not a fixed final schema.

The actual field set should evolve from the QRE corpus.

---

# 22. AGENT 2 — BASIC SURVEY BUILDER

Agent 2 is CURRENT SCOPE.

Agent 2 is not a survey-programming replacement. It is a basic automated
translator from the canonical platform-neutral specification into LimeSurvey
survey definition XML.

Current workflow:

Canonical Survey Specification
        ↓
Agent 2 — Survey Builder
        ↓
LimeSurvey-compatible XML
        ↓
LimeSurvey import/create workflow

---

# 23. AGENT 2 RESPONSIBILITIES

The basic Survey Builder should initially support the minimum set of survey
constructs required to demonstrate an end-to-end workflow.

It should:

1. Read the approved Canonical Survey Specification.
2. Map supported question types to LimeSurvey question types.
3. Map question IDs.
4. Map question wording.
5. Map answer options and codes.
6. Map applicable mandatory/optional behavior.
7. Map supported basic validation.
8. Map supported display/routing logic when represented in the canonical spec.
9. Generate LimeSurvey-compatible XML.
10. Validate the generated XML before output.
11. Report unsupported constructs explicitly.
12. Preserve traceability from generated XML elements back to canonical fields.

Agent 2 must NOT silently discard unsupported QRE requirements.

If a feature cannot be represented in the first LimeSurvey implementation:

- retain the unsupported requirement;
- report it;
- identify its source;
- continue only when safe;
- or block generation if the unsupported feature is critical.

---

# 24. LIMESURVEY BOUNDARY

LimeSurvey is the current survey platform used in the active prototype.

The immediate integration target is LimeSurvey-compatible XML.

The architecture should distinguish:

Canonical Survey Specification
        ↓
LimeSurvey Adapter / Builder
        ↓
LimeSurvey XML

Agent 1 must remain platform-neutral.

LimeSurvey-specific details belong in Agent 2 / the LimeSurvey adapter.

Do not put LimeSurvey-specific field names, XML syntax, or implementation
constraints into Agent 1's canonical interpretation unless they are genuinely
part of the QRE meaning.

If programmatic LimeSurvey import/API functionality is introduced, keep it
behind a separate adapter boundary and validate the actual LimeSurvey version,
API, and permissions before implementation.

---

# 25. AGENT 2 VALIDATION

Agent 2 should validate at multiple levels:

1. Canonical specification schema validation.
2. Mapping validation.
3. XML syntax validation.
4. Required LimeSurvey fields validation.
5. Unsupported-feature detection.
6. Internal consistency checks.
7. Import/round-trip validation where a LimeSurvey test environment is available.

The initial MVP should prefer deterministic XML generation and validation over
LLM-generated XML.

The LLM may assist with exceptional mapping decisions only when necessary,
but deterministic mapping tables and code should be preferred.

---

# 26. AGENT 1 → AGENT 2 CONTRACT

Agent 2 consumes ONLY the stable Canonical Survey Specification.

Do not make Agent 2 depend on:

- raw DOCX structures;
- raw PDF layout;
- Part 1 parser internals;
- prompt-specific intermediate formats.

The interface is:

QRE
 ↓
Agent 1 Part 1
 ↓
QREExtractionIR
 ↓
Agent 1 Part 2
 ↓
Canonical Survey Specification
 ↓
Agent 2
 ↓
LimeSurvey XML

This separation allows future survey platforms to reuse Agent 1.

---

# 27. AGENTS 3 TO 5

The full architecture is:

Agent 1 — QRE Interpreter
        ↓
Human approval
        ↓
Agent 2 — Survey Builder
        ↓
LimeSurvey / future survey platform
        ↓
Agent 3 — Test Designer
        ↓
Agent 4 — Respondent Bot
        ↓
Agent 5 — QA Adjudicator
        ↓
QC Report

Agent 3, Agent 4 and Agent 5 exist in the repository as stubs wired into the
orchestration graph, so that the pipeline runs end to end from an early stage.
They are not current implementation priorities.

Their interfaces may be stubbed and documented now, but real implementation
logic begins only when the project team moves them into the active build
phase. They must not drive premature implementation decisions in Agent 1 or
Agent 2.

---

# 28. FORSTA / DECIPHER — FUTURE ONLY

Forsta/Decipher is NOT being used in the current implementation.

Do not build at this stage:

- Forsta APIs;
- Decipher APIs;
- Decipher survey creation;
- Decipher survey inspection;
- Decipher respondent execution;
- Decipher-specific Playwright automation;
- Forsta-specific schema mapping.

Forsta/Decipher may be introduced later as another survey-platform adapter.

The current architecture should remain platform-neutral enough to support it
later without redesigning Agent 1.

Do not mention Decipher as the active survey platform in current implementation
logic, configuration, tests, or output formats unless a future phase explicitly
activates that integration.

---

# 29. DETERMINISTIC VS LLM RESPONSIBILITIES

## Prefer deterministic code for:

- file ingestion;
- DOCX/PDF parsing;
- document structure extraction where deterministic;
- table extraction where deterministic;
- question ID extraction where explicit;
- option extraction where explicit;
- JSON parsing;
- XML generation;
- XML validation;
- schema validation;
- reference validation;
- duplicate detection;
- missing-reference checks;
- consistency checks;
- provenance tracking;
- applicability validation;
- field requirement validation;
- file handling;
- test execution;
- scoring.

## Use LLM reasoning for:

- semantic classification;
- interpreting natural-language instructions;
- contextual relationship discovery;
- ambiguous QRE constructs;
- semantic routing normalization;
- piping semantics;
- randomization semantics;
- complex or non-standard wording;
- controlled schema-extension proposals.

Rule:

> If reliable deterministic code can solve the problem, prefer code.

Rule:

> Use the LLM where semantic reasoning is genuinely required.

---

# 30. NO HALLUCINATION

The system must never silently invent:

- questions;
- options;
- response codes;
- routing rules;
- quotas;
- randomization rules;
- piping;
- dispositions;
- validations;
- missing metadata;
- LimeSurvey-specific behavior not supported by the actual platform.

Missing information should become an explicit state such as:

- null;
- unknown;
- unresolved;
- ambiguous;
- review_required;
- unsupported;
- unparsed_content.

Never fabricate.

---

# 31. AMBIGUITY HANDLING

For uncertain interpretation:

1. retain original text;
2. retain source location;
3. provide the interpretation if possible;
4. record uncertainty metadata;
5. create a review item.

A flagged uncertainty is preferable to a silently incorrect interpretation.

---

# 32. CONFIDENCE

Confidence must exist at the object/rule level.

Do not rely only on an LLM's self-reported confidence.

Evidence-based confidence should consider, where available:

- extraction success;
- schema validity;
- reference validity;
- consistency checks;
- agreement across extraction/interpretation passes;
- source explicitness;
- ground-truth performance;
- reviewer outcomes.

Confidence thresholds are provisional until they are calibrated against an
evaluation corpus.

---

# 33. GROUND TRUTH — CURRENT STATE

There is currently NO pre-existing ground-truth dataset for the synthetic QRE
corpus.

This is a known project gap.

Ground truth must therefore be generated as part of the project.

Ground truth must NOT be generated solely by the same AI system being evaluated.

The preferred process is:

Synthetic QRE
    ↓
Human/independent expert interpretation
    ↓
Reviewed ground-truth artifact
    ↓
Agent output
    ↓
Automated comparison
    ↓
Error analysis

Where possible, use two independent reviews for high-impact logic, followed by
adjudication if they disagree.

Ground truth should be stored separately from agent outputs.

---

# 34. GROUND TRUTH FOR PART 1

Part 1 ground truth should capture, as applicable:

- detected sections;
- detected questions;
- question text;
- question types;
- options;
- response codes;
- raw instructions;
- validations;
- source references;
- unparsed content;
- expected extraction status.

The goal is to evaluate whether the reader faithfully extracted the document.

---

# 35. GROUND TRUTH FOR PART 2

Part 2 ground truth should additionally capture:

- normalized routing;
- display conditions;
- validation semantics;
- quotas;
- randomization;
- piping;
- dispositions;
- dependencies;
- pivots;
- path-relevant elements.

Ground truth should distinguish explicit source facts from human interpretation.

---

# 36. GROUND TRUTH FOR AGENT 2

Agent 2 requires a separate evaluation layer.

For representative canonical specifications, maintain expected mappings for:

- LimeSurvey question type;
- question code/ID;
- wording;
- answer options;
- mandatory/optional behavior;
- supported validation;
- supported display/routing behavior;
- generated XML structure.

Where feasible, validate generated XML by importing it into a controlled
LimeSurvey test environment and checking the resulting survey.

The agent's own generated XML must NOT be treated as ground truth.

---

# 37. EVALUATION CORPUS

The current synthetic QRE corpus is the initial development/evaluation corpus.

Use multiple QREs with varied:

- domains;
- complexity levels;
- document structures;
- question types;
- routing styles;
- validations;
- quotas;
- randomization;
- piping;
- branching;
- multi-page instructions.

Do not optimize against a single sample.

Do not assume the synthetic corpus exhaustively represents Escalent's future
QREs.

When real/sanitized Escalent QREs become available, add them as a separate
validation tier.

---

# 38. EVALUATION STRATEGY

Evaluate Agent 1 and Agent 2 separately.

## Part 1 metrics

Measure:

- question extraction precision/recall;
- option extraction accuracy;
- question-type extraction accuracy;
- instruction extraction accuracy;
- section detection performance;
- provenance accuracy;
- unparsed-content recall;
- schema validity.

## Part 2 metrics

Measure:

- semantic classification accuracy;
- routing accuracy;
- display-condition accuracy;
- validation accuracy;
- piping accuracy;
- randomization accuracy;
- quota interpretation accuracy;
- pivot/path identification accuracy;
- ambiguity detection;
- confidence calibration.

## Agent 2 metrics

Measure:

- successful mapping rate;
- XML validity rate;
- supported-feature mapping accuracy;
- unsupported-feature detection rate;
- import success rate where LimeSurvey test environment is available;
- round-trip consistency where feasible.

Project-level targets may be defined later once the evaluation corpus and
ground-truth methodology are established.

Do not claim a target is achieved until it is measured.

---

# 39. FAILURE MODES TO TEST

Actively test for:

1. missing questions;
2. wrong question IDs;
3. missing options;
4. incorrect option codes;
5. incorrect question type;
6. incorrect section detection;
7. lost table content;
8. unsupported PDF structure;
9. incorrect routing interpretation;
10. incorrect display conditions;
11. incorrect AND/OR interpretation;
12. incorrect nesting;
13. incorrect termination;
14. incorrect quota interpretation;
15. incorrect piping source;
16. incorrect multi-select piping;
17. incorrect randomization;
18. missing anchoring rules;
19. incorrect validation;
20. wrong numeric ranges;
21. missing dependencies;
22. wrong pivot classification;
23. wrong path classification;
24. hallucinated logic;
25. unresolved ambiguity treated as resolved;
26. references to non-existent questions;
27. references to non-existent options;
28. conflicting instructions;
29. duplicate question interpretation;
30. cross-page context loss;
31. silently dropped document content;
32. DOCX/PDF layout errors;
33. schema drift across QREs;
34. unsupported attribute loss;
35. LLM self-confidence falsely implying correctness;
36. incorrect LimeSurvey question-type mapping;
37. invalid LimeSurvey XML;
38. silent loss of QRE logic during XML generation;
39. unsupported LimeSurvey feature presented as successfully generated.

---

# 40. SILENT WRONG SPECIFICATION CONTROL

The highest-risk failure is:

incorrect extraction
    → incorrect interpretation
    → false confidence
    → incorrect canonical specification
    → incorrect LimeSurvey survey
    → false test result

Therefore prioritize:

- source provenance;
- independent ground truth;
- deterministic validation;
- explicit ambiguity;
- regression tests;
- reviewer attention;
- cross-stage validation.

A visible failure is preferable to a silently incorrect result.

---

# 41. REPOSITORY ARCHITECTURE

The repository structure is:

```text
Escalent_SurveyProgramming/
│
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .gitignore
│
├── docs/
│   ├── charter/
│   ├── weekly-progress/
│   ├── decks/
│   ├── architecture/
│   └── decisions/
│
├── fixtures/
│   ├── qre-samples/
│   └── holdout/
│
├── data/
│   ├── inputs/
│   │   ├── qre_interpretation/
│   │   ├── test_design/
│   │   ├── survey_builder/
│   │   ├── respondent_bot/
│   │   └── qa_adjudication/
│   │
│   ├── outputs/
│   │   ├── qre_interpretation/
│   │   ├── test_design/
│   │   ├── survey_builder/
│   │   ├── respondent_bot/
│   │   └── qa_adjudication/
│   │
│   ├── ground_truth/
│   │   ├── Synthetic/
│   │   └── Client/
│   │
│   └── runs/
│
├── src/
│   ├── agents/
│   │   ├── qre_interpretation/
│   │   ├── test_design/
│   │   ├── survey_builder/
│   │   ├── respondent_bot/
│   │   └── qa_adjudication/
│   │
│   ├── orchestration/
│   │   ├── graph.py
│   │   └── state.py
│   │
│   ├── backend/
│   ├── dashboard/
│   ├── reports/
│   ├── evaluation/
│   │
│   └── common/
│       ├── llm/
│       │   └── groq_client.py
│       ├── prompts/
│       │   ├── qre_interpretation.py
│       │   ├── test_design.py
│       │   ├── survey_builder.py
│       │   ├── respondent_bot.py
│       │   └── qa_adjudication.py
│       └── schemas/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── regression/
│   └── uat/
│
├── notebooks/
├── scripts/
└── config/
    └── .env.example
```

## Folder responsibilities

`docs/decisions/` holds the append-only decision log: one entry per
architectural decision, with date and rationale. `docs/architecture/` records
the current state; `docs/decisions/` records why it changed.

`fixtures/` is split by role, not by file format. Both folders contain a mix of
DOCX and PDF, because the reader must handle both (Section 11) and format is
already evident from the extension.

`fixtures/qre-samples/` holds the 15-QRE development corpus. Build and iterate
against these.

`fixtures/holdout/` holds 3 QREs that are NOT read during development. They
exist to measure whether the reader learned general document-processing
concepts or merely the documents it was built against — the risk Sections 9, 10
and 61 guard against by intent, and which nothing else in the project actually
measures.

Do not open, read, or run against the holdout while building the reader. Use it
only to measure extraction performance once ground truth exists for it. A
change made in response to a holdout result must be a general improvement,
never an accommodation of one document. If the holdout is ever used to debug a
specific failure, it is burned: replace it with a fresh selection and record
that in `docs/decisions/`.

See `docs/decisions/0002-corpus-development-holdout-split.md`.

`data/ground_truth/` holds independently reviewed ground-truth artifacts. It is
a sibling of `data/inputs/` and `data/outputs/`, not a child of either, because
Sections 33 and 49 require ground truth to be stored separately from agent
outputs. Ground truth is versioned and never overwritten.

It is split by provenance, and the split is a security boundary rather than a
filing convention:

- `data/ground_truth/Synthetic/` holds ground truth hand-coded from the
  synthetic QRE corpus in `fixtures/qre-samples/`. It is committed to the
  repository so that evaluation is reproducible by anyone who clones it.
- `data/ground_truth/Client/` holds ground truth derived from confidential
  Escalent material. It is never committed, per Sections 51 and 53.

`.gitignore` enforces this: everything under `data/` is ignored by default,
`data/ground_truth/Synthetic/` is re-included, and `data/ground_truth/Client/`
is explicitly re-ignored. Ground-truth artifacts must therefore be written to
the correct folder for their provenance — a client-derived artifact placed in
`Synthetic/` would be committed.

`data/runs/` holds the per-run ledger required by Section 50: document hash,
schema versions, model identifier, prompt version, code version, timestamp and
run ID.

`src/common/schemas/` holds the cross-agent contracts, `QREExtractionIR` and
the Canonical Survey Specification. These are shared interfaces rather than any
single agent's internals, and must not live inside an agent folder. See
Section 26.

`src/evaluation/` holds the evaluation harness and scoring code defined in
Sections 37 and 38. It scores all agents and therefore sits beside `agents/`
rather than inside any one of them.

`tests/unit/` covers individual components with mocked model responses.
`tests/integration/` covers the full graph executed through the supervisor.
`tests/regression/` re-runs the evaluation set after every change.
`tests/uat/` holds sponsor acceptance scripts.

Scaffold folders that are still empty carry a `.gitkeep`, because git does not
track directories. A structural folder without one is absent from a fresh
clone, which silently changes the repository other people receive.

Do not create folders merely for appearance.

Agent 1's internal stage folders (`ingestion/`, `extraction/`,
`interpretation/`, `normalization/`) in Section 42 are deliberately NOT
pre-created. They are created as the code that fills them is written, per the
instruction in Section 42 not to build abstractions before the first
representative QRE works.

Do not create real implementation inside an Agent 3, 4 or 5 folder merely
because the folder, a stub file, or a reserved prompt module already exists.

---

# 42. CURRENT AGENT 1 STRUCTURE

Each agent owns its internal pipeline stages inside its own folder under
`src/agents/`. Ingestion, extraction, interpretation and normalization are
internal to Agent 1 and are not top-level `src/` modules.

```text
src/agents/qre_interpretation/
├── __init__.py
├── agent.py
├── ingestion/
│   ├── docx_reader.py
│   ├── pdf_reader.py
│   └── normalized_document.py
├── extraction/
│   ├── reader.py
│   └── extractor.py
├── interpretation/
│   └── interpreter.py
├── normalization/
│   └── ...
├── provenance.py
├── confidence.py
└── validators.py
```

Schemas are shared contracts and live outside the agent, in
`src/common/schemas/`:

```text
src/common/schemas/
├── qre_extraction.py
├── survey_spec.py
├── question.py
├── routing.py
├── validation.py
├── quota.py
├── piping.py
├── randomization.py
└── review.py
```

Agent 1 prompts live in `src/common/prompts/qre_interpretation.py`.

This structure is provisional.

Do not create excessive abstractions before the first representative QRE works.

---

# 43. CURRENT AGENT 2 STRUCTURE

LimeSurvey-specific code is internal to Agent 2 and lives inside the agent
folder, keeping the platform adapter boundary contained in one place.

```text
src/agents/survey_builder/
├── __init__.py
├── agent.py
├── mapper.py
├── validator.py
├── provenance.py
└── limesurvey/
    ├── __init__.py
    ├── question_mapper.py
    ├── xml_generator.py
    ├── xml_validator.py
    └── adapter.py
```

Agent 2 prompts live in `src/common/prompts/survey_builder.py`.

Agents 3, 4 and 5 follow the same folder convention but contain only
`__init__.py` and a stub `agent.py` until they enter the active build phase.

The exact structure may change after the first valid LimeSurvey XML is produced.

---

# 44. PART 1 FIRST IMPLEMENTATION BOUNDARY

The immediate implementation target is:

```text
DOCX/PDF
   ↓
Document Parser
   ↓
Normalized Document Representation
   ↓
QRE Reader / Extractor
   ↓
QREExtractionIR
   ↓
Deterministic Validation
   ↓
JSON Output
```

Do not initially build real logic for:

- full semantic routing normalization, which belongs to Part 2;
- complete canonical survey interpretation;
- Agent 3 — Test Designer;
- Agent 4 — Respondent Bot;
- Agent 5 — QA Adjudicator;
- Forsta/Decipher integration.

Agents 3, 4 and 5 remain stubs wired into the orchestration graph. Keeping the
stubs is required; adding real logic to them is not.

`src/dashboard/` may be scaffolded and grown incrementally alongside the
agents. What is out of bounds at this stage is a feature-complete front end
built before Agent 1 output is stable enough to display, not the existence of
the folder or its skeleton.

Agent 2 is in project scope, but should begin only after the Agent 1 contract
required by Agent 2 is stable enough to consume.

---

# 45. AGENT 1 PART 1 DEFINITION OF DONE

Part 1 is not complete merely because it produces JSON.

A meaningful Part 1 implementation should:

- ingest representative QREs;
- read the complete document;
- support the target format(s);
- detect document structure dynamically;
- identify questions;
- identify question IDs;
- identify wording;
- identify explicit question types;
- identify options;
- identify explicit codes;
- capture raw instructions;
- capture validation blocks;
- capture visible routing instructions;
- capture randomization instructions;
- capture piping instructions;
- capture quota instructions;
- capture disposition instructions;
- preserve provenance;
- preserve unparsed content;
- distinguish extracted/derived/inferred/unknown states;
- validate the QREExtractionIR schema;
- detect duplicates and malformed objects;
- provide measurable extraction performance;
- pass regression tests on the development corpus.

Part 1 should NOT claim to have solved semantic routing.

---

# 46. AGENT 1 PART 2 DEFINITION OF DONE

Part 2 is complete when it can:

- consume QREExtractionIR;
- resolve semantic relationships;
- normalize routing;
- normalize display conditions;
- normalize validation semantics;
- identify piping;
- identify randomization;
- interpret quotas;
- identify dispositions;
- identify pivots;
- identify route-relevant elements;
- validate references;
- surface ambiguity;
- preserve provenance;
- produce confidence metadata;
- produce schema-valid Canonical Survey Specification;
- compare against independently reviewed ground truth.

---

# 47. AGENT 2 BASIC DEFINITION OF DONE

Agent 2 is complete for MVP when it can:

- consume a valid Canonical Survey Specification;
- map supported question types;
- map question IDs and wording;
- map supported options/codes;
- map mandatory/optional behavior where supported;
- map supported validation;
- map supported display/routing behavior;
- generate valid LimeSurvey-compatible XML;
- validate the XML deterministically;
- flag unsupported features;
- preserve source-to-output traceability;
- successfully import or round-trip the XML in a controlled LimeSurvey test
environment when such an environment is available.

---

# 48. DEVELOPMENT SEQUENCE

Build incrementally.

## Stage 1 — Repository and environment

Confirm:

- repository;
- Python environment;
- dependencies;
- tests;
- configuration;
- security controls.

## Stage 2 — Document ingestion

Implement the smallest useful DOCX/PDF ingestion capability based on the
representative corpus.

## Stage 3 — Normalized document representation

Create a stable internal document representation.

## Stage 4 — QRE Reader

Extract observable content deterministically where possible.

## Stage 5 — QREExtractionIR

Create Pydantic models and JSON serialization.

## Stage 6 — Part 1 validation

Add schema validation and extraction checks.

## Stage 7 — Generate reviewed ground truth

Create independent human-reviewed ground-truth artifacts from the synthetic
QRE corpus.

## Stage 8 — Part 1 evaluation

Measure extraction performance and identify failure modes.

## Stage 9 — Part 2 semantic interpreter

Build semantic interpretation only after Part 1 output is sufficiently stable.

## Stage 10 — Canonical Survey Specification

Finalize the platform-neutral downstream contract.

## Stage 11 — Part 2 validation and human review

Add deterministic checks, evidence, confidence, and review queues.

## Stage 12 — Agent 2 LimeSurvey Builder

Implement deterministic mapping from canonical specification to LimeSurvey XML.

## Stage 13 — LimeSurvey validation

Validate XML and, when available, test import/round-trip behavior in a controlled
environment.

## Stage 14 — End-to-end prototype

QRE → Agent 1 → canonical specification → Agent 2 → LimeSurvey XML → LimeSurvey.

Do not start with the entire end-to-end pipeline at once.

---

# 49. GROUND-TRUTH GENERATION WORKFLOW

Because the project currently has no existing ground truth, create it as a
separate workstream.

Recommended process:

1. Select representative synthetic QREs.
2. Independently read each QRE.
3. Hand-code the expected Part 1 extraction.
4. Independently interpret high-impact semantic rules for Part 2.
5. Review disagreements.
6. Store the adjudicated result as versioned ground truth.
7. Never overwrite prior ground-truth versions.
8. Use the ground truth to evaluate future model/code changes.

Where feasible, have a second reviewer validate critical routing, termination,
quota, validation, and piping interpretations.

Ground truth generation is part of the project's evaluation methodology, not a
post-hoc activity.

---

# 50. REPRODUCIBILITY

Every run should record:

- document ID/hash;
- QRE version if available;
- extraction schema version;
- canonical schema version;
- model identifier;
- model configuration;
- prompt/version identifier;
- code version;
- timestamp;
- run ID;
- output artifact version.

For Agent 2, also record:

- LimeSurvey mapping version;
- XML generator version;
- LimeSurvey version where known.

The same approved specification and same deterministic mapping should produce
the same LimeSurvey XML modulo non-semantic serialization differences.

---

# 51. DATA SECURITY

Escalent QREs may contain confidential client material.

Never commit:

- confidential client QREs;
- credentials;
- passwords;
- API keys;
- tokens;
- certificates;
- real respondent data;
- private exports;
- private screenshots;
- logs containing secrets.

Use:

- environment variables;
- local `.env` where required;
- `.env.example`;
- `.gitignore`.

The GitHub repository should remain private unless explicitly approved otherwise.

---

# 52. MODEL / TOOL SECURITY

## Current application LLM runtime

The current application LLM runtime is:

- Groq, with structured-output support, accessed through
  `src/common/llm/groq_client.py`.

Configuration is supplied by environment variables — `LLM_PROVIDER` and
`GROQ_API_KEY` — via `config/.env`, with placeholder values in
`config/.env.example`. Never hard-code a key or endpoint in source.

Groq is in use because no sponsor-approved Azure OpenAI endpoint has been
supplied to the team yet. This is a development-phase decision, not a
rejection of the enterprise runtime.

## The client indirection rule

All agent prompt modules in `src/common/prompts/` must call the shared client
in `src/common/llm/` rather than instantiating a provider SDK directly, so that
the runtime can be audited, rate-limited and swapped from one place.

This rule matters more than which provider is behind it. It is what makes the
eventual move to Azure OpenAI a change to one module rather than a change to
every agent. Do not import a provider SDK anywhere outside `src/common/llm/`.

## When an approved enterprise endpoint becomes available

Confidential Escalent QRE content must be processed through the
sponsor-approved enterprise endpoint once one is provided. At that point:

1. add the Azure client alongside the existing one in `src/common/llm/`;
2. select it through `LLM_PROVIDER` rather than by editing agent code;
3. update this section and record the change in `docs/decisions/`.

Until then, treat the synthetic QRE corpus as the safe development input, and
do not send confidential client material through the Groq runtime.

Claude Code is the development tool and is separate from the application
runtime.

Do not silently change the application runtime provider. A runtime change is a
project decision, not an implementation detail.

Do not send confidential client content to consumer AI services.

---

# 53. GIT RULES

Never commit:

- `.env`;
- secrets;
- credentials;
- API tokens;
- confidential client QREs;
- real respondent data;
- private exports;
- private screenshots;
- temporary logs containing credentials.

Commit:

- source code;
- schemas;
- tests;
- documentation;
- sanitized/synthetic fixtures;
- reviewed ground-truth artifacts when safe;
- evaluation infrastructure.

---

# 54. ENGINEERING PRINCIPLES

## Deterministic where possible

If reliable code can solve the problem, use code.

## LLM where semantics are required

Use the LLM for genuine interpretation, not routine parsing or validation.

## Never hallucinate

Missing or uncertain information becomes an explicit state.

## Preserve provenance

Important facts and interpretations must be traceable.

## Stable interfaces

Agents communicate through typed artifacts, not undocumented assumptions.

## Platform neutrality in Agent 1

Agent 1 describes expected survey behavior, not LimeSurvey-specific XML.

## Deterministic Survey Builder

Agent 2 should prefer deterministic mappings and XML generation.

## Reproducibility

Record model, prompt, code, schema, and output versions.

## Small working increments

Build the smallest useful implementation first.

---

# 55. LOGGING

Logs should allow the team to determine:

- which document was processed;
- which parser was used;
- which model was used when applicable;
- which prompt/version was used;
- which schema version was used;
- what validation failed;
- which review items were created;
- which output was produced.

Do not log secrets.

Do not duplicate confidential QRE content unnecessarily into logs.

---

# 56. CLAUDE CODE WORKING STYLE

When working on this repository:

1. Inspect the repository before changing it.
2. Read CLAUDE.md and relevant documentation.
3. Understand existing code before creating abstractions.
4. Prefer small, reversible changes.
5. Explain the plan before significant implementation.
6. Do not silently change architecture.
7. Do not invent requirements.
8. Ask questions only when an important architectural or scope decision is truly
   unresolved.
9. Run tests after changes.
10. Report exactly what changed.
11. Report test results.
12. Report remaining risks.
13. Keep Agent 1 Part 1 / Part 2 boundaries explicit.
14. Keep Agent 1 / Agent 2 boundaries explicit.
15. Do not prematurely implement future agents.

---

# 57. BEFORE IMPLEMENTING A COMPLEX CHANGE

Provide a concise plan containing:

1. What will change.
2. Why it is needed.
3. Files affected.
4. Tests required.
5. Risks.
6. Whether a schema or agent contract changes.

Then implement.

For small changes, do not create excessive planning overhead.

---

# 58. DO NOT ASK UNNECESSARY QUESTIONS

Ask for clarification only when:

- the decision materially affects architecture;
- requirements conflict;
- security is affected;
- scope could change;
- a required artifact is genuinely missing;
- implementation would otherwise require an unsafe assumption.

For routine implementation details, choose the simplest approach consistent with
this document.

---

# 59. CURRENT IMMEDIATE PRIORITY

The immediate implementation target is:

> **Agent 1 — Part 1: QRE Reader / Extractor.**

The immediate goal is:

> Given a representative DOCX or PDF QRE, faithfully produce a validated,
> provenance-aware QREExtractionIR in JSON.

Do not implement full semantic routing interpretation yet.

Do not implement the complete Canonical Survey Specification yet.

Do not implement real logic for Agent 3, Agent 4 or Agent 5 yet. Their stub
folders and orchestration wiring already exist and remain stubs.

Do not implement Forsta/Decipher integration.

Agent 2 remains part of the active project scope, but its implementation should
follow the stabilization of the upstream canonical specification required for
basic survey generation.

---

# 60. FIRST MEANINGFUL DELIVERABLE

The first meaningful milestone is:

Representative synthetic QRE
        ↓
Document ingestion
        ↓
Normalized Document Representation
        ↓
QRE Reader
        ↓
QREExtractionIR
        ↓
Deterministic validation
        ↓
JSON output
        ↓
Reviewed ground-truth comparison

The system should be able to show:

- what it extracted;
- what it could not extract;
- where each extracted element came from;
- what content remains unparsed;
- whether the output conforms to schema;
- how extraction performed against reviewed ground truth.

---

# 61. SAMPLE-TO-PRODUCTION GENERALIZATION RULE

Synthetic QREs are close to the expected domain but are not a fixed production
template.

Every implementation decision derived from a sample must be classified as one
of:

1. general survey concept;
2. general document-processing technique;
3. observed sample pattern;
4. Escalent-specific rule, only when confirmed by actual Escalent material.

Only categories 1 and 2 can be treated as generally applicable without review.

Category 3 must remain configurable or extensible.

Category 4 must be explicitly validated when actual Escalent QREs become
available.

---

# 62. HOW TO HANDLE NEW QRE PATTERNS

When a new QRE contains an unfamiliar pattern:

1. Preserve the raw content.
2. Determine whether deterministic extraction can capture it.
3. Determine whether it is a new semantic concept.
4. Determine whether an existing schema field can represent it.
5. If not, propose a schema extension.
6. Preserve the new pattern in the evaluation corpus.
7. Add a regression test.
8. Update documentation.
9. Only then consider changing the stable schema.

Never solve a new QRE by hard-coding its exact wording.

---

# 63. HOW TO HANDLE NEW PROJECT REQUIREMENTS

If a new sponsor requirement appears:

1. Determine whether it is already in scope.
2. Check for conflicts with this file.
3. Determine which agent/part it affects.
4. Identify architecture impact.
5. Identify schema impact.
6. Identify testing impact.
7. Identify security impact.
8. Identify timeline impact.
9. Ask for clarification if scope is ambiguous.
10. Do not silently expand scope.

---

# 64. FINAL PRINCIPLE

The platform exists to turn:

Human-readable QRE
        ↓
Faithfully extracted QRE content
        ↓
Machine-readable expected survey behavior
        ↓
LimeSurvey-specific survey representation
        ↓
LimeSurvey survey

Future phases may extend this to:

Survey
        ↓
Systematic test routes
        ↓
Observed behavior
        ↓
Deterministic comparison
        ↓
Auditable QA evidence

The most important asset is not the LLM.

It is the trustworthy machine-readable specification and the evidence chain
built around it.

Therefore prioritize:

1. correctness;
2. traceability;
3. deterministic validation;
4. reproducibility;
5. measurable accuracy;
6. explainability;
7. security;
8. practical usability;

over:

- flashy agent behavior;
- unnecessary autonomy;
- excessive framework complexity;
- premature UI development;
- unsupported assumptions;
- hard-coded sample-QRE behavior.

---

# 65. FINAL INSTRUCTION TO CLAUDE CODE

When asked to build or modify this project:

- respect the project scope;
- understand the architecture;
- prioritize the current development phase;
- inspect existing code before changing it;
- preserve the Part 1 / Part 2 boundary;
- preserve the Agent 1 / Agent 2 boundary;
- use QREExtractionIR as the Part 1 output contract;
- use Canonical Survey Specification as the Agent 2 input contract;
- keep Agent 1 platform-neutral;
- keep LimeSurvey-specific logic inside Agent 2/adapters;
- preserve raw source content;
- preserve provenance;
- distinguish extracted facts from derived and inferred interpretations;
- expose uncertainty;
- preserve unparsed content;
- prefer deterministic processing wherever possible;
- use LLM reasoning only where semantic reasoning is required;
- never hallucinate QRE requirements;
- never silently invent schema fields;
- never silently change schema contracts;
- never hard-code parameters solely because they appear in a synthetic QRE;
- never commit confidential data;
- never expose credentials;
- test every meaningful change;
- generate and maintain reviewed ground truth for evaluation;
- keep implementation simple enough for the ISB capstone timeline;
- do not implement Forsta/Decipher unless explicitly activated in a future phase;
- treat Agent 3, 4 and 5 folders as stubs to be maintained, not implementations
  to be built;
- do not silently expand scope.

## Immediate instruction

> **Build real logic only for Agent 1 — Part 1: QRE Reader / Extractor, unless
> the project team explicitly changes the scope. Agents 3, 4 and 5 remain
> stub-only.**

The immediate target is:

DOCX/PDF QRE
    ↓
Document ingestion
    ↓
Normalized Document Representation
    ↓
QRE Reader / Extractor
    ↓
QREExtractionIR
    ↓
Deterministic validation
    ↓
JSON output

First make the QRE Reader reliable, measurable, generalizable, provenance-aware,
and independently testable.
