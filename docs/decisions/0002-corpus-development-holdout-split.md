# 0002 — Split the synthetic corpus into a development set and a holdout

**Date:** 2026-08-17
**Status:** Accepted
**Affects:** `fixtures/`, evaluation strategy (CLAUDE.md Sections 9, 10, 37, 61)

## Context

The repository held 18 synthetic QREs in two folders: `fixtures/qre-samples/`
(15 DOCX) and `fixtures/test-samples/` (3 PDF). The names implied a
development/test split, but the actual division was by **file format**, not by
role. Nothing was held back from development, and the naming invited the
opposite assumption.

This matters because the project's central technical risk, stated repeatedly in
CLAUDE.md, is a reader that learns the sample documents rather than the
concepts behind them. Section 9 forbids hard-coding section names, headings,
question ID patterns or routing phrases. Section 10 says to learn patterns from
the samples but not to hard-code the samples. Section 61 requires every
sample-derived decision to be classified by how far it generalizes. All three
are disciplines of intent — none of them **measures** whether we succeeded.

A holdout measures it. It is the cheapest instrument available for the single
failure mode most likely to make this project produce confident nonsense.

## Decision

Reorganize `fixtures/` by role rather than format:

```
fixtures/
├── qre-samples/   15 QREs — development corpus (13 DOCX, 2 PDF)
└── holdout/        3 QREs — not read during development (2 DOCX, 1 PDF)
```

`fixtures/test-samples/` is removed; its name described a role it did not have.

Held out:

| File | Format | Tier |
|---|---|---|
| `C03_b2b_saas_decision_journey.docx` | DOCX | Complex |
| `M04_hotel_stay_experience.docx` | DOCX | Moderate |
| `QRE_2_Moderate_Cloud_Storage_Concept_Test.pdf` | PDF | Moderate |

**The holdout is not opened, read, or run against while building the reader.**
It is used only to measure extraction performance once ground truth exists for
it, and any change made in response to a holdout result must be a general
improvement, never an accommodation of a specific document.

## Rationale

**Why hold out at all, given no ground truth exists yet.** Ground truth is
coming (Sections 33 and 49) and is expensive to hand-code. The holdout has to
be designated *before* development starts, or it is not a holdout — it is a
sample we happened to look at last. The cost of deciding now is zero; the cost
of deciding later is the whole instrument.

**Why 3 of 18.** Roughly one sixth. Large enough to be informative across
format and complexity, small enough that the development corpus keeps 15
documents and all three complexity tiers.

**Why not hold out all 3 PDFs.** A PDF adapter cannot be built against zero
PDFs. Holding out one leaves the Simple and Complex PDFs for development, which
spans the range better than any other pair, while still leaving a PDF that can
detect PDF-specific overfitting.

**Why the Moderate tier for two of the three.** Complex documents exercise the
most features and are the most valuable to develop against; simple ones reveal
the least. Moderate is the cheapest tier to give up.

## Relationship to real Escalent QREs

Section 37 designates real or sanitized Escalent QREs as a separate validation
tier when they arrive. That remains the strongest test, because the synthetic
corpus was authored with a shared idea of what a QRE looks like, and a holdout
drawn from it inherits that shared idea. This holdout detects overfitting to
specific documents; it cannot detect overfitting to the synthetic style. Both
tiers are needed and neither substitutes for the other.

## Consequences

- Development corpus drops from 18 to 15 documents, and from 3 PDFs to 2.
- Some discipline is required: the holdout is enforced by folder placement, not
  by tooling. Anyone can open it. Do not.
- Ground truth must eventually be hand-coded for holdout documents too, or the
  holdout produces no measurement.
- If the holdout is ever used to debug a specific extraction failure, it is
  burned and must be replaced with a fresh selection, recorded as a new
  decision here.
- CLAUDE.md Section 41 and the README structure block were updated to match.
