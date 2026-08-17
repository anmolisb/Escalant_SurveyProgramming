#!/usr/bin/env python3
"""RUN THIS FILE to execute the Agent 1 Part 1 pipeline on a QRE document.

Usage:
    python3 run_pipeline.py                       # uses the S01 sample QRE
    python3 run_pipeline.py path/to/your.docx     # uses your own .docx

Currently runs:
    Step 1  Document ingestion       → NormalizedDocument
    Step 2  Section detection        → SectionedDocument
    Step 4  Question extraction      → QuestionExtraction

Step 3 (study specification & standing instructions) is not built yet; it reads
the study_specification section and does not feed Step 4, so Step 4 runs without
it.

Prints a summary of each step and writes both artifacts as JSON under
data/outputs/qre_interpretation/. Add later steps to STAGES as they are built.

This is a development runner, not part of the agent. All logic lives under
src/agents/qre_interpretation/ — this file only invokes it and displays results.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.qre_interpretation.extraction.question_parser import (  # noqa: E402
    parse_questions,
)
from agents.qre_interpretation.extraction.raw_question import (  # noqa: E402
    QuestionExtraction,
)
from agents.qre_interpretation.extraction.section_detector import (  # noqa: E402
    detect_sections,
)
from agents.qre_interpretation.extraction.sectioned_document import (  # noqa: E402
    SectionedDocument,
)
from agents.qre_interpretation.ingestion.docx_reader import (  # noqa: E402
    DocxReadError,
    read_docx,
)
from agents.qre_interpretation.ingestion.normalized_document import (  # noqa: E402
    NormalizedDocument,
)
from common.config import get_settings  # noqa: E402
from common.prompts.qre_interpretation import (  # noqa: E402
    SECTION_CLASSIFICATION_PROMPT_VERSION,
    classify_section_heading,
    classify_table_column,
)

DEFAULT_QRE = REPO_ROOT / "fixtures" / "qre-samples" / "S01_campus_cafeteria_experience.docx"
OUTPUT_DIR = REPO_ROOT / "data" / "outputs" / "qre_interpretation"


def _rule(title: str) -> None:
    print(f"\n{title}\n{'-' * max(len(title), 78)}")


def print_step1(doc: NormalizedDocument) -> None:
    """One line per extracted block, in document order."""
    _rule(
        f"STEP 1 · Document ingestion — {len(doc.blocks)} blocks "
        f"({len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables)"
    )
    print(f"{'#':>3}  {'TYPE':<6} {'STYLE':<14} {'BOLD':<5} CONTENT")
    for block in doc.blocks:
        if block.kind == "paragraph":
            if not block.text.strip():
                continue  # kept in the data; adds nothing to read
            print(
                f"{block.order_index:>3}  {'para':<6} {block.style_name:<14} "
                f"{str(block.is_bold):<5} {block.text[:50]}"
            )
        else:
            shape = f"{len(block.rows)}x{len(block.header_row)}"
            header = " | ".join(block.header_row)
            print(f"{block.order_index:>3}  {'TABLE':<6} {shape:<14} {'':<5} {header[:50]}")


def print_llm_status(settings) -> None:
    """Report which runtime the semantic steps will use, and why.

    Printed every run so an output is never ambiguous about whether a model was
    involved (CLAUDE.md §55).
    """
    if settings.llm_enabled:
        print(
            f"\nLLM: {settings.llm_provider} · model={settings.groq.model} · "
            f"prompt={SECTION_CLASSIFICATION_PROMPT_VERSION}"
        )
        print("     Only heading and column-header text is sent — never cell content.")
    else:
        reason = (
            "no API key set"
            if settings.llm_provider != "none"
            else "LLM_PROVIDER=none"
        )
        print(f"\nLLM: disabled ({reason}) — deterministic matching only.")


def print_step2(sectioned: SectionedDocument) -> None:
    """One line per detected section, plus anything flagged for review."""
    _rule(f"STEP 2 · Section detection — {len(sectioned.sections)} sections")
    print(f"{'LABEL':<34} {'PROVENANCE':<11} {'BLOCKS':<8} HEADING")
    for section in sectioned.sections:
        label = section.label or "(unclassified)"
        blocks = f"{section.paragraph_count}p/{section.table_count}t"
        print(
            f"{label:<34} {section.label_provenance:<11} {blocks:<8} "
            f"{section.heading_text[:30]}"
        )
    print_review_queue("STEP 2", sectioned.review_queue)


def print_step4(extraction: QuestionExtraction) -> None:
    """One line per extracted question, plus the column mapping it used."""
    _rule(f"STEP 4 · Question extraction — {len(extraction.questions)} questions")

    if extraction.column_mapping:
        print("Column mapping (table header -> field):")
        for role, header in extraction.column_mapping.items():
            print(f"  {header!r:<28} -> {role}")
        if extraction.unmapped_headers:
            print(f"  unmapped (kept in extra_columns): {extraction.unmapped_headers}")
        print()

    if extraction.questions:
        print(f"{'ID':<6} {'TYPE':<8} {'WORDING':<44} OPTIONS_RAW")
        for question in extraction.questions:
            print(
                f"{question.id:<6} {question.type:<8} {question.wording[:42]:<44} "
                f"{question.options_raw[:30]}"
            )
    print_review_queue("STEP 4", extraction.review_queue)


def print_review_queue(step: str, items) -> None:
    """Print a step's review queue, or state plainly that it is empty.

    Shared by every step: silence would be ambiguous about whether a step has no
    findings or simply does not report them (CLAUDE.md §55).
    """
    if not items:
        print(f"\n{step} review queue: empty.")
        return
    _rule(f"{step} REVIEW QUEUE — {len(items)} item(s)")
    for item in items:
        print(f"  [{item.reason}] {item.element}")
        print(f"      {item.detail}")


def write_json(obj, document_name: str, suffix: str) -> Path:
    """Serialize a dataclass artifact to JSON and return the output path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{Path(document_name).stem}.{suffix}.json"
    out_path.write_text(json.dumps(dataclasses.asdict(obj), indent=2))
    return out_path


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_QRE

    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        print("\nUsage: python3 run_pipeline.py [path/to/qre.docx]", file=sys.stderr)
        return 1

    try:
        document = read_docx(path)
    except DocxReadError as exc:
        # Step 1 fails loudly rather than emitting partial extraction.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print_step1(document)

    # Wire the LLM classifier only when a provider is configured. Without it the
    # pipeline still runs, flagging headings it cannot resolve deterministically.
    settings = get_settings()
    enabled = settings.llm_enabled
    print_llm_status(settings)

    sectioned = detect_sections(
        document, classifier=classify_section_heading if enabled else None
    )
    print_step2(sectioned)

    # Step 3 is not built; Step 4 reads the questionnaire section directly.
    extraction = parse_questions(
        sectioned, classifier=classify_table_column if enabled else None
    )
    print_step4(extraction)

    written = [
        write_json(document, document.document_name, "step1"),
        write_json(sectioned, document.document_name, "step2"),
        write_json(extraction, document.document_name, "step4"),
    ]
    _rule("OUTPUT")
    for out_path in written:
        print(f"  {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
