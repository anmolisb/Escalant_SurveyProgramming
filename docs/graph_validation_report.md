# Graph validation report

Whether the persisted NetworkX graph (`part2_route_graph.json`) faithfully
represents the validated canonical specification, and whether walking it
produces the behaviour the QRE itself expects. No model calls; no Stage 4 or
Part 2 re-run - every check reads artifacts already on disk.

## Aggregate result

**OVERALL GRAPH STATUS: READY_WITH_WARNINGS**

**AGENT 3 INPUT STATUS: READY**

## Per survey

| Survey | Structural | Behavioural | Tests | Pass | Fail | Unverified | Blocked | Agent 3 input |
|---|---|---|---|---|---|---|---|---|
| S01 | READY | READY | 13 | 13 | 0 | 0 | 0 | READY |
| C01 | READY | READY_WITH_WARNINGS | 51 | 46 | 0 | 5 | 0 | READY |
| C02 | READY | READY_WITH_WARNINGS | 51 | 46 | 0 | 5 | 0 | READY |

## S01 — S01_campus_cafeteria_experience

### Structural preservation, by category (A–J)

| Category | Coverage |
|---|---|
| Node preservation (A) | 12/12 (100%) |
| Routing / show transition (B) | 1/1 (100%) |
| Skip logic (D) | 1/1 (100%) |
| Termination (E) | 2/2 (100%) |
| Display / guards (C) | 1/1 (100%) |
| Validation / reject rules (F) | n/a |
| Dependency / piping (G) | 2/2 (100%) |
| Randomization (H) | n/a |
| Quotas (I) | n/a |
| Traceability (J) | 4/4 (100%) |

### Structural findings

None. Every node, edge, guard, dependency,
quota and metadata field checked matches the canonical specification.

### Behavioural tests

All behavioural tests PASS.

### Agent 3 input sufficiency

| Test class | Status |
|---|---|
| route tests | READY |
| branch condition tests | READY |
| termination tests | READY |
| validation negative tests | READY_VIA_CANONICAL_SPEC |
| dependency piping tests | READY |
| randomization tests | READY_VIA_CANONICAL_SPEC |
| quota tests | READY_VIA_CANONICAL_SPEC |
| acceptance tests | READY_VIA_CANONICAL_SPEC |

Must be read from the canonical specification, not the graph:

- **question wording, option labels, message text** — deliberately kept out of every node and edge; the graph carries ids and structure only
- **validation bounds (min/max length, min/max value, min_selections, sum_to, require_each_row, exclusive_option, mandatory)** — reject rules are recorded as a constraint, not an edge with the bound attached
- **acceptance scenarios** — specification-level ground truth; never represented as graph structure
- **study metadata and programming/QA requirements** — survey-level statements, not structural facts about any one node or edge
- **quota cell targets and percentages** — the graph records that a quota edge exists and is stateful, not its groups or targets
- **the human decision register's resolutions** — a graph edge exists whether or not its condition has been confirmed; the graph alone cannot say which of its own transitions are still provisional

### Shareable exports

- `out/S01_campus_cafeteria_experience/route_graph.graphml`
- `out/S01_campus_cafeteria_experience/route_graph.gexf`
- `out/S01_campus_cafeteria_experience/dependency_graph.graphml`
- `out/S01_campus_cafeteria_experience/dependency_graph.gexf`

## C01 — C01_chronic_care_patient_journey

### Structural preservation, by category (A–J)

| Category | Coverage |
|---|---|
| Node preservation (A) | 37/37 (100%) |
| Routing / show transition (B) | 12/12 (100%) |
| Skip logic (D) | 1/1 (100%) |
| Termination (E) | 4/4 (100%) |
| Display / guards (C) | 13/13 (100%) |
| Validation / reject rules (F) | 3/3 (100%) |
| Dependency / piping (G) | 6/6 (100%) |
| Randomization (H) | 5/5 (100%) |
| Quotas (I) | 2/2 (100%) |
| Traceability (J) | 22/22 (100%) |

### Structural findings

None. Every node, edge, guard, dependency,
quota and metadata field checked matches the canonical specification.

### Behavioural tests


