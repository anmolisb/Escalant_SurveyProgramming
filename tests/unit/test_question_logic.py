"""Regression check for Step 5 — building per-question logic.

Run directly: python3 tests/unit/test_question_logic.py
Run via pytest: python3 -m pytest tests/unit/test_question_logic.py -v
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

from agents.qre_interpretation.extraction.instruction_splitter import split_instructions
from agents.qre_interpretation.extraction.question import (
    OP_ALWAYS,
    OP_CONTAINS_ANY,
    OP_EQUALS,
    OP_IN,
    OP_NOT_EQUALS,
    PROV_DERIVED,
    PROV_EXTRACTED,
    PROV_INFERRED,
    PROV_UNKNOWN,
)
from agents.qre_interpretation.extraction.question_logic import (
    build_questions,
    convert_condition,
    parse_matrix,
    parse_validation_rule,
    split_option_list,
)
from agents.qre_interpretation.extraction.raw_question import RawQuestion
from agents.qre_interpretation.ingestion.normalized_document import SourceReference


def _raw(qid="Q1", wording="W", qtype="single", options="", display=""):
    """Build a RawQuestion the way Step 4 would, including the instruction split."""
    return RawQuestion(
        id=qid,
        wording=wording,
        type=qtype,
        options_raw=options,
        display_validation_raw=display,
        instructions=split_instructions(display),
        row_index=1,
        source_reference=SourceReference(document="t.docx", order_index=0),
    )


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def test_options_split_on_semicolon():
    options = split_option_list("Yes; No")
    assert [o.label for o in options] == ["Yes", "No"]
    assert all(o.code is None for o in options)


def test_numeric_codes_extracted_when_the_source_gives_them():
    options = split_option_list("1 - Very poor; 2 - Poor; 3 - Fair")
    assert [(o.code, o.label) for o in options] == [
        ("1", "Very poor"),
        ("2", "Poor"),
        ("3", "Fair"),
    ]


def test_equals_style_codes_extracted():
    options = split_option_list("1=Yes; 2=No")
    assert [(o.code, o.label) for o in options] == [("1", "Yes"), ("2", "No")]


def test_codes_are_never_invented():
    """CLAUDE.md §13: labels without codes keep code None."""
    options = split_option_list("Counter; Mobile pre-order; Vending kiosk")
    assert all(o.code is None for o in options)


def test_hyphenated_label_is_not_read_as_a_code():
    """'Mobile pre-order' must not yield code 'Mobile'."""
    options = split_option_list("Mobile pre-order; Self-service kiosk")
    assert [o.label for o in options] == ["Mobile pre-order", "Self-service kiosk"]
    assert all(o.code is None for o in options)


def test_long_prefix_before_dash_is_not_a_code():
    """'Very poor - never again' is a label, not code 'Very'."""
    options = split_option_list("Very poor - never again; Good")
    assert options[0].code is None
    assert options[0].label == "Very poor - never again"


def test_dash_placeholder_means_no_options():
    """Step 5 may interpret '—'; Step 4 correctly could not."""
    for marker in ("—", "-", "n/a", ""):
        assert split_option_list(marker) == ()


def test_comma_split_only_when_no_semicolon_present():
    """Labels contain commas, so comma-splitting a ';' list would shred them."""
    kept = split_option_list("Thank you, that is all; Goodbye")
    assert [o.label for o in kept] == ["Thank you, that is all", "Goodbye"]
    fallback = split_option_list("Red, Green, Blue")
    assert [o.label for o in fallback] == ["Red", "Green", "Blue"]


def test_option_keeps_its_raw_text():
    options = split_option_list("1 - Very poor")
    assert options[0].raw == "1 - Very poor"


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------


def test_matrix_rows_and_scale_parsed():
    spec = parse_matrix("Rows: Access; Communication\nScale: 1 - Poor; 2 - Good")
    assert [o.label for o in spec.rows] == ["Access", "Communication"]
    assert [(o.code, o.label) for o in spec.scale] == [("1", "Poor"), ("2", "Good")]


def test_matrix_accepts_columns_as_the_scale_keyword():
    spec = parse_matrix("Rows: A; B\nColumns: Low; High")
    assert [o.label for o in spec.scale] == ["Low", "High"]


def test_flat_option_list_is_not_a_matrix():
    assert parse_matrix("Yes; No") is None
    assert parse_matrix("") is None


def test_matrix_question_exposes_scale_as_its_options():
    question = build_questions(
        [_raw(qtype="matrix", options="Rows: A; B\nScale: 1 - Low; 2 - High")]
    ).questions[0]
    assert question.matrix is not None
    assert [o.label for o in question.matrix.rows] == ["A", "B"]
    assert [o.label for o in question.options] == ["Low", "High"]


def test_matrix_typed_question_without_structure_is_flagged():
    result = build_questions([_raw(qtype="matrix", options="Yes; No")])
    assert any(r.reason == "matrix_structure_not_found" for r in result.review_queue)
    assert [o.label for o in result.questions[0].options] == ["Yes", "No"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validation_json_is_decoded():
    rule = parse_validation_rule('Validate: {"min_length": 10, "max_length": 500}')
    assert rule.parameters == {"min_length": 10, "max_length": 500}
    assert rule.is_parsed


def test_validation_keys_are_not_renamed_or_defaulted():
    rule = parse_validation_rule('Validate: {"exclusive_option": "None of these"}')
    assert rule.parameters == {"exclusive_option": "None of these"}


def test_malformed_validation_is_reported_not_dropped():
    rule = parse_validation_rule('Validate: {"min_length": }')
    assert not rule.is_parsed
    assert rule.parse_error is not None
    assert rule.raw == 'Validate: {"min_length": }'


def test_validation_without_json_is_reported():
    rule = parse_validation_rule("Validate: something in prose")
    assert rule.parse_error == "no JSON object found"


def test_unparseable_validation_reaches_the_review_queue():
    result = build_questions([_raw(display='Validate: {"broken": }')])
    assert any(
        r.reason == "validation_payload_unparseable" for r in result.review_queue
    )


# ---------------------------------------------------------------------------
# Display conditions — deterministic forms
# ---------------------------------------------------------------------------


def test_always_show_is_unconditional():
    condition = convert_condition("Always show")
    assert condition.operator == OP_ALWAYS
    assert condition.provenance == PROV_EXTRACTED
    assert condition.is_unconditional


def test_equality_condition_parsed():
    condition = convert_condition("Show if: Q5 == 'Yes'")
    assert condition.operator == OP_EQUALS
    assert condition.question_id == "Q5"
    assert condition.values == ("Yes",)
    assert condition.provenance == PROV_DERIVED


def test_inequality_condition_parsed():
    condition = convert_condition("Show if: Q3 != 'None/currently not using'")
    assert condition.operator == OP_NOT_EQUALS
    assert condition.values == ("None/currently not using",)


def test_in_list_condition_parsed():
    condition = convert_condition("Show if: Q9 in ['Detractor','Passive']")
    assert condition.operator == OP_IN
    assert condition.question_id == "Q9"
    assert condition.values == ("Detractor", "Passive")


def test_prose_condition_unresolved_without_a_converter():
    condition = convert_condition("Show if: Q5 contains any touchpoint")
    assert condition.operator is None
    assert condition.provenance == PROV_UNKNOWN
    assert condition.question_id == "Q5"  # the reference is still recovered
    assert condition.raw == "Show if: Q5 contains any touchpoint"
    assert condition.note


def test_deterministic_forms_never_reach_the_converter():
    calls = []

    def converter(text, qid, options):
        calls.append(text)
        return None

    for text in ("Always show", "Show if: Q5 == 'Yes'", "Show if: Q9 in ['A']"):
        convert_condition(text, {"Q5": ["Yes", "No"]}, converter)
    assert calls == []


# ---------------------------------------------------------------------------
# Display conditions — converter path
# ---------------------------------------------------------------------------


def test_converter_resolves_prose_against_the_option_list():
    def converter(text, qid, options):
        assert qid == "Q5"
        assert options == ["Physician", "Hospital", "None of these"]
        return {
            "operator": OP_CONTAINS_ANY,
            "question_id": "Q5",
            "values": ["Physician", "Hospital"],
        }

    condition = convert_condition(
        "Show if: Q5 contains any touchpoint",
        {"Q5": ["Physician", "Hospital", "None of these"]},
        converter,
    )
    assert condition.operator == OP_CONTAINS_ANY
    assert condition.values == ("Physician", "Hospital")
    assert condition.provenance == PROV_INFERRED


def test_converter_cannot_invent_an_operator():
    """§17: a converter must not widen the operator vocabulary."""
    condition = convert_condition(
        "Show if: Q5 contains any touchpoint",
        {"Q5": ["A"]},
        lambda text, qid, options: {"operator": "made_up", "values": ["A"]},
    )
    assert condition.operator is None
    assert condition.provenance == PROV_UNKNOWN


def test_converter_declining_leaves_condition_unresolved():
    condition = convert_condition(
        "Show if: Q5 contains any touchpoint",
        {"Q5": ["A"]},
        lambda text, qid, options: None,
    )
    assert condition.operator is None


# ---------------------------------------------------------------------------
# build_questions integration
# ---------------------------------------------------------------------------


def test_step5_reuses_step4_split_rather_than_resplitting():
    """Step 5 reads the instructions Step 4 already classified."""
    raw = _raw(
        options="Yes; No",
        display="Show if: Q1 == 'Yes'\nValidate: {\"min_selections\": 1}\nRandomize",
    )
    question = build_questions([raw]).questions[0]
    assert question.display_condition.operator == OP_EQUALS
    assert question.validation_rules[0].parameters == {"min_selections": 1}
    assert question.randomize is True


def test_randomize_notes_kept_distinct_from_the_flag():
    raw = _raw(display="Randomize\nConcept descriptions are displayed in randomized order; store display order.")
    question = build_questions([raw]).questions[0]
    assert question.randomize is True
    assert len(question.randomize_notes) == 2


def test_piping_carried_through():
    raw = _raw(display="Show if: Q1 == 'Yes'\nShow only brands selected at Q1.")
    question = build_questions([raw]).questions[0]
    assert question.dynamic_option_source == "Show only brands selected at Q1."


def test_no_display_instruction_yields_no_condition():
    question = build_questions([_raw(display='Validate: {"max_length": 10}')]).questions[0]
    assert question.display_condition is None


def test_condition_referencing_a_missing_question_is_flagged():
    raw = _raw(qid="Q2", display="Show if: Q99 == 'Yes'")
    result = build_questions([raw])
    assert any(
        r.reason == "condition_references_unknown_question" for r in result.review_queue
    )


def test_condition_referencing_a_present_question_is_not_flagged():
    result = build_questions(
        [_raw(qid="Q1", options="Yes; No"), _raw(qid="Q2", display="Show if: Q1 == 'Yes'")]
    )
    assert not any(
        r.reason == "condition_references_unknown_question" for r in result.review_queue
    )


def test_unresolved_condition_is_flagged_and_listed():
    result = build_questions([_raw(display="Show if: Q1 contains any brand")])
    assert any(
        r.reason == "display_condition_unresolved" for r in result.review_queue
    )
    assert len(result.unresolved_conditions) == 1


def test_record_is_json_round_trippable():
    import json

    raw = _raw(
        options="1 - Low; 2 - High",
        display="Show if: Q1 == 'Yes'\nValidate: {\"min_length\": 3}",
    )
    payload = json.loads(json.dumps(build_questions([raw]).to_dict()))
    q = payload["questions"][0]
    assert q["options"] == [
        {"label": "Low", "code": "1", "raw": "1 - Low"},
        {"label": "High", "code": "2", "raw": "2 - High"},
    ]
    assert q["validation_rules"][0]["parameters"] == {"min_length": 3}
    assert q["display_condition"]["operator"] == OP_EQUALS


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("OK: all question_logic checks passed")
