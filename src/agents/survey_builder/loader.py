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
_COMPARISON = re.compile(r"^\s*(\w+)\s*(==|!=)\s*'([^']*)'\s*$")

# "Q12 IN ['Fully','Partly']", brackets or parentheses.
_MEMBERSHIP = re.compile(
    r"^\s*(\w+)\s+(NOT\s+IN|IN)\s*[\[(](.+)[\])]\s*$", re.IGNORECASE
)

# "CONTAINS_ANY(Q1, 'a', 'b')" and "CONTAINS_ANY(Q1, ['a','b'])".
_CONTAINS_CALL = re.compile(
    r"^\s*(CONTAINS_ANY|CONTAINS_ALL)\s*\(\s*(\w+)\s*,\s*(.+?)\s*\)\s*$",
    re.IGNORECASE,
)

# "Q5 CONTAINS_ANY ('a','b')".
_CONTAINS_INFIX = re.compile(
    r"^\s*(\w+)\s+(CONTAINS_ANY|CONTAINS_ALL)\s*[\[(](.+)[\])]\s*$",
    re.IGNORECASE,
)

_QUOTED = re.compile(r"'([^']*)'")

#: A ticked checkbox stores this, and each option is its own field.
_CHECKED = "Y"

# Stage 4 neutral type -> LimeSurvey type letter.
_TYPE_MAP = {
    "single": "L",
    "multi": "M",
    "text": "T",  # S, a single-line box, is available but never inferred
    "matrix": "F",
    "constant_sum": "K",
}

#: Types whose options are stored as subquestions rather than answers.
_SUBQUESTION_TYPES = {"M", "K"}

# "Show only touchpoints selected at Q5." -> Q5
_SOURCE_QUESTION = re.compile(r"\b([A-Z]{1,3}\d+)\b")


class ConditionError(ValueError):
    """A routing condition could not be resolved against the questionnaire."""


def _code_for(index: int) -> str:
    return f"A{index + 1:03d}"


def _subquestion_code_for(index: int) -> str:
    return f"SQ{index + 1:03d}"


def _limesurvey_type(raw: dict) -> str:
    """Map a neutral question type to LimeSurvey's type letter.

    Free text always becomes T. LimeSurvey also has S for a single-line box,
    but the QRE never says which it wants and the difference is only the size
    of the input; both accept the same answers and both honour maximum_chars.
    Guessing from max_length would invent a distinction the source never made.
    """
    kind = (raw.get("type") or "").strip().lower()
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
    raw_rows = raw.get("matrix_rows") or []

    def _subquestions(items):
        return [
            Subquestion(
                code=_subquestion_code_for(i),
                label=item["label"],
                question_order=i,
            )
            for i, item in enumerate(items)
        ]

    def _options(items):
        return [
            Option(
                code=item.get("code") or _code_for(i),
                label=item["label"],
                sortorder=i,
            )
            for i, item in enumerate(items)
        ]

    if question.type == "F":
        # An array puts its rows in subquestions and its scale in answers.
        question.subquestions = _subquestions(raw_rows)
        question.options = _options(raw_options)
    elif question.type in _SUBQUESTION_TYPES:
        question.subquestions = _subquestions(raw_options)
    else:
        question.options = _options(raw_options)

    exclusive = raw.get("exclusive_option")
    if exclusive:
        # LimeSurvey addresses the option by its subquestion code, not its label.
        question.attributes["exclude_all_others"] = _subquestion_code_of_label(
            question, exclusive
        )

    if raw.get("sum_to") is not None:
        # Forces the entered numbers to add up, which is what makes a
        # multiple-numeric question behave as a constant sum.
        question.attributes["equals_num_value"] = str(int(raw["sum_to"]))
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


def _subquestion_code_of_label(question: Question, label: str) -> str:
    wanted = label.strip().casefold()
    for subquestion in question.subquestions:
        if subquestion.label.strip().casefold() == wanted:
            return subquestion.code
    raise ConditionError(
        f"{question.title}: no option labelled {label!r} to mark exclusive"
    )


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


def _question(question_id: str, by_title: dict[str, Question]) -> Question:
    if question_id not in by_title:
        raise ConditionError(f"condition names unknown question {question_id!r}")
    return by_title[question_id]