5 UNVERIFIED (no independent oracle exists — needs a person):
- `G011` [display] Q2
- `G012` [display] Q3
- `G013` [display] Q6
- `G040` [quota] QUOTA_REGION
- `G041` [quota] QUOTA_AGE

### Agent 3 input sufficiency

| Test class | Status |
|---|---|
| route tests | READY |
| branch condition tests | READY |
| termination tests | READY |
| validation negative tests | READY_VIA_CANONICAL_SPEC |
| dependency piping tests | READY |
| randomization tests | READY_VIA_CANONICAL_SPEC |
| quota tests | READY_VIA_CANONICAL_SPEC |
| acceptance tests | READY_VIA_CANONICAL_SPEC |

Must be read from the canonical specification, not the graph:

- **question wording, option labels, message text** — deliberately kept out of every node and edge; the graph carries ids and structure only
- **validation bounds (min/max length, min/max value, min_selections, sum_to, require_each_row, exclusive_option, mandatory)** — reject rules are recorded as a constraint, not an edge with the bound attached
- **acceptance scenarios** — specification-level ground truth; never represented as graph structure
- **study metadata and programming/QA requirements** — survey-level statements, not structural facts about any one node or edge
- **quota cell targets and percentages** — the graph records that a quota edge exists and is stateful, not its groups or targets
- **the human decision register's resolutions** — a graph edge exists whether or not its condition has been confirmed; the graph alone cannot say which of its own transitions are still provisional

### Shareable exports

- `out/C01_chronic_care_patient_journey/route_graph.graphml`
- `out/C01_chronic_care_patient_journey/route_graph.gexf`
- `out/C01_chronic_care_patient_journey/dependency_graph.graphml`
- `out/C01_chronic_care_patient_journey/dependency_graph.gexf`

## C02 — C02_automotive_purchase_journey

### Structural preservation, by category (A–J)

| Category | Coverage |
|---|---|
| Node preservation (A) | 37/37 (100%) |
| Routing / show transition (B) | 12/12 (100%) |
| Skip logic (D) | 1/1 (100%) |
| Termination (E) | 4/4 (100%) |
| Display / guards (C) | 13/13 (100%) |
| Validation / reject rules (F) | 3/3 (100%) |
| Dependency / piping (G) | 6/6 (100%) |
| Randomization (H) | 5/5 (100%) |
| Quotas (I) | 2/2 (100%) |
| Traceability (J) | 22/22 (100%) |

### Structural findings

None. Every node, edge, guard, dependency,
quota and metadata field checked matches the canonical specification.

### Behavioural tests


5 UNVERIFIED (no independent oracle exists — needs a person):
- `G011` [display] Q2
- `G012` [display] Q3
- `G013` [display] Q6
- `G040` [quota] QUOTA_REGION
- `G041` [quota] QUOTA_AGE

### Agent 3 input sufficiency

| Test class | Status |
|---|---|
| route tests | READY |
| branch condition tests | READY |
| termination tests | READY |
| validation negative tests | READY_VIA_CANONICAL_SPEC |
| dependency piping tests | READY |
| randomization tests | READY_VIA_CANONICAL_SPEC |
| quota tests | READY_VIA_CANONICAL_SPEC |
| acceptance tests | READY_VIA_CANONICAL_SPEC |

Must be read from the canonical specification, not the graph:

- **question wording, option labels, message text** — deliberately kept out of every node and edge; the graph carries ids and structure only
- **validation bounds (min/max length, min/max value, min_selections, sum_to, require_each_row, exclusive_option, mandatory)** — reject rules are recorded as a constraint, not an edge with the bound attached
- **acceptance scenarios** — specification-level ground truth; never represented as graph structure
- **study metadata and programming/QA requirements** — survey-level statements, not structural facts about any one node or edge
- **quota cell targets and percentages** — the graph records that a quota edge exists and is stateful, not its groups or targets
- **the human decision register's resolutions** — a graph edge exists whether or not its condition has been confirmed; the graph alone cannot say which of its own transitions are still provisional

### Shareable exports

- `out/C02_automotive_purchase_journey/route_graph.graphml`
- `out/C02_automotive_purchase_journey/route_graph.gexf`
- `out/C02_automotive_purchase_journey/dependency_graph.graphml`
- `out/C02_automotive_purchase_journey/dependency_graph.gexf`
