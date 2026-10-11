"""Stage 5's content check: does it notice when Stage 4 changes what a row says?

Built from S01's committed Agent 1 output. The clean pairing must produce no
finding, and each deliberate change to a Stage 4 object must produce one.

    python -m pytest tests/test_stage5_content.py
"""

from __future__ import annotations

import json
from pathlib import Path

from src.agents.qre_interpretation.models import Question, RoutingRule, Stage3Block
from src.agents.qre_interpretation.stage5_audit import check_content_fidelity
from src.common import paths

AGENT1 = Path(__file__).resolve().parents[1] / "out" / "S01_campus_cafeteria_experience" / "agent1"


def _content(name: str):
    data = json.loads((AGENT1 / name).read_text(encoding="utf-8"))
    return data["content"] if isinstance(data, dict) and "content" in data else data


def _load():
    stage3 = [
        Stage3Block.model_validate(_content(paths.agent1_stage(3, "questionnaire.json"))),
        Stage3Block.model_validate(_content(paths.agent1_stage(3, "routing.json"))),
    ]
    parsed = {
        "questions": [Question.model_validate(q) for q in _content(paths.agent1_stage(4, "questionnaire.json"))],
        "routing": [RoutingRule.model_validate(r) for r in _content(paths.agent1_stage(4, "routing.json"))],
    }
    return stage3, parsed


def _question(parsed, qid):
    return next(q for q in parsed["questions"] if q.id == qid)


def _findings(stage3, parsed):
    return [f.finding for f in check_content_fidelity(stage3, parsed)]


def test_clean_output_has_no_findings():
    stage3, parsed = _load()
    assert _findings(stage3, parsed) == []


def test_changed_wording_is_found():
    stage3, parsed = _load()
    _question(parsed, "Q1").wording = "Which channel did you use?"
    assert any(f.startswith("wording:") for f in _findings(stage3, parsed))


def test_dropped_option_is_found():
    stage3, parsed = _load()
    _question(parsed, "Q1").options.pop()
    assert any("options cell text missing" in f for f in _findings(stage3, parsed))


def test_changed_validation_is_found():
    stage3, parsed = _load()
    _question(parsed, "Q6").min_length = 5
    assert any(f.startswith("validation min_length") for f in _findings(stage3, parsed))


def test_lost_optional_instruction_is_found():
    stage3, parsed = _load()
    _question(parsed, "Q8").optional = False
    assert any("Optional" in f for f in _findings(stage3, parsed))


def test_changed_rule_destination_is_found():
    stage3, parsed = _load()
    parsed["routing"][0].destination = "Q1"
    assert any(f.startswith("destination:") for f in _findings(stage3, parsed))
