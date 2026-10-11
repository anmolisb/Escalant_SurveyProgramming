"""A text display row ("You're almost done!") builds as LimeSurvey's type X.

Built from S01's canonical fixture with one display row added, the way the S,
M and C QREs write it: type "text display", no options, shown to everyone.

    python -m pytest tests/survey_builder/test_display.py
"""

from __future__ import annotations

from pathlib import Path

from src.agents.survey_builder.loader import _build_question, read_canonical
from src.common import readiness

FIXTURE = Path(__file__).parent / "canonical" / "S01"

DISPLAY = {
    "question_id": "DT1",
    "seq": 3,
    "kind": "text display",
    "wording": "You're almost done!",
    "options": [],
    "matrix_rows": [],
    # Part 2 writes False for a display row. True here proves the builder
    # does not make a row with nothing to answer compulsory either way.
    "validation": {"mandatory": True},
    "guard": None,
    "option_source": None,
    "extra": {},
}


def test_display_row_is_text_display_and_never_mandatory():
    question = _build_question(DISPLAY, 1, randomized=False)
    assert question.type == "X"
    assert question.mandatory == "N"
    assert not question.options and not question.subquestions


def test_display_row_is_ready_for_every_agent():
    spec = read_canonical(FIXTURE)
    spec["questions"].insert(2, dict(DISPLAY, validation={"mandatory": False}))
    assert readiness.check_spec(spec) == []
