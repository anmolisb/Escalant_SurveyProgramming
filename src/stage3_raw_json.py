"""Stage 3 — raw JSON. One literal transcription per matched block.

Tables are converted by python-docx output alone: the header row becomes the JSON
keys, each subsequent row becomes one object. No LLM touches a table.

Prose blocks — completion messages are written as prose in most QREs — go to the
LLM under a Pydantic schema.

Still literal. Keys are the source's own column names, values are cell text
verbatim. No renaming, no splitting, no interpretation.
"""

from __future__ import annotations

import re

from llm import LLMUnavailable, complete
from models import (
    FlagSeverity,
    FlagStatus,
    FlagTarget,
    LLMCompletionMessages,
    Paragraph,
    ReviewFlag,
    SourceReference,
    Stage2Blocks,
    Stage3Block,
    Table,
    TargetHeading,
)

_SYSTEM = """\
You transcribe a block of prose from a questionnaire requirement document into \
JSON objects.

Transcribe only. Copy the text exactly as written: do not reword, summarise, \
translate, expand abbreviations, or add fields the source does not contain.

Each distinct item in the source becomes one object with exactly two keys, \
"code" and "message". Put the identifier in "code" and the text in "message"; \
never use the identifier itself as a key. A line reading \
"COMPLETE: Thank you for taking part." becomes \
{"code": "COMPLETE", "message": "Thank you for taking part."}.

Return no objects at all rather than inventing one for text that is not an item \
of this kind.
"""


def _table_to_rows(
    table: Table, context: SourceReference
) -> tuple[list[dict[str, str]], list[SourceReference]]:
    """Header row becomes keys; each subsequent row becomes one object.

    Also returns one SourceReference per emitted row, index-aligned with them.
    `row_index` counts data rows in the source table, so it keeps pointing at the
    right place in the document even where a blank row was skipped.
    """
    if len(table.rows) < 2:
        return [], []
    header = [cell.strip() for cell in table.rows[0]]
    rows: list[dict[str, str]] = []
    sources: list[SourceReference] = []
    for offset, row in enumerate(table.rows[1:]):
        if not any(cell.strip() for cell in row):
            continue
        rows.append(
            {
                header[index] if index < len(header) else f"column_{index}": value
                for index, value in enumerate(row)
            }
        )
        sources.append(
            context.model_copy(
                update={
                    "block_order": table.order,
                    "row_index": offset,
                    "source_kind": "table",
                    "text": " | ".join(c.strip() for c in row if c.strip())[:300],
                }
            )
        )
    return rows, sources


def _locate_prose_row(
    row: dict[str, str], paragraphs: list[Paragraph], context: SourceReference
) -> SourceReference:
    """Point a transcribed prose row at the paragraph it came from.

    Prose rows do not map one to one onto paragraphs the way table rows do, so
    this looks for a paragraph containing every value the row holds. That is a
    lookup of text we already have, not an interpretation of it. Where no single
    paragraph contains the row, it falls back to the start of the prose block
    rather than guessing.
    """
    values = [v.strip() for v in row.values() if v and v.strip()]
    if values:
        for paragraph in paragraphs:
            if all(value in paragraph.text for value in values):
                return context.model_copy(
                    update={
                        "block_order": paragraph.order,
                        "source_kind": "prose",
                        "text": paragraph.text[:300],
                    }
                )
    return context.model_copy(
        update={
            "block_order": paragraphs[0].order if paragraphs else None,
            "source_kind": "prose",
        }
    )


#: Targets whose prose needs a model to pair an identifier with its text.
#: Everything else is transcribed line by line, which needs no model, costs no
#: rate-limit budget and gives the same answer every run.
_LLM_PROSE_TARGETS = {TargetHeading.COMPLETION_MESSAGES}

#: "QUOTA_REGION: hard quota on D1..." or "Mode: Self-completion web survey".
#: The prefix is bounded so a sentence containing a colon is not mistaken for a
#: labelled line.
_PREFIXED_LINE = re.compile(r"^\s*([A-Za-z][\w \-/]{0,40}?)\s*:\s*(.+?)\s*$")
#: A disposition or quota code standing alone, e.g. COMPLETE, QUOTA_REGION.
_CODE_LIKE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def _prose_rows_literal(
    paragraphs: list[Paragraph], context: SourceReference
) -> tuple[list[dict[str, str]], list[SourceReference]]:
    """Transcribe prose one paragraph to one row.

    Splits only a leading "Code:" or "Label:" prefix, because that much is
    punctuation rather than meaning. The rest of the line is kept whole: turning
    "hard quota on D1: North=20%, South=20%" into cells and percentages is
    interpretation, and belongs to Part 2 (CLAUDE.md §19).
    """
    rows: list[dict[str, str]] = []
    sources: list[SourceReference] = []
    for paragraph in paragraphs:
        line = paragraph.text.strip()
        if not line:
            continue
        row: dict[str, str] = {"raw_text": line}
        match = _PREFIXED_LINE.match(line)
        if match:
            prefix, rest = match.group(1).strip(), match.group(2).strip()
            if _CODE_LIKE.match(prefix):
                row["code"] = prefix
            else:
                row["label"] = prefix
            row["text"] = rest
        else:
            row["text"] = line
        rows.append(row)
        sources.append(
            context.model_copy(
                update={
                    "block_order": paragraph.order,
                    "source_kind": "prose",
                    "text": line[:300],
                }
            )
        )
    return rows, sources


