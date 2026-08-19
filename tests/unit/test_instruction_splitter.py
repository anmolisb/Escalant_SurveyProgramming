"""Checks for splitting compound display/validation cells into separate fields.

Run directly: python3 tests/unit/test_instruction_splitter.py
Run via pytest: python3 -m pytest tests/unit/test_instruction_splitter.py -v
"""

from __future__ import annotations

import os

# Keep this file hermetic when run directly (pytest gets the same via
# tests/conftest.py). The pipeline steps default to the configured LLM, so
# without this a standalone run would make real API calls.
os.environ["LLM_PROVIDER"] = "none"
os.environ["GROQ_API_KEY"] = ""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agents.qre_interpretation.extraction.instruction_splitter import (
    KIND_DISPLAY,
    KIND_DYNAMIC_OPTIONS,
    KIND_OPTIONALITY,
    KIND_OTHER,
    KIND_RANDOMIZATION,
    KIND_VALIDATION,
    classify_instruction,
    routing_precedes_validation,
    split_instructions,
)


# ---------------------------------------------------------------------------
# Classification — by wording, never by position
# ---------------------------------------------------------------------------


def test_classifies_every_shape_seen_in_the_corpus():
    cases = {
        "Always show": KIND_DISPLAY,
        "Show if: Q5 == 'Yes'": KIND_DISPLAY,
        "Show if: Q1 contains at least one brand": KIND_DISPLAY,
        'Validate: {"min_length": 10, "max_length": 500}': KIND_VALIDATION,
        "Randomize": KIND_RANDOMIZATION,
        "Concept descriptions are displayed in randomized order; store display order.":
            KIND_RANDOMIZATION,
        "Optional": KIND_OPTIONALITY,
        "Show only touchpoints selected at Q5.": KIND_DYNAMIC_OPTIONS,
        "Show only brands selected at Q1.": KIND_DYNAMIC_OPTIONS,
    }
    for line, expected in cases.items():
        assert classify_instruction(line) == expected, line


def test_piping_wins_over_display_for_show_only():
    """'Show only ...' is piping, not a display condition, despite leading 'Show'."""
    assert classify_instruction("Show only options selected at Q7.") == (
        KIND_DYNAMIC_OPTIONS
    )
    assert classify_instruction("Show if: Q7 == 'Yes'") == KIND_DISPLAY


def test_unknown_line_is_flagged_not_forced():
    assert classify_instruction("Interviewer: pause for effect") == KIND_OTHER
    assert classify_instruction("See appendix B") == KIND_OTHER


def test_classification_is_case_insensitive():
    for line in ("SHOW IF: Q1 == 'Yes'", "show if: Q1 == 'Yes'", "Show If: Q1 == 'Yes'"):
        assert classify_instruction(line) == KIND_DISPLAY


def test_position_does_not_drive_classification():
    """Validation appears first in some cells and second in others."""
    first = split_instructions('Validate: {"x": 1}\nRandomize')
    second = split_instructions("Show if: Q1 == 'Yes'\nValidate: {\"x\": 1}")
    assert first[0].kind == KIND_VALIDATION
    assert second[1].kind == KIND_VALIDATION


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def test_splits_on_newline_preserving_order_and_text():
    cell = "Show if: Q5 == 'Yes'\nValidate: {\"min_length\": 10}"
    parts = split_instructions(cell)
    assert [p.text for p in parts] == [
        "Show if: Q5 == 'Yes'",
        'Validate: {"min_length": 10}',
    ]
    assert [p.kind for p in parts] == [KIND_DISPLAY, KIND_VALIDATION]
    assert [p.line_index for p in parts] == [0, 1]


def test_splits_on_double_pipe_too():
    """The project's ground-truth CSV encodes instruction breaks as '||'."""
    parts = split_instructions("Show if: Q5 == 'Yes'||Validate: {\"min_length\": 10}")
    assert [p.kind for p in parts] == [KIND_DISPLAY, KIND_VALIDATION]


def test_single_instruction_cell_yields_one():
    parts = split_instructions("Always show")
    assert len(parts) == 1 and parts[0].kind == KIND_DISPLAY


def test_empty_cell_yields_nothing():
    assert split_instructions("") == ()
    assert split_instructions("   \n  ") == ()


def test_blank_lines_between_instructions_are_dropped_not_counted():
    parts = split_instructions("Show if: Q1 == 'Yes'\n\n\nRandomize")
    assert len(parts) == 2
    assert [p.kind for p in parts] == [KIND_DISPLAY, KIND_RANDOMIZATION]


def test_split_is_lossless():
    """Every non-empty source line survives, verbatim and in order."""
    cell = (
        "Show if: Q3 != 'None'\n"
        'Validate: {"scale": ["1 - Very poor"], "require_each_row": true}\n'
        "Randomize"
    )
    parts = split_instructions(cell)
    source = [line.strip() for line in cell.split("\n") if line.strip()]
    assert [p.text for p in parts] == source


def test_custom_patterns_override_default():
    parts = split_instructions(
        "Nur zeigen wenn: Q1 == 'Ja'",
        patterns=((KIND_DISPLAY, r"^nur\s+zeigen\s+wenn"),),
    )
    assert parts[0].kind == KIND_DISPLAY


# ---------------------------------------------------------------------------
# Routing-before-validation ordering
# ---------------------------------------------------------------------------


def test_routing_before_validation_is_the_normal_order():
    parts = split_instructions("Show if: Q5 == 'Yes'\nValidate: {\"min_length\": 10}")
    assert routing_precedes_validation(parts) is True


def test_validation_before_routing_is_detected():
    parts = split_instructions('Validate: {"min_length": 10}\nShow if: Q5 == \'Yes\'')
    assert routing_precedes_validation(parts) is False


def test_ordering_check_ignores_non_routing_kinds():
    """Randomize or Optional after a validation is normal, not an inversion."""
    for cell in (
        'Validate: {"x": 1}\nRandomize',
        'Validate: {"max_length": 1000}\nOptional',
    ):
        assert routing_precedes_validation(split_instructions(cell)) is True


def test_ordering_holds_for_cells_without_validation():
    parts = split_instructions("Show if: Q1 == 'Yes'\nShow only brands selected at Q1.")
    assert routing_precedes_validation(parts) is True


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("OK: all instruction_splitter checks passed")
