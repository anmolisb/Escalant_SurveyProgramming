# 0001 — Use pdfplumber for PDF ingestion

**Date:** 2026-08-17
**Status:** Accepted
**Affects:** Agent 1 Part 1, document ingestion (CLAUDE.md Sections 8, 11)

## Context

Part 1 must ingest both DOCX and PDF QREs. CLAUDE.md Section 11 requires the
normalized document representation to preserve page number, paragraph order,
table structure, headings, section boundaries and source position, because
every extracted element carries provenance back to its location in the source.
Section 8 additionally requires that scanned or image-only PDFs be detected
explicitly rather than silently producing empty extraction.

The realistic candidates were pdfplumber, PyMuPDF and pypdf.

## Decision

Use **pdfplumber** (0.11.10), built on pdfminer.six.

## Rationale

**Provenance.** pdfplumber exposes per-character position and page-level table
objects. Provenance is not an optional extra in this project — a rule without a
traceable source cannot be reviewed, and Section 15 requires that we can always
answer where in the QRE a piece of information came from. A library that
returns a flat text blob makes that answer approximate at best.

**Tables.** The synthetic corpus carries a meaningful share of its content in
tables — the sample DOCX files have three tables each, and page 1 of a sample
PDF has two. Losing table structure means losing response options and codes,
which is failure mode 7 in Section 39.

**Image-only detection.** A pdfplumber page exposes its characters directly, so
"this page yielded no characters" is a one-line observable check rather than an
inference from empty output. That is exactly what Section 8 asks for.

**Licensing.** pdfplumber and pdfminer.six are MIT. PyMuPDF is AGPL, which is a
poor fit for a project that ends in a handover to a client, and licensing is
awkward to revisit late.

## Alternatives rejected

**PyMuPDF** is faster and has good text extraction, but the AGPL licence is the
blocking concern for handover. Speed is not a constraint at this corpus size.

**pypdf** is pure Python and MIT, but its table handling is weak and it does not
expose character-level geometry, which undercuts provenance.

## Consequences

- pdfplumber is slower than PyMuPDF. Irrelevant at 18 documents; worth
  revisiting only if batch runtime becomes a real constraint.
- If a scanned QRE appears, pdfplumber will not OCR it. That is intended
  behaviour under Section 8 — detect and surface, do not guess. Adding OCR
  would be a new decision, not an extension of this one.
- The rationale is duplicated as a comment in `requirements.txt`, since that is
  where someone changing the pin will actually be looking.
