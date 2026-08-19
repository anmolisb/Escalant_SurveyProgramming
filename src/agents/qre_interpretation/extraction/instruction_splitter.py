"""Splits a compound display/validation cell into separate labelled instructions.

A QRE routinely packs several unrelated instructions into one table cell,
separated by newlines:

    Show if: Q5 == 'Yes'
    Validate: {"min_length": 10, "max_length": 500}

Agent 2 (the survey builder) needs these as distinct fields — a display
condition and a validation rule are different things that map to different
LimeSurvey constructs. Handing it one string forces it to re-parse, which is
where silent misreads start.

This is the "splits multi-part display cells" half of Step 5. It is deliberately
*only* the split: each instruction keeps its source text verbatim. Converting
"Show if: Q5 == 'Yes'" into a typed predicate, or running json.loads on the
validation payload, is the other half of Step 5 and Part 2's normalization —
not done here (CLAUDE.md §19).

The kind vocabulary below was derived by tallying every instruction line in the
15-QRE corpus (364 lines, 9 distinct shapes), not from one sample. It is
category-3 material under §61 — observed patterns, not confirmed Escalent
convention — so it stays overridable and an unrecognized line is flagged rather
than forced into the nearest bucket.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Instruction kinds
# ---------------------------------------------------------------------------
# Names match the Step 5 output contract in the agent specification:
# {..., validation_rules[], display_condition, randomize, dynamic_option_source}

#: When the question is shown. This is routing/base logic.
KIND_DISPLAY = "display_condition"
#: A constraint on the answer.
KIND_VALIDATION = "validation"
#: Order randomization of options or concepts.
KIND_RANDOMIZATION = "randomization"
#: Mandatory/optional flag.
KIND_OPTIONALITY = "optionality"
#: Options carried over from an earlier question (piping).
KIND_DYNAMIC_OPTIONS = "dynamic_option_source"
#: Recognized as an instruction, but not as any known kind.
KIND_OTHER = "other"

#: Ordered (kind, pattern) pairs. First match wins, so the order matters:
#: "Show only options selected at Q7" must be tested against the piping pattern
#: before anything that matches a bare leading "show".
DEFAULT_INSTRUCTION_PATTERNS: tuple[tuple[str, str], ...] = (
    # Piping first — "Show only ..." would otherwise look display-shaped.
    (KIND_DYNAMIC_OPTIONS, r"^show\s+only\b"),
    (KIND_DYNAMIC_OPTIONS, r"\bcarry\s+(forward|over)\b"),
    (KIND_DYNAMIC_OPTIONS, r"\bpipe(d|s)?\s+from\b"),
    # Display / routing.
    (KIND_DISPLAY, r"^(show|ask|hide|display)\s+if\b"),
    (KIND_DISPLAY, r"^always\s+show\b"),
    (KIND_DISPLAY, r"^ask\s+all\b"),
    (KIND_DISPLAY, r"^base\s*:"),
    # Validation.
    (KIND_VALIDATION, r"^validate\b"),
    (KIND_VALIDATION, r"^validation\s*:"),
    # Randomization.
    (KIND_RANDOMIZATION, r"^randomi[sz]e"),
    (KIND_RANDOMIZATION, r"randomi[sz]ed\s+order"),
    (KIND_RANDOMIZATION, r"^rotate\b"),
    # Optionality.
    (KIND_OPTIONALITY, r"^optional\b"),
    (KIND_OPTIONALITY, r"^mandatory\b"),
    (KIND_OPTIONALITY, r"^not\s+required\b"),
)

#: Separators that divide one cell into several instructions. Newline is what
#: DOCX cells use; "||" is the project's ground-truth CSV encoding of the same
#: thing, so both are accepted and a cell round-tripped through either splits
#: identically.
INSTRUCTION_SEPARATOR = re.compile(r"\n|\|\|")

#: Kinds that state *when a question is asked*, and so must appear before any
#: constraint on the answer. Verified against the corpus: display never follows
#: validation in 364 lines.
_ROUTING_KINDS = (KIND_DISPLAY,)


@dataclass(frozen=True)
class Instruction:
    """One instruction line pulled out of a compound cell.

    Attributes:
        kind:       one of the KIND_* constants above.
        text:       the line exactly as written, stripped of surrounding
                    whitespace only. Never reworded, reordered or parsed.
        line_index: 0-based position within the source cell, so the original
                    document order is recoverable after grouping by kind.
    """

    kind: str
    text: str
    line_index: int


def classify_instruction(
    line: str, patterns: Sequence[tuple[str, str]] | None = None
) -> str:
    """Return the kind of a single instruction line.

    Classified on the line's own wording, never on its position in the cell.
    Position is not a reliable signal: in the corpus a validation line appears
    first in 29 cells and second in 21, and randomization appears at three
    different positions. Using position would mislabel whichever case is rarer.

    Returns:
        A KIND_* constant. KIND_OTHER when nothing matches — the caller flags it
        rather than guessing (CLAUDE.md §30).
    """
    active = DEFAULT_INSTRUCTION_PATTERNS if patterns is None else patterns
    stripped = line.strip()
    for kind, pattern in active:
        if re.search(pattern, stripped, re.IGNORECASE):
            return kind
    return KIND_OTHER


def split_instructions(
    cell: str, patterns: Sequence[tuple[str, str]] | None = None
) -> tuple[Instruction, ...]:
    """Split one display/validation cell into classified instructions.

    Args:
        cell:     the raw cell text, possibly holding several instructions.
        patterns: optional override of the (kind, regex) vocabulary.

    Returns:
        One Instruction per non-empty line, in source order. Empty tuple for an
        empty cell.
    """
    if not cell or not cell.strip():
        return ()

    instructions: list[Instruction] = []
    for index, part in enumerate(INSTRUCTION_SEPARATOR.split(cell)):
        text = part.strip()
        if not text:
            continue
        instructions.append(
            Instruction(
                kind=classify_instruction(text, patterns),
                text=text,
                line_index=index,
            )
        )
    return tuple(instructions)


def routing_precedes_validation(instructions: Sequence[Instruction]) -> bool:
    """True if no routing instruction appears after a validation instruction.

    A display condition says whether the question is asked at all; a validation
    rule constrains the answer once it is. The first therefore governs the
    second, and every cell in the corpus is written in that order.

    A cell that inverts it is not automatically wrong, but it is unusual enough
    to be worth a reviewer's eye — a validation written above the condition that
    gates it often means the two were meant for different questions, or that a
    row has been merged by mistake.
    """
    seen_validation = False
    for instruction in instructions:
        if instruction.kind == KIND_VALIDATION:
            seen_validation = True
        elif instruction.kind in _ROUTING_KINDS and seen_validation:
            return False
    return True
