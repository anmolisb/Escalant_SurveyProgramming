#!/usr/bin/env python3
"""Benchmark Step 2's LLM section classifier across available models.

    python3 scripts/benchmark_section_classifier.py            # all usable models
    python3 scripts/benchmark_section_classifier.py qwen/qwen3.6-27b

Why this exists. Model availability differs per Groq account, and the classifier
has two failure modes that pull in opposite directions:

  - **over-reach**: labelling an adjacent-but-different section, which silently
    misroutes content downstream (CLAUDE.md §30, §40);
  - **over-caution**: declining a genuine synonym, which sends real sections to
    the review queue for no reason.

A single accuracy number hides that trade-off, so this reports both arms
separately. Re-run it after any change to the classification prompt.

Makes live API calls and costs tokens. Requires GROQ_API_KEY in .env.

Note the cases below are hand-written development fixtures for choosing a model,
NOT the reviewed ground truth required by CLAUDE.md §33/§34 — that must be
produced independently of the system under test.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from common.config import GroqSettings, get_settings  # noqa: E402
from common.llm.groq_client import GroqClient, LLMUnavailableError  # noqa: E402
from common.prompts.qre_interpretation import (  # noqa: E402
    SECTION_CLASSIFICATION_PROMPT_VERSION,
    classify_section_heading,
)

ALLOWED = [
    "study_specification",
    "questionnaire",
    "routing_and_termination",
    "quota_controls",
    "programming_and_qa_requirements",
    "acceptance_test_scenarios",
    "completion_messages",
]

#: Headings absent from the deterministic alias list but genuinely synonymous
#: with an allowed label. A correct classifier resolves these.
SYNONYM_CASES: list[tuple[str, str]] = [
    ("Sample Balancing Rules", "quota_controls"),
    ("Interview Flow Control", "routing_and_termination"),
    ("Final Thank You Screens", "completion_messages"),
    ("Item Bank", "questionnaire"),
    ("Survey Build Notes", "programming_and_qa_requirements"),
    ("Study Aims And Sample", "study_specification"),
    ("UAT Cases", "acceptance_test_scenarios"),
]

#: Real QRE section types that are NOT in the allowed vocabulary. A correct
#: classifier declines all of these rather than picking the nearest label.
DECLINE_CASES: list[str] = [
    "Weighting And Analysis Plan",
    "Translation Requirements",
    "Fieldwork Timings",
    "Data Deliverables And Tabulation",
    "Incentive Structure",
    "Legal And Consent Wording",
]

#: Models worth trying for a short JSON classification. Chat-capable only —
#: audio, guard and embedding models are skipped.
CANDIDATE_MODELS = [
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "groq/compound-mini",
    "allam-2-7b",
]


def discover_models(api_key: str) -> list[str]:
    """Return candidate models the account can actually see."""
    from groq import Groq

    available = {m.id for m in Groq(api_key=api_key).models.list().data}
    return [m for m in CANDIDATE_MODELS if m in available]


def score_model(model: str, api_key: str) -> tuple[int, int, list[str]]:
    """Run both case sets against one model.

    Returns:
        (synonyms_correct, declines_correct, per-case report lines)
    """
    client = GroqClient(
        GroqSettings(api_key=api_key, model=model, timeout_seconds=40, max_retries=1)
    )
    lines: list[str] = []

    synonyms_ok = 0
    for heading, expected in SYNONYM_CASES:
        got = classify_section_heading(heading, ALLOWED, client=client)
        hit = got == expected
        synonyms_ok += hit
        flag = "ok  " if hit else "MISS"
        lines.append(f"  [{flag}] {heading:<34} -> {got}")

    declines_ok = 0
    for heading in DECLINE_CASES:
        got = classify_section_heading(heading, ALLOWED, client=client)
        hit = got is None
        declines_ok += hit
        flag = "ok  " if hit else "OVER"
        lines.append(f"  [{flag}] {heading:<34} -> {got}")

    return synonyms_ok, declines_ok, lines


def main(argv: list[str]) -> int:
    settings = get_settings()
    if not settings.groq.is_configured:
        print(
            "ERROR: GROQ_API_KEY is not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 1

    key = settings.groq.api_key
    models = argv[1:] or discover_models(key)
    if not models:
        print("ERROR: none of the candidate models are available on this account.", file=sys.stderr)
        return 1

    total = len(SYNONYM_CASES) + len(DECLINE_CASES)
    print(f"Prompt version: {SECTION_CLASSIFICATION_PROMPT_VERSION}")
    print(f"Cases: {len(SYNONYM_CASES)} synonyms + {len(DECLINE_CASES)} declines = {total}\n")

    results: list[tuple[str, int, int]] = []
    for model in models:
        try:
            synonyms_ok, declines_ok, lines = score_model(model, key)
        except LLMUnavailableError as exc:
            print(f"=== {model} — unavailable: {exc}\n")
            continue
        except Exception as exc:
            print(f"=== {model} — unusable: {type(exc).__name__}: {str(exc)[:100]}\n")
            continue

        results.append((model, synonyms_ok, declines_ok))
        print(
            f"=== {model} — synonyms {synonyms_ok}/{len(SYNONYM_CASES)}, "
            f"declines {declines_ok}/{len(DECLINE_CASES)}, "
            f"total {synonyms_ok + declines_ok}/{total}"
        )
        for line in lines:
            print(line)
        print()

    if results:
        results.sort(key=lambda r: r[1] + r[2], reverse=True)
        best, synonyms_ok, declines_ok = results[0]
        print(f"Best: {best} ({synonyms_ok + declines_ok}/{total})")
        print(f"Set it with:  GROQ_MODEL={best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
