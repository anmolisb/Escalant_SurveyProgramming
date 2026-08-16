# 0003 — Ground-truth methodology for Part 1

**Date:** 2026-08-17
**Status:** Accepted, with one open question (see "Who codes it")
**Affects:** `data/ground_truth/Synthetic/`, `src/evaluation/`, Stages 7 and 8
**Relates to:** CLAUDE.md Sections 33–35, 38, 42, 45, 49

## Context

The QRE Reader extracts 10 questions from `S01` and 99 from `QRE_3`. Nothing
currently tells us whether those are the *right* questions. The test suite
proves the extraction is internally consistent, traceable and reproducible — it
cannot prove it is correct, because every test was written from the same
understanding of the documents that produced the reader.

That gap is the difference between "extraction runs" and "extraction works", and
only ground truth closes it.

## Decision

### Format: one CSV per QRE, one row per question

Ground truth lives at `data/ground_truth/Synthetic/<document>.gt.csv`, committed
to the repository (decision 0002, enforced by `.gitignore`).

CSV was chosen over JSON or YAML for a practical reason: a human has to write
roughly 300 question rows across the corpus, and CSV opens in Excel. A format
that makes the work tedious produces either no ground truth or careless ground
truth, and careless ground truth is worse than none — it reports confident
scores against wrong answers.

The loader validates every file into a typed model, so the convenience of the
authoring format does not cost schema safety.

### Worksheets are blank, not pre-filled

`scripts/make_ground_truth_worksheet.py` emits a worksheet containing the
document's identity and an empty grid. **It deliberately does not pre-fill the
reader's answers.**

Pre-filling would halve the work and destroy the result. A reviewer shown a
plausible answer verifies it; a reviewer shown a blank field derives it. The
first produces agreement with the reader, which is precisely the thing ground
truth is supposed to measure independently. This is anchoring, it is well
documented, and it is not defeated by knowing about it.

### Scope: what a first pass covers

Per Section 34, and ordered by what the Section 38 metrics need:

| Captured | Why |
|---|---|
| Question ID | precision/recall — the primary metric |
| Question wording | catches misattributed or merged rows |
| Question type | type accuracy |
| Options and codes | option accuracy; codes catch fabrication |
| Instructions (verbatim) | instruction capture |
| Section | section detection |

Deferred to a later pass: per-element provenance (page and table coordinates).
Hand-coding source locations roughly doubles the effort and measures the part of
the reader least likely to be wrong, since provenance is carried mechanically
from ingestion rather than inferred.

### Two independent passes for high-impact documents

Section 49 asks for two independent reviews with adjudication where they
disagree. Applied in full that is 30 passes over 15 documents, which will not
happen and a methodology nobody follows is worse than an honest smaller one.

The proportionate version: **two independent passes on one document per
complexity tier** (one simple, one moderate, one complex), single-pass on the
rest. The doubled documents measure inter-coder agreement — if two humans
disagree materially on what a QRE says, that is a finding about the QRE and
about the task, and it calibrates how much to trust the single-pass files.

### Versioning

Ground truth is never overwritten (Section 49). A correction supersedes rather
than edits: the prior file is retained and the change recorded. A ground truth
that quietly changes to match the reader is not ground truth.

## Who codes it — the open question

**This decision is the team's, not the implementer's.**

Section 33 requires that ground truth not be generated solely by the AI system
being evaluated, and Section 45 forbids using the agent's own output as ground
truth. The QRE Reader is deterministic code, but it was written by Claude Code
from these same documents. If Claude Code also authors the expected answers,
both inherit the same misreadings and the evaluation reports agreement with
itself. The failure would be invisible: high scores, wrong specification, which
is exactly the silent-wrong-specification risk in Section 40.

Two workable options:

**A. Fully human-coded.** Team members read each QRE and fill the worksheets.
Strongest independence, and the only option that satisfies Section 33 without
interpretation. Cost is real: roughly 20–40 minutes per document, so about 8–10
hours across the corpus, plus the doubled tier documents.

**B. Human-coded with a non-authoring assist.** A human codes each worksheet;
tooling flags rows where their answer and the reader's differ, and the human
adjudicates each difference. This is cheaper and still human-authored, but it
reintroduces anchoring at the adjudication step, and disagreements the human
resolves in the reader's favour are no longer independent evidence.

**Recommendation: A for the three doubled tier documents, B for the remainder.**
The fully independent documents establish whether the assisted ones can be
trusted, which is a claim that can then be stated rather than assumed.

What is not acceptable under any option: Claude Code populating expected values
and a human approving them in bulk. That is the agent grading its own homework
with a signature at the bottom.

## Consequences

- Evaluation (Stage 8) is blocked on human effort, not on code. The harness will
  be ready and idle.
- Until ground truth exists, no accuracy claim about the reader is defensible.
  Section 38's closing line applies: do not claim a target is achieved until it
  is measured.
- The corpus is synthetic, so ground truth over it measures whether the reader
  reads *these documents* correctly. It cannot measure whether it will read a
  real Escalent QRE correctly. Both the holdout (0002) and real QREs remain
  necessary and neither substitutes for this.
