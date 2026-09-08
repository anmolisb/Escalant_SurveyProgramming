"""Regression tests for the survey builder.

The snapshot test is the safety net: it fails if anything changes the bytes of
the S01 output. When a change is intentional, regenerate the snapshot with

    python -m src.agents.survey_builder.tests.test_s01 --update

The structural tests below it pin the four things that were found by comparing
against a real LimeSurvey export and are easy to break by accident.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from src.agents.survey_builder.emitter import emit
from src.agents.survey_builder.loader import load

FIXTURES = Path("fixtures/stage4-outputs/S01")
SNAPSHOT = Path(__file__).parent / "S01_expected.lss"


def _build() -> str:
    return emit(load(FIXTURES))


def test_output_matches_snapshot():
    assert _build() == SNAPSHOT.read_text(), (
        "S01 output changed. If that was intended, rerun with --update."
    )


def test_subquestions_are_in_their_own_table():
    """Multiple-choice options belong in <subquestions>, not <questions>.

    Putting them in <questions> imports without error and silently leaves the
    parent question with no options.
    """
    xml = _build()
    questions = re.search(r"<questions>.*?</questions>", xml, re.DOTALL).group(0)
    subquestions = re.search(r"<subquestions>.*?</subquestions>", xml, re.DOTALL).group(0)

    assert "SQ001" not in questions
    assert re.findall(r"<title><!\[CDATA\[(SQ\d+)\]\]>", subquestions)


def test_answer_labels_join_on_aid():
    """answer_l10ns links to answers by aid. Without it labels import blank."""
    xml = _build()
    answers = re.search(r"<answers>.*?</answers>", xml, re.DOTALL).group(0)
    l10ns = re.search(r"<answer_l10ns>.*?</answer_l10ns>", xml, re.DOTALL).group(0)

    answer_aids = set(re.findall(r"<aid><!\[CDATA\[(\d+)\]\]>", answers))
    l10n_aids = set(re.findall(r"<aid><!\[CDATA\[(\d+)\]\]>", l10ns))

    assert answer_aids
    assert answer_aids == l10n_aids


def test_qids_cannot_collide_with_question_titles():
    """A qid matching a numeral in a question title corrupts relevance on import.

    LimeSurvey rewrites "Q5" in a relevance string as though the 5 were a qid.
    """
    xml = _build()
    qids = {int(q) for q in re.findall(r"<qid><!\[CDATA\[(\d+)\]\]>", xml)}
    title_numbers = {
        int(n)
        for n in re.findall(r"<title><!\[CDATA\[[A-Z]+(\d+)\]\]>", xml)
    }
    assert not (qids & title_numbers)


def test_localized_attributes_carry_a_language():
    """Attributes holding display text are dropped on import without one."""
    xml = _build()
    attributes = re.search(
        r"<question_attributes>.*?</question_attributes>", xml, re.DOTALL
    ).group(0)
    tip = re.search(
        r"<row>(?:(?!</row>).)*em_validation_q_tip(?:(?!</row>).)*</row>",
        attributes,
        re.DOTALL,
    )
    assert tip, "em_validation_q_tip not emitted"
    assert "<language><![CDATA[en]]></language>" in tip.group(0)


def test_screening_gates_the_main_group():
    survey = load(FIXTURES)
    main = next(g for g in survey.groups if g.name == "Main Survey")
    assert "S1.NAOK" in main.relevance
    assert "S2.NAOK" in main.relevance


if __name__ == "__main__":
    if "--update" in sys.argv:
        SNAPSHOT.write_text(_build())
        print(f"snapshot updated: {SNAPSHOT}")
    else:
        print("run with pytest, or pass --update to regenerate the snapshot")