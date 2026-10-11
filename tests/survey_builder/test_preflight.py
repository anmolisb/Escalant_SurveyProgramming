"""The preflight check finds what the builder cannot do before a build starts.

Built from S01's canonical fixture. The clean specification has no gaps, and
each deliberate change produces the gap it should.

    python -m pytest tests/survey_builder/test_preflight.py
"""

from __future__ import annotations

from pathlib import Path

from src.agents.survey_builder.loader import read_canonical
from src.agents.survey_builder.preflight import check_spec

FIXTURE = Path(__file__).parent / "canonical" / "S01"


def _spec():
    return read_canonical(FIXTURE)


def _question(spec, qid):
    return next(q for q in spec["questions"] if q["question_id"] == qid)


def _blocking(spec):
    return [g for g in check_spec(spec) if g.blocking]


def test_clean_specification_has_no_gaps():
    assert check_spec(_spec()) == []


def test_unsupported_kind_blocks():
    spec = _spec()
    _question(spec, "Q1")["kind"] = "ranking"
    assert any("not supported" in g.problem for g in _blocking(spec))


def test_unread_display_condition_blocks():
    spec = _spec()
    _question(spec, "Q6")["guard"]["condition"] = None
    assert any(g.where == "Q6" and "not read" in g.problem for g in _blocking(spec))


def test_unsupported_operator_blocks():
    spec = _spec()
    _question(spec, "Q6")["guard"]["condition"]["op"] = "answered"
    assert any("cannot be built" in g.problem for g in _blocking(spec))


def test_unread_terminate_rule_blocks():
    spec = _spec()
    rule = next(r for r in spec["rules"] if r["kind"] == "terminate")
    rule["when"] = None
    assert any(g.where == rule["rule_id"] for g in _blocking(spec))
