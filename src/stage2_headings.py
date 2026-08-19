"""Stage 2 — heading identification. Locate the four target blocks.

Heading candidates are paragraphs carrying a Word heading style. Each target is
first matched by name; anything still unmatched is offered to the LLM, which
judges the *shape* of the unmatched headings' content (a table headed
ID / wording / type implies Questionnaire) and proposes a candidate.

LLM use: shape-matching only, and only for targets name-matching missed.
"""

from __future__ import annotations

import re

from llm import LLMUnavailable, complete
from models import (
    ContentBlock,
    FlagStatus,
    LLMHeadingCandidate,
    Paragraph,
    ReviewFlag,
    Stage1Document,
    Stage2Blocks,
    Table,
    TargetHeading,
)

#: What each target's content looks like, for the shape-matching prompt.
_TARGET_SHAPES = {
    TargetHeading.QUESTIONNAIRE: (
        "a table whose columns identify survey questions — an id or reference "
        "column, a question wording column, and usually a type and options column"
    ),
    TargetHeading.ROUTING_AND_TERMINATION: (
        "a table of routing rules — a rule id, a condition, an action such as "
        "show/skip/terminate, and a destination"
    ),
    TargetHeading.ACCEPTANCE_TEST_SCENARIOS: (
        "a table of test cases — a scenario id, a purpose, input values and an "
        "expected outcome, often with JSON in the input and outcome cells"
    ),
    TargetHeading.COMPLETION_MESSAGES: (
        "prose or a short table pairing a disposition code such as COMPLETE or "
        "TERM_INELIGIBLE with the message text shown to the respondent"
    ),
}

_SYSTEM = """\
You identify sections of a market-research questionnaire requirement document by \
the SHAPE of their content, not by their title.

You are given one section: its heading text, and a description of what it \
contains. Decide whether that content is the target section described to you.

Judge the structure only. A table's column names and the kind of values beneath \
them are the evidence. Ignore whether the heading sounds right.

Return is_match false whenever the content does not have the target's structure. \
A false positive routes the wrong content into an automated survey build; a false \
negative merely asks a human to look. Prefer the false negative.
"""


def _describe(blocks: list[Paragraph | Table]) -> str:
    """Summarise a block's content for the shape prompt. Structure, not prose."""
    parts: list[str] = []
    for block in blocks[:12]:
        if isinstance(block, Table):
            header = " | ".join(block.header)
            sample = " | ".join(block.rows[1][:6]) if len(block.rows) > 1 else ""
            parts.append(
                f"TABLE {len(block.rows)}x{len(block.header)} "
                f"columns: [{header}]"
                + (f" first row: [{sample}]" if sample else "")
            )
        elif block.text.strip():
            parts.append(f"PARAGRAPH: {block.text[:120]}")
    return "\n".join(parts) if parts else "(empty)"


def _normalise(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _heading_positions(document: Stage1Document) -> list[int]:
    return [
        index
        for index, block in enumerate(document.blocks)
        if isinstance(block, Paragraph)
        and block.heading_level is not None
        and block.text.strip()
    ]


def _content_after(
    document: Stage1Document, index: int, level: int, heading_indexes: list[int]
) -> list[Paragraph | Table]:
    """Everything below a heading until the next heading of equal or higher level."""
    end = len(document.blocks)
    for other in heading_indexes:
        if other <= index:
            continue
        block = document.blocks[other]
        if isinstance(block, Paragraph) and (block.heading_level or 99) <= level:
            end = other
            break
    return document.blocks[index + 1 : end]


def run(document: Stage1Document) -> Stage2Blocks:
    heading_indexes = _heading_positions(document)
    matched: dict[TargetHeading, ContentBlock] = {}
    flags: list[ReviewFlag] = []

    # --- direct name match ---------------------------------------------------
    targets_by_name = {_normalise(t.value): t for t in TargetHeading}
    used_indexes: set[int] = set()

    for index in heading_indexes:
        heading = document.blocks[index]
        target = targets_by_name.get(_normalise(heading.text))
        if target is None or target in matched:
            continue
        level = heading.heading_level or 1
        matched[target] = ContentBlock(
            target=target,
            heading_text=heading.text,
            heading_order=heading.order,
            heading_level=level,
            matched_by="direct",
            blocks=_content_after(document, index, level, heading_indexes),
        )
        used_indexes.add(index)

    # --- LLM shape-match for whatever is left --------------------------------
    unmatched_targets = [t for t in TargetHeading if t not in matched]
    spare_indexes = [i for i in heading_indexes if i not in used_indexes]

    for target in unmatched_targets:
        best: tuple[float, int, LLMHeadingCandidate] | None = None

        for index in spare_indexes:
            heading = document.blocks[index]
            level = heading.heading_level or 1
            content = _content_after(document, index, level, heading_indexes)
            try:
                verdict = complete(
                    _SYSTEM,
                    f"Target section: {target.value}\n"
                    f"Target content looks like: {_TARGET_SHAPES[target]}\n\n"
                    f"Candidate heading: {heading.text}\n"
                    f"Candidate content:\n{_describe(content)}\n\n"
                    "Is this the target section?",
                    LLMHeadingCandidate,
                )
            except LLMUnavailable as exc:
                flags.append(
                    ReviewFlag(
                        target_heading=target,
                        status=FlagStatus.NOT_PRESENT,
                        reasoning=f"No name match and shape-matching unavailable: {exc}",
                    )
                )
                best = None
                break
            if verdict.is_match and (best is None or verdict.confidence > best[0]):
                best = (verdict.confidence, index, verdict)

        if best is None:
            if not any(f.target_heading == target for f in flags):
                flags.append(
                    ReviewFlag(
                        target_heading=target,
                        status=FlagStatus.NOT_PRESENT,
                        reasoning=(
                            "No heading matched by name, and no unmatched heading's "
                            "content had this section's shape."
                        ),
                    )
                )
            continue

        confidence, index, verdict = best
        heading = document.blocks[index]
        level = heading.heading_level or 1
        matched[target] = ContentBlock(
            target=target,
            heading_text=heading.text,
            heading_order=heading.order,
            heading_level=level,
            matched_by="llm_shape",
            blocks=_content_after(document, index, level, heading_indexes),
        )
        spare_indexes.remove(index)
        flags.append(
            ReviewFlag(
                target_heading=target,
                status=FlagStatus.POSSIBLE_MATCH,
                candidate_heading=heading.text,
                confidence=confidence,
                reasoning=verdict.reasoning,
            )
        )

    return Stage2Blocks(
        source=document.source,
        blocks=[matched[t] for t in TargetHeading if t in matched],
        flags=flags,
    )
