# 0001 — Groq as the interim LLM runtime

**Date:** 2026-08-17
**Status:** Accepted (interim)
**Affects:** `src/common/llm/`, `src/common/prompts/`, Agent 1 Part 1 Steps 2, 5, 7

## Context

`CLAUDE.md` §52 names Azure OpenAI, accessed through
`src/common/llm/azure_client.py`, as the sponsor-approved application runtime for
processing confidential QRE content, and forbids silently substituting another
provider.

The Agent 1 specification's step table names Groq for the semantic calls in
Steps 2 (section classification), 5 (condition-to-expression conversion) and 7
(quota prose to structure). The project team holds a Groq API key and has
directed that Groq be used for development.

No Azure OpenAI endpoint or credentials are available to the project at this
time, so the alternative to Groq is no semantic capability at all.

## Decision

Wire Groq as the interim LLM runtime, and record the deviation rather than let
it pass silently (§56.6, §63).

The §52 *principle* — one shared, auditable, rate-limitable, swappable client
that all prompt modules route through — is preserved in full:

- `src/common/llm/groq_client.py` is the only module that touches a provider SDK.
- Prompt modules under `src/common/prompts/` call that client, never the SDK.
- Agent steps depend on a callable signature (`SectionClassifier`), not on Groq.
  `src/agents/.../section_detector.py` contains no provider reference.

Replacing this with `azure_client.py` therefore means adding one module and
changing one import in the prompt layer. No agent step changes.

## Confidentiality controls

Given §51/§52's concern about client material reaching non-approved services,
each call sends the minimum needed:

- **Step 2** sends only the section heading text and the allowed label
  vocabulary. Section bodies, question wording, response options and routing
  rules are never sent.
- The corpus in current use is synthetic (§2), not real client material.

Before any real or sanitized Escalent QRE is processed, this decision must be
revisited — either by obtaining the approved Azure endpoint, or by explicit
sponsor sign-off for Groq.

## Model selection

The account has no Llama 3.x chat models. Every chat-capable model it does have
was benchmarked against the Step 2 task via
`scripts/benchmark_section_classifier.py` (7 synonym cases that should resolve,
6 adjacent-section cases that should decline):

| Model | Synonyms | Declines | Total |
|---|---|---|---|
| **qwen/qwen3.6-27b** | **7/7** | **6/6** | **13/13** |
| openai/gpt-oss-120b | 6/7 | 6/6 | 12/13 |
| openai/gpt-oss-20b | 3/7 | 6/6 | 9/13 |
| groq/compound-mini | 4/7 | 6/6 | 10/13 |
| allam-2-7b | 5/7 | 0/6 | 5/13 |

`qwen/qwen3.6-27b` is the default. Two findings worth keeping:

1. **Prompt v1 over-reached on every model.** All three leading models mapped
   "Weighting And Analysis Plan" onto `study_specification` rather than declining
   — the silent-misroute failure §30 prohibits. Prompt v2 adds an explicit
   null-bias rule and worked examples of declining; over-reach went to 0/6 on all
   three without losing synonym recall on qwen.
2. **`allam-2-7b` returned a label outside the supplied vocabulary**
   (`analysis_and_weighting`). The §17 vocabulary re-check in
   `section_detector._classify` rejected it. That guard is load-bearing, not
   defensive decoration.

## Consequences

- Semantic classification is available now, unblocking Steps 2, 5 and 7.
- `LLM_PROVIDER=none` disables all model calls; the pipeline still runs and flags
  what it cannot resolve deterministically. Every step's deterministic path is
  therefore exercised regardless of provider.
- Reproducibility (§50) is served by temperature 0 and a versioned prompt string
  recorded per run. Note that a hosted model is not a frozen artifact: identical
  input may drift across provider-side model updates. Model ID is recorded so
  such drift is at least detectable.
- One added dependency: `groq`.

## Revisit when

1. Azure OpenAI credentials become available, **or**
2. real/sanitized Escalent QREs enter the corpus, **or**
3. a step needs to send more than minimal fragments to the model.
