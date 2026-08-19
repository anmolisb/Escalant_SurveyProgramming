"""Stage 3 — raw JSON. One literal transcription per matched block.

Tables are converted by python-docx output alone: the header row becomes the JSON
keys, each subsequent row becomes one object. No LLM touches a table.

Prose blocks — completion messages are written as prose in most QREs — go to the
LLM under a Pydantic schema.

Still literal. Keys are the source's own column names, values are cell text
verbatim. No renaming, no splitting, no interpretation.
"""

from __future__ import annotations

from llm import LLMUnavailable, complete
from models import (
    FlagStatus,
    LLMCompletionMessages,
    Paragraph,
    ReviewFlag,
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


def _table_to_rows(table: Table) -> list[dict[str, str]]:
    """Header row becomes keys; each subsequent row becomes one object."""
    if len(table.rows) < 2:
        return []
    header = [cell.strip() for cell in table.rows[0]]
    rows: list[dict[str, str]] = []
    for row in table.rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        rows.append(
            {
                header[index] if index < len(header) else f"column_{index}": value
                for index, value in enumerate(row)
            }
        )
    return rows


def _prose_text(blocks: list[Paragraph | Table]) -> str:
    return "\n".join(
        b.text.strip() for b in blocks if isinstance(b, Paragraph) and b.text.strip()
    )


def run(stage2: Stage2Blocks) -> tuple[list[Stage3Block], list[ReviewFlag]]:
    outputs: list[Stage3Block] = []
    flags: list[ReviewFlag] = []

    for block in stage2.blocks:
        tables = [b for b in block.blocks if isinstance(b, Table)]

        if tables:
            rows: list[dict[str, str]] = []
            for table in tables:
                rows.extend(_table_to_rows(table))
            outputs.append(
                Stage3Block(target=block.target, source_kind="table", rows=rows)
            )
            if not rows:
                flags.append(
                    ReviewFlag(
                        target_heading=block.target,
                        status=FlagStatus.POSSIBLE_MATCH,
                        candidate_heading=block.heading_text,
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
                    reasoning="Matched block has neither a table nor prose content.",
                )
            )
            outputs.append(
                Stage3Block(target=block.target, source_kind="prose", rows=[])
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
                    reasoning=f"Prose block could not be transcribed: {exc}",
                )
            )
        outputs.append(Stage3Block(target=block.target, source_kind="prose", rows=rows))

    for target in TargetHeading:
        if not any(o.target == target for o in outputs):
            flags.append(
                ReviewFlag(
                    target_heading=target,
                    status=FlagStatus.NOT_PRESENT,
                    reasoning="No block reached Stage 3 for this target.",
                )
            )

    return outputs, flags
