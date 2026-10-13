"""The readiness check names what Agents 2, 3 and 4 cannot handle, before they run.

Built from the Survey Builder's S01 canonical fixture. The clean specification
is ready for every agent, and each deliberate change is reported against the
agent it affects.

    python -m pytest tests/test_readiness.py
"""

from __future__ import annotations

from pathlib import Path

from src.agents.survey_builder.loader import read_canonical
from src.agents.test_design import b2_witness
from src.common import readiness

FIXTURE = Path(__file__).parent / "survey_builder" / "canonical" / "S01"


def _spec():
    return read_canonical(FIXTURE)


def _question(spec, qid):
    return next(q for q in spec["questions"] if q["question_id"] == qid)


def test_clean_specification_is_ready_for_every_agent():
    assert readiness.check_spec(_spec()) == []


def test_a_kind_the_test_designer_cannot_answer_blocks(monkeypatch):
    """M01's age question: a kind with no answer stops every journey at it."""
    spec = _spec()
    _question(spec, "Q1")["kind"] = "integer"
    _question(spec, "Q1")["options"] = []
    monkeypatch.setattr(b2_witness, "SUPPORTED_KINDS",
                        b2_witness.SUPPORTED_KINDS - {"integer"})
    findings = readiness.check_spec(spec)
    assert any(f.agent == 3 and f.where == "Q1" and f.blocking for f in findings)


def test_a_numeric_comparison_is_supported():
    spec = _spec()
    guard = _question(spec, "Q6")["guard"]["condition"]
    guard["op"] = "lt"
    guard["right"] = {"number": 3}
    assert not [f for f in readiness.check_spec(spec)
                if f.agent == 3 and f.where == "Q6"]


def test_an_unsupported_operator_is_named_for_the_test_designer():
    spec = _spec()
    guard = _question(spec, "Q6")["guard"]["condition"]
    guard["op"] = "starts_with"
    guard["right"] = {"text": "A"}
    findings = [f for f in readiness.check_spec(spec) if f.agent == 3]
    assert any(f.where == "Q6" and not f.blocking for f in findings)


def test_an_unread_condition_is_reported_to_both_agents():
    spec = _spec()
    _question(spec, "Q6")["guard"]["condition"] = None
    findings = readiness.check_spec(spec)
    assert any(f.agent == 2 and f.where == "Q6" and f.blocking for f in findings)
    assert any(f.agent == 3 and f.where == "Q6" for f in findings)