def _relevance(condition: str, by_title: dict[str, Question]) -> str:
    """Turn a neutral condition into a LimeSurvey relevance expression.

        Q5 == 'Yes'                 ->  (Q5.NAOK == "A001")
        Q12 IN ['Fully','Partly']   ->  (Q12.NAOK == "A001" or Q12.NAOK == "A002")
        CONTAINS_ANY(Q1, 'A', 'B')  ->  (Q1_SQ001.NAOK == "Y" or Q1_SQ002.NAOK == "Y")

    A multiple-choice option is a subquestion, so it is addressed as
    QUESTION_SUBQUESTION and holds "Y" when ticked, not as a value on the
    parent question.
    """
    match = _COMPARISON.match(condition)
    if match:
        question_id, operator, label = match.groups()
        question = _question(question_id, by_title)
        code = _code_of_label(question, label)
        return f'({question_id}.NAOK {operator} "{code}")'

    match = _CONTAINS_CALL.match(condition) or _CONTAINS_INFIX.match(condition)
    if match:
        groups = match.groups()
        # The call form reads (keyword, question, body); the infix form reads
        # (question, keyword, body).
        if groups[0].upper().startswith("CONTAINS"):
            keyword, question_id, body = groups
        else:
            question_id, keyword, body = groups
        question = _question(question_id, by_title)
        if not question.subquestions:
            raise ConditionError(
                f"{question_id}: {keyword.upper()} needs a multiple-choice question"
            )
        labels = _QUOTED.findall(body)
        if not labels:
            raise ConditionError(
                f"cannot resolve {condition!r}; it may compare two questions"
            )
        joiner = " and " if keyword.upper().endswith("ALL") else " or "
        tests = [
            f'{question_id}_{_code_of_label(question, label)}.NAOK == "{_CHECKED}"'
            for label in labels
        ]
        return "(" + joiner.join(tests) + ")"

    match = _MEMBERSHIP.match(condition)
    if match:
        question_id, keyword, body = match.groups()
        question = _question(question_id, by_title)
        labels = _QUOTED.findall(body)
        if not labels:
            raise ConditionError(f"no quoted values in {condition!r}")
        negated = keyword.upper().startswith("NOT")
        operator = "!=" if negated else "=="
        joiner = " and " if negated else " or "
        tests = [
            f'{question_id}.NAOK {operator} "{_code_of_label(question, label)}"'
            for label in labels
        ]
        return "(" + joiner.join(tests) + ")"

    raise ConditionError(f"cannot parse condition {condition!r}")


def _invert(expression: str) -> str:
    """Negate a comparison so a terminate rule becomes a proceed rule."""
    if " or " in expression or " and " in expression:
        return f"not{expression}"
    if "==" in expression:
        return expression.replace("==", "!=", 1)
    if "!=" in expression:
        return expression.replace("!=", "==", 1)
    raise ConditionError(f"cannot invert {expression!r}")


def _end_text(messages: list[dict], terminations: list[tuple[str, str]]) -> str:
    """One end screen that varies by why the respondent got there.

    LimeSurvey has no terminate action, so the group relevance inverts the
    terminate rules into a proceed condition and the end text tests the
    originals. A QRE may define several disposition codes; rules sharing a
    message are OR-ed together, and distinct messages nest.
    """
    by_code = {m["code"]: m["message"] for m in messages}
    complete = by_code.get("COMPLETE", "Thank you.")
    if not terminations:
        return f"<p>{complete}</p>"

    # Group conditions by the message they produce, preserving first-seen order.
    by_message: dict[str, list[str]] = {}
    for expression, code in terminations:
        message = by_code.get(code, "You do not qualify for this survey.")
        by_message.setdefault(message, []).append(expression)

    text = f'"{complete}"'
    for message, expressions in reversed(list(by_message.items())):
        test = " or ".join(expressions)
        text = f'if({test}, "{message}", {text})'
    return f"<p>{{{text}}}</p>"


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

    # Routing is read before the questionnaire's own display conditions.
    # Both describe the same rule, but the questionnaire copies the QRE
    # verbatim ("Q1 contains at least one brand") while routing carries the
    # normalised expression, so routing is the parseable one and wins.
    #
    # A skip rule is the complement of a show rule on the same question and is
    # already satisfied by it, so it needs nothing emitted.
    proceed: list[str] = []
    terminate: list[tuple[str, str]] = []
    skipped_rejects: list[str] = []
    shown: dict[str, str] = {}
    for rule in routing_raw:
        action = rule["action"].strip().lower()
        condition = (
            rule.get("condition_expression")
            or rule.get("condition")
            or rule.get("condition_raw")
            or ""
        )
        if action == "terminate":
            expression = _relevance(condition, by_title)
            terminate.append((expression, rule["destination"]))
            proceed.append(_invert(expression))
        elif action == "reject":
            # A reject rule bars the respondent from continuing, which is
            # validation rather than routing. Every one seen so far restates a
            # constraint already carried on the question itself: sum_to,
            # exclusive_option or dynamic_option_source. Skipping them here
            # avoids emitting the same rule twice in two different places.
            skipped_rejects.append(rule["rule"])
        elif action == "show":
            destination = rule["destination"]
            if destination in by_title:
                shown[destination] = _relevance(condition, by_title)

    for raw in questions_raw:
        question = by_title[raw["id"]]
        if raw["id"] in shown:
            question.relevance = shown[raw["id"]]
        elif raw.get("display_condition"):
            question.relevance = _relevance(raw["display_condition"], by_title)

    # A question whose options are carried from an earlier question uses
    # array_filter, which names the source question by code.
    for raw in questions_raw:
        source = raw.get("dynamic_option_source")
        if not source:
            continue
        match = _SOURCE_QUESTION.search(source)
        if not match or match.group(1) not in by_title:
            raise ConditionError(
                f"{raw['id']}: cannot tell which question {source!r} refers to"
            )
        by_title[raw["id"]].attributes["array_filter"] = match.group(1)

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
