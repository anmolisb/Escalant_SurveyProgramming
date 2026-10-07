"""Stage 2 — heading identification. Locate the target blocks.

Heading candidates are paragraphs carrying a Word heading style. Each target is
first matched by name. Sections no name claimed are then read table by table:
a table whose own header row has a target's signature (ID / wording / type
implies Questionnaire) is claimed for that target on its own, whatever heading
it sits under. Targets still unmatched are offered to the LLM, which judges the
*shape* of the remaining headings' content and proposes candidates.

A target may be found in several places — a modular QRE keeps one question
table per module — so every match is kept, not only the first.

LLM use: shape-matching only, and only for targets the first two passes missed.
"""

from __future__ import annotations

import re

from src.common.llm.groq_client import LLMUnavailable, complete
from .models import (
    ContentBlock,
    FlagSeverity,
    FlagStatus,
    FlagTarget,
    LLMHeadingCandidate,
    Paragraph,
    ReviewFlag,
    Stage1Document,
    Stage2Blocks,
    Table,
    TargetHeading,
    UnclassifiedSection,
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
    TargetHeading.QUOTA_CONTROLS: (
        "prose or a table describing sampling quotas — named quota groups, the "
        "question or demographic each is measured on, target shares or counts "
        "per cell, and what happens to a respondent whose cell is already full"
    ),
    TargetHeading.STUDY_SPECIFICATION: (
        "prose stating study-level facts — the business objective, the target "
        "population, the interviewing mode, expected length, and instructions "
        "that apply to the questionnaire as a whole"
    ),
    TargetHeading.PROGRAMMING_AND_QA: (
        "prose listing instructions to whoever programs or tests the survey — "
        "what identifiers to store, what to log or capture, what to reject, and "
        "what evidence a test run must produce"
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


#: Words a table header uses for each role a column can play. Generic survey
#: vocabulary, not any one document's column names: a header using none of them
#: classifies as nothing and its table is preserved unclassified.
_ROLE_WORDS = {
    "id": ("id", "qid", "var", "ref", "no", "marker", "code", "rule", "quota", "path"),
    "wording": ("wording", "question", "text", "verbatim", "stem", "instruction"),
    "type": ("type", "format", "mode", "capture"),
    "condition": ("condition", "when", "if", "test", "trigger", "logic"),
    "action": ("action", "do", "effect", "then"),
    "destination": ("destination", "target", "goto", "go", "jump", "ending"),
    "purpose": ("purpose", "description", "scenario", "objective"),
    "inputs": ("inputs", "input", "given", "answers", "entered"),
    "expected": ("expected", "outcome", "result"),
    "message": ("message", "messages"),
    "quota": ("quota", "quotas", "tolerance", "cells", "cell"),
}

#: The roles a table's header must carry to be read as each target.
_TABLE_SIGNATURES = [
    (TargetHeading.QUESTIONNAIRE, frozenset({"id", "wording", "type"})),
    (TargetHeading.ROUTING_AND_TERMINATION, frozenset({"id", "condition", "action"})),
    (TargetHeading.ACCEPTANCE_TEST_SCENARIOS, frozenset({"id", "purpose", "expected"})),
    (TargetHeading.COMPLETION_MESSAGES, frozenset({"id", "message"})),
    (TargetHeading.QUOTA_CONTROLS, frozenset({"id", "quota"})),
]


#: Targets a QRE writes as a table, as sentences, or as both under one heading.
_PROSE_TARGETS = {TargetHeading.QUOTA_CONTROLS}


def _words(text: str) -> list[str]:
    """Whole words only. Substring matching is how "no" once matched
    "Scripter notes" and made a column of scripting notes the question id."""
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _roles_in(header: list[str]) -> set[str]:
    words = {w for cell in header for w in _words(cell)}
    return {role for role, names in _ROLE_WORDS.items() if words & set(names)}


def _classify_table(header: list[str]) -> TargetHeading | None:
    """None where nothing fits, and None again where more than one signature
    fits — an ambiguous table is a thing to report, not a thing to guess at."""
    if not header:
        return None
    roles = _roles_in(header)
    hits = [t for t, required in _TABLE_SIGNATURES if required <= roles]
    if hits == [TargetHeading.COMPLETION_MESSAGES] and "condition" in roles:
        # Messages that each fire on a trigger are a catalogue of validation
        # and system messages, not the survey's endings. Read as endings they
        # become places a respondent can finish that nothing ever routes to.
        return None
    return hits[0] if len(hits) == 1 else None


#: "3. ", "2.1 ", "4) " — outline numbering in front of a heading's name.
_OUTLINE_NUMBER = re.compile(r"^\s*\d+(\.\d+)*[.)]?\s+")


def _normalise(text: str) -> str:
    text = _OUTLINE_NUMBER.sub("", text)
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
    matched: dict[TargetHeading, list[ContentBlock]] = {}
    flags: list[ReviewFlag] = []

    # --- direct name match ---------------------------------------------------
    targets_by_name = {_normalise(t.value): t for t in TargetHeading}
    used_indexes: set[int] = set()

    for index in heading_indexes:
        heading = document.blocks[index]
        target = targets_by_name.get(_normalise(heading.text))
        if target is None:
            continue
        level = heading.heading_level or 1
        matched.setdefault(target, []).append(
            ContentBlock(
                target=target,
                heading_text=heading.text,
                heading_order=heading.order,
                heading_level=level,
                matched_by="direct",
                blocks=_content_after(document, index, level, heading_indexes),
            )
        )
        used_indexes.add(index)

    # --- table signature, for sections no heading name claimed ---------------
    # Only the spare sections are read this way, so a document whose headings
    # are the familiar ones takes exactly the route it always did.
    spare_indexes = [i for i in heading_indexes if i not in used_indexes]
    leftovers: list[tuple[int, list[Paragraph | Table]]] = []
    # A sub-heading inside a section a name already claimed is still spare, and
    # its tables are already in that section's block. Claiming them again here
    # would transcribe every row twice.
    claimed_orders = {
        item.order for blocks in matched.values() for block in blocks for item in block.blocks
    }

    for index in list(spare_indexes):
        heading = document.blocks[index]
        level = heading.heading_level or 1
        content = _content_after(document, index, level, heading_indexes)

        unclaimed: list[Paragraph | Table] = []
        claimed_here = False
        for item in content:
            if item.order in claimed_orders:
                continue
            target = _classify_table(item.header) if isinstance(item, Table) else None
            if target is None:
                unclaimed.append(item)
                continue
            matched.setdefault(target, []).append(
                ContentBlock(
                    target=target,
                    heading_text=heading.text,
                    heading_order=heading.order,
                    heading_level=level,
                    matched_by="table_signature",
                    blocks=[item],  # this table only
                )
            )
            claimed_orders.add(item.order)
            claimed_here = True

        if not claimed_here:
            continue
        spare_indexes.remove(index)
        prose = [item for item in unclaimed if isinstance(item, Paragraph)]
        if prose and len(prose) == len(unclaimed) and all(
            isinstance(item, Paragraph) or _classify_table(item.header) in _PROSE_TARGETS
            for item in content
        ):
            # The section holds nothing but this target's table and sentences
            # around it, and the target is one that is written either way. The
            # sentences are part of it: "evaluate the quota after eligibility"
            # is a quota requirement wherever the cell targets are tabled.
            target = _classify_table(next(i for i in content if isinstance(i, Table)).header)
            matched[target].append(
                ContentBlock(
                    target=target,
                    heading_text=heading.text,
                    heading_order=heading.order,
                    heading_level=level,
                    matched_by="table_signature",
                    blocks=prose,
                )
            )
            continue
        # A claimed table's ContentBlock holds only that table, so the paragraphs
        # around it would be accounted for nowhere. Keep everything unclaimed —
        # prose as well as tables.
        if unclaimed:
            leftovers.append((index, unclaimed))

    # --- LLM shape-match for whatever is left --------------------------------
    unmatched_targets = [t for t in TargetHeading if t not in matched]

    for target in unmatched_targets:
        claims: list[tuple[int, LLMHeadingCandidate]] = []

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
                        severity=FlagSeverity.BLOCKING,
                        target=FlagTarget(kind="section", id=target.value),
                        reasoning=f"No name match and shape-matching unavailable: {exc}",
                    )
                )
                claims = []
                break
            if verdict.is_match:
                claims.append((index, verdict))

        if not claims:
            if not any(f.target_heading == target for f in flags):
                flags.append(
                    ReviewFlag(
                        target_heading=target,
                        status=FlagStatus.NOT_PRESENT,
                        # A QRE need not contain every section; S01 has no
                        # quotas and that is not an error.
                        severity=FlagSeverity.WARNING,
                        target=FlagTarget(kind="section", id=target.value),
                        reasoning=(
                            "No heading matched by name, and no unmatched heading's "
                            "content had this section's shape."
                        ),
                    )
                )
            continue

        # Every section the model calls a match, not only the most confident:
        # a target written in several places is several matches.
        for index, verdict in claims:
            heading = document.blocks[index]
            level = heading.heading_level or 1
            matched.setdefault(target, []).append(
                ContentBlock(
                    target=target,
                    heading_text=heading.text,
                    heading_order=heading.order,
                    heading_level=level,
                    matched_by="llm_shape",
                    blocks=_content_after(document, index, level, heading_indexes),
                )
            )
            spare_indexes.remove(index)
            flags.append(
                ReviewFlag(
                    target_heading=target,
                    status=FlagStatus.POSSIBLE_MATCH,
                    candidate_heading=heading.text,
                    confidence=verdict.confidence,
                    severity=FlagSeverity.WARNING,
                    target=FlagTarget(kind="section", id=target.value),
                    reasoning=verdict.reasoning,
                )
            )

    # --- keep whatever matched nothing ---------------------------------------
    # A heading no target claimed is not noise. C02's `Quota controls` and
    # `Programming and QA requirements` both land here, and both state real
    # survey behaviour. Dropping them is how they went missing unnoticed.
    unclassified = [
        UnclassifiedSection(
            heading_text=document.blocks[index].text,
            heading_order=document.blocks[index].order,
            heading_level=document.blocks[index].heading_level or 1,
            blocks=_content_after(
                document,
                index,
                document.blocks[index].heading_level or 1,
                heading_indexes,
            ),
        )
        for index in spare_indexes
    ]
    unclassified += [
        UnclassifiedSection(
            heading_text=document.blocks[index].text,
            heading_order=document.blocks[index].order,
            heading_level=document.blocks[index].heading_level or 1,
            blocks=items,
            reason="section matched a target, but these tables did not",
        )
        for index, items in leftovers
    ]
    unclassified.sort(key=lambda section: section.heading_order)

    return Stage2Blocks(
        source=document.source,
        blocks=[b for t in TargetHeading for b in matched.get(t, [])],
        flags=flags,
        unclassified=unclassified,
    )
