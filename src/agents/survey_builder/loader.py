"""Load stage 4 JSON into the survey IR.

Reads four files from the stage 4 output directory: survey, questionnaire,
routing and messages.

Two jobs the QRE does not do for us:

1. Option codes. Stage 4 leaves `code` null when the QRE did not spell one out.
   We generate A001, A002, ... in option order. Every downstream reference is
   by code, never by label.

2. Label to code resolution. Routing conditions name answers by label
   ("S1 == 'No'"), so we look the label up to get its code. A miss raises;
   defaulting here would silently invert a screening rule.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.agents.survey_builder.models import Group, Option, Question, Subquestion, Survey

# Questions whose id starts with S are screening; everything else is main body.
_SCREENING_PREFIX = "S"

# "Q5 == 'Yes'" -> ("Q5", "==", "Yes")
_CONDITION = re.compile(r"^\s*(\w+)\s*(==|!=)\s*'([^']*)'\s*$")

# Stage 4 neutral type -> LimeSurvey type letter.
_TYPE_MAP = {
    "single": "L",
    "multi": "M",
    "text": "T",
}

# A free-text question shorter than this is a short text box, not a long one.
_SHORT_TEXT_MAX = 100


class ConditionError(ValueError):
    """A routing condition could not be resolved against the questionnaire."""


def _code_for(index: int) -> str:
    return f"A{index + 1:03d}"


def _subquestion_code_for(index: int) -> str:
    return f"SQ{index + 1:03d}"


def _limesurvey_type(raw: dict) -> str:
    kind = (raw.get("type") or "").strip().lower()
    if kind == "text":
        max_length = raw.get("max_length")
        if max_length is not None and int(max_length) <= _SHORT_TEXT_MAX:
            return "S"
        return "T"
    if kind not in _TYPE_MAP:
        raise ValueError(f"{raw.get('id')}: unmapped question type {kind!r}")
    return _TYPE_MAP[kind]


def _build_question(raw: dict, order: int) -> Question:
    question = Question(
        title=raw["id"],
        text=raw["wording"],
        type=_limesurvey_type(raw),
        question_order=order,
        mandatory="N" if raw.get("optional") else "Y",
    )

    raw_options = raw.get("options") or []
    if question.type == "M":
        question.subquestions = [
            Subquestion(
                code=_subquestion_code_for(i),
                label=option["label"],
                question_order=i,
            )
            for i, option in enumerate(raw_options)
        ]
    else:
        question.options = [
            Option(
                code=option.get("code") or _code_for(i),
                label=option["label"],
                sortorder=i,
            )
            for i, option in enumerate(raw_options)
        ]

    if raw.get("min_selections") is not None:
        question.attributes["min_answers"] = str(raw["min_selections"])
    if raw.get("max_length") is not None:
        question.attributes["maximum_chars"] = str(raw["max_length"])
    if raw.get("min_length") is not None:
        # LimeSurvey has no minimum-length setting; this is the only route.
        question.attributes["em_validation_q"] = f"strlen(this) >= {raw['min_length']}"
        question.localized_attributes["em_validation_q_tip"] = (
            f"Please enter at least {raw['min_length']} characters."
        )

    return question


def _code_of_label(question: Question, label: str) -> str:
    """Find the code for an answer label. Raises rather than guessing."""
    wanted = label.strip().casefold()
    for option in question.options:
        if option.label.strip().casefold() == wanted:
            return option.code
    for subquestion in question.subquestions:
        if subquestion.label.strip().casefold() == wanted:
            return subquestion.code
    raise ConditionError(
        f"{question.title}: no option labelled {label!r}. "
        f"Have: {[o.label for o in question.options] or [s.label for s in question.subquestions]}"
    )


def _relevance(condition: str, by_title: dict[str, Question]) -> str:
    """Turn "Q5 == 'Yes'" into '(Q5.NAOK == "A001")'."""
    match = _CONDITION.match(condition)
    if not match:
        raise ConditionError(f"cannot parse condition {condition!r}")
    question_id, operator, label = match.groups()
    if question_id not in by_title:
        raise ConditionError(f"condition names unknown question {question_id!r}")
    code = _code_of_label(by_title[question_id], label)
    return f'({question_id}.NAOK {operator} "{code}")'


def _end_text(messages: list[dict], terminate_conditions: list[str]) -> str:
    """One end screen that shows a different message to screened-out respondents.

    The routing rules say "terminate if S1 is No" and "terminate if S2 is No".
    LimeSurvey has no terminate action, so the group relevance inverts these
    into a single proceed condition, and the end text tests the original ones.
    """
    by_code = {m["code"]: m["message"] for m in messages}
    complete = by_code.get("COMPLETE", "Thank you.")
    if not terminate_conditions:
        return f"<p>{complete}</p>"
    ineligible = by_code.get("TERM_INELIGIBLE", "You do not qualify for this survey.")
    test = " or ".join(terminate_conditions)
    return f'<p>{{if({test}, "{ineligible}", "{complete}")}}</p>'


def load(directory: str | Path) -> Survey:
    directory = Path(directory)
    survey_raw = json.loads((directory / "stage4_survey.json").read_text())
    questions_raw = json.loads((directory / "stage4_questionnaire.json").read_text())
    routing_raw = json.loads((directory / "stage4_routing.json").read_text())
    messages_raw = json.loads((directory / "stage4_messages.json").read_text())

    screening: list[Question] = []
    main: list[Question] = []
    for raw in questions_raw:
        target = screening if raw["id"].startswith(_SCREENING_PREFIX) else main
        target.append(_build_question(raw, order=len(target) + 1))

    by_title = {q.title: q for q in [*screening, *main]}

    # Per-question display conditions from the questionnaire.
    for raw in questions_raw:
        condition = raw.get("display_condition")
        if condition:
            by_title[raw["id"]].relevance = _relevance(condition, by_title)

    # Routing: terminate rules gate the main group, show rules set relevance.
    # A skip rule is the complement of a show rule on the same question and is
    # already satisfied by it, so it needs nothing emitted.
    proceed: list[str] = []
    terminate: list[str] = []
    for rule in routing_raw:
        action = rule["action"].strip().lower()
        condition = rule.get("condition") or rule.get("condition_raw") or ""
        if action == "terminate":
            expression = _relevance(condition, by_title)
            terminate.append(expression)
            proceed.append(expression.replace("==", "!=", 1))
        elif action == "show":
            destination = rule["destination"]
            if destination in by_title:
                by_title[destination].relevance = _relevance(condition, by_title)

    groups = []
    if screening:
        groups.append(Group(name="Screening", group_order=0, questions=screening))
    if main:
        groups.append(
            Group(
                name="Main Survey",
                group_order=len(groups),
                relevance=" and ".join(proceed) if proceed else "1",
                questions=main,
            )
        )

    qre_id = survey_raw.get("qre_id")
    title = survey_raw.get("title") or ""
    if qre_id and not title.startswith(qre_id):
        title = f"{qre_id} - {title}"

    return Survey(
        title=title,
        description=survey_raw.get("description") or "",
        welcome_text=survey_raw.get("welcome_text") or "",
        end_text=_end_text(messages_raw, terminate),
        groups=groups,
    )