def _prose_text(blocks: list[Paragraph | Table]) -> str:
    return "\n".join(
        b.text.strip() for b in blocks if isinstance(b, Paragraph) and b.text.strip()
    )


def run(stage2: Stage2Blocks) -> tuple[list[Stage3Block], list[ReviewFlag]]:
    outputs: list[Stage3Block] = []
    flags: list[ReviewFlag] = []

    for block in stage2.blocks:
        tables = [b for b in block.blocks if isinstance(b, Table)]

        # Everything a row inherits from the section it sits in. Each row then
        # adds its own position on top of this.
        context = SourceReference(
            document=stage2.source,
            section=block.target.value,
            heading_text=block.heading_text,
        )

        if tables:
            rows: list[dict[str, str]] = []
            row_sources: list[SourceReference] = []
            for table in tables:
                table_rows, table_sources = _table_to_rows(table, context)
                rows.extend(table_rows)
                row_sources.extend(table_sources)
            outputs.append(
                Stage3Block(
                    target=block.target,
                    source_kind="table",
                    rows=rows,
                    row_sources=row_sources,
                )
            )
            if not rows:
                flags.append(
                    ReviewFlag(
                        target_heading=block.target,
                        status=FlagStatus.POSSIBLE_MATCH,
                        candidate_heading=block.heading_text,
                        severity=FlagSeverity.BLOCKING,
                        target=FlagTarget(kind="section", id=block.target.value),
                        reasoning="Block contains a table but no data rows below its header.",
                    )
                )
            continue

        prose = _prose_text(block.blocks)
        if not prose:
            flags.append(
                ReviewFlag(
                    target_heading=block.target,
                    status=FlagStatus.NOT_PRESENT,
                    candidate_heading=block.heading_text,
                    severity=FlagSeverity.BLOCKING,
                    target=FlagTarget(kind="section", id=block.target.value),
                    reasoning="Matched block has neither a table nor prose content.",
                )
            )
            outputs.append(
                Stage3Block(
                    target=block.target, source_kind="prose", rows=[], row_sources=[]
                )
            )
            continue

        paragraphs = [
            b for b in block.blocks if isinstance(b, Paragraph) and b.text.strip()
        ]

        if block.target not in _LLM_PROSE_TARGETS:
            literal_rows, literal_sources = _prose_rows_literal(paragraphs, context)
            outputs.append(
                Stage3Block(
                    target=block.target,
                    source_kind="prose",
                    rows=literal_rows,
                    row_sources=literal_sources,
                )
            )
            continue

        try:
            transcribed = complete(
                _SYSTEM,
                f"Section: {block.target.value}\n\nSource text:\n{prose}",
                LLMCompletionMessages,
            )
            rows = transcribed.rows
        except LLMUnavailable as exc:
            rows = []
            flags.append(
                ReviewFlag(
                    target_heading=block.target,
                    status=FlagStatus.POSSIBLE_MATCH,
                    candidate_heading=block.heading_text,
                    # The section was found but its content never arrived.
                    severity=FlagSeverity.BLOCKING,
                    target=FlagTarget(kind="section", id=block.target.value),
                    reasoning=f"Prose block could not be transcribed: {exc}",
                )
            )
        outputs.append(
            Stage3Block(
                target=block.target,
                source_kind="prose",
                rows=rows,
                row_sources=[_locate_prose_row(r, paragraphs, context) for r in rows],
            )
        )

    for target in TargetHeading:
        if not any(o.target == target for o in outputs):
            flags.append(
                ReviewFlag(
                    target_heading=target,
                    status=FlagStatus.NOT_PRESENT,
                    severity=FlagSeverity.WARNING,
                    target=FlagTarget(kind="section", id=target.value),
                    reasoning="No block reached Stage 3 for this target.",
                )
            )

    return outputs, flags
