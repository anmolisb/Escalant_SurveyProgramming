"""Load Agent 1's canonical specification into the survey IR.

Reads one file, `agent1_canonical_survey_spec.json`. Everything the builder needs is in it:
the survey heading, the questions with their options and validation, the
routing rules and display guards as parsed condition trees, and the endings.

Two jobs the QRE does not do for us:

1. Option codes. The canonical leaves `code` null when the QRE did not spell
   one out. We generate A001, A002, ... in option order. Every downstream
   reference is by code, never by label.

2. Condition to relevance. Conditions arrive as trees (operator, question,
   answers) rather than strings, so they are written out by walking the tree.
   An answer is found by its label on the question it belongs to. A miss
   raises; defaulting here would silently invert a screening rule.

What this loader can build is stated once, in SUPPORTED_KINDS, SUPPORTED_OPS
and SUPPORTED_RULE_KINDS, so a readiness check can report gaps before a build
rather than meeting them halfway through one.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.common import paths as fnames
from src.agents.survey_builder.models import Group, Option, Question, Subquestion, Survey

#: The file this loader reads, inside Agent 1's output folder.
CANONICAL_FILE = fnames.CANONICAL

# Questions whose id starts with S are screening; everything else is main body.
_SCREENING_PREFIX = "S"

#: A ticked checkbox stores this, and each option is its own field.
_CHECKED = "Y"

# Canonical question kind -> LimeSurvey type letter.
_TYPE_MAP = {
    "single": "L",
    "multi": "M",
    "text": "T",  # S, a single-line box, is available but never inferred
    "matrix": "F",
    "constant_sum": "K",
    "integer": "N",
    "number": "N",
    # Shows text and asks nothing, such as "You're almost done!".
    "text display": "X",
}

#: Types that take a typed-in number rather than a choice.
_NUMERIC_TYPES = {"N", "K"}

#: Types whose options are stored as subquestions rather than answers.
_SUBQUESTION_TYPES = {"M", "K"}

#: Question kinds this builder can turn into a LimeSurvey question.
SUPPORTED_KINDS = frozenset(_TYPE_MAP)

#: Condition operators `_relevance` can write as ExpressionScript.
SUPPORTED_OPS = frozenset({
    "eq", "ne", "lt", "le", "gt", "ge", "in", "not_in",
    "contains", "contains_any", "contains_all", "and", "or", "not",
})

#: Rule kinds the builder acts on. A skip rule is the complement of a show rule
#: and is already satisfied by it. A reject rule restates a constraint the
#: question carries itself (sum, exclusive option, piped options), so it is
#: deliberately not emitted a second time.
SUPPORTED_RULE_KINDS = frozenset({"terminate", "show", "skip", "reject"})

_COMPARE = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}


class ConditionError(ValueError):
    """A condition could not be resolved against the questionnaire."""


def _number(value) -> str:
    """Numbers can arrive as floats; LimeSurvey wants 18, not 18.0."""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _code_for(index: int) -> str:
    return f"A{index + 1:03d}"


def _subquestion_code_for(index: int) -> str:
    return f"SQ{index + 1:03d}"


def _limesurvey_type(raw: dict) -> str:
    """Map a canonical question kind to LimeSurvey's type letter.

    Free text always becomes T. LimeSurvey also has S for a single-line box,
    but the QRE never says which it wants and the difference is only the size
    of the input; both accept the same answers. Guessing from max_length would
    invent a distinction the source never made.
    """
    kind = (raw.get("kind") or "").strip().lower()
    if kind not in _TYPE_MAP:
        raise ValueError(f"{raw.get('question_id')}: unmapped question kind {kind!r}")
    return _TYPE_MAP[kind]


def _build_question(raw: dict, order: int, randomized: bool) -> Question:
    validation = raw.get("validation") or {}
    question = Question(
        title=raw["question_id"],
        text=raw["wording"],
        type=_limesurvey_type(raw),
        question_order=order,
        # A text display has nothing to answer, so it is never mandatory
        # whatever the specification says.
        mandatory=("Y" if validation.get("mandatory", True)
                   and _TYPE_MAP.get((raw.get("kind") or "").strip().lower()) != "X"
                   else "N"),
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

    if question.type in _NUMERIC_TYPES:
        # LimeSurvey names the bounds on a numeric question with an _n suffix;
        # min_num_value and max_num_value without it are a different setting.
        if validation.get("min_value") is not None:
            question.attributes["min_num_value_n"] = _number(validation["min_value"])
        if validation.get("max_value") is not None:
            question.attributes["max_num_value_n"] = _number(validation["max_value"])
        if (raw.get("kind") or "").strip().lower() == "integer":
            question.attributes["num_value_int_only"] = "1"

    if randomized:
        # answer_order takes a word, not a flag; "normal" is the default.
        question.attributes["answer_order"] = "random"

    exclusive = validation.get("exclusive_option_label")
    if exclusive:
        # LimeSurvey addresses the option by its subquestion code, not its label.
        question.attributes["exclude_all_others"] = _subquestion_code_of_label(
            question, exclusive
        )

    if validation.get("sum_to") is not None:
        # Forces the entered numbers to add up, which is what makes a
        # multiple-numeric question behave as a constant sum.
        question.attributes["equals_num_value"] = str(int(validation["sum_to"]))
    if validation.get("min_selections") is not None:
        question.attributes["min_answers"] = str(validation["min_selections"])

    # There is deliberately no maximum_chars here. LimeSurvey's own setting
    # quietly cuts an over-long answer down to fit, so the validation below
    # never sees it and the respondent is never told. Measured on a live
    # survey: a 501 character answer was kept as 500 and accepted with no
    # error. The validation on its own refuses it and shows the tip.
    #
    # LimeSurvey has no minimum-length setting either. Both limits are
    # expressed as one validation because a question can state both and a
    # second em_validation_q would replace the first rather than add to it.
    #
    # Spaces alone are not an answer. LimeSurvey's mandatory check accepts
    # them, so the minimum is measured on the trimmed answer, and a compulsory
    # question always needs at least one real character. On an optional
    # question an answer of spaces counts as blank, so it is let through.
    checks: list[str] = []
    tips: list[str] = []
    minimum = validation.get("min_length")
    compulsory = question.mandatory == "Y" and question.type in ("S", "T", "U")
    if compulsory:
        checks.append(f"strlen(trim(this)) >= {max(1, minimum or 1)}")
        tips.append(f"at least {minimum} characters" if minimum
                    else "an answer, not just spaces")
    elif minimum is not None:
        checks.append(f"(strlen(trim(this)) == 0 or "
                      f"strlen(trim(this)) >= {minimum})")
        tips.append(f"at least {minimum} characters")
    if validation.get("max_length") is not None:
        checks.append(f"strlen(this) <= {validation['max_length']}")
        tips.append(f"no more than {validation['max_length']} characters")
    if checks:
        question.attributes["em_validation_q"] = " and ".join(checks)
        question.localized_attributes["em_validation_q_tip"] = (
            "Please enter " + " and ".join(tips) + "."
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


def _question(question_id: str | None, by_title: dict[str, Question]) -> Question:
    if not question_id or question_id not in by_title:
        raise ConditionError(f"condition names unknown question {question_id!r}")
    return by_title[question_id]


def _labels(operand: dict | None) -> list[str]:
    """The answers a condition names, by label."""
    operand = operand or {}
    if operand.get("values"):
        return list(operand["values"])
    if operand.get("text") is not None:
        return [operand["text"]]
    return []


def _relevance(condition: dict, by_title: dict[str, Question]) -> str:
    """Turn a condition tree into a LimeSurvey relevance expression.

        Q5 == 'Yes'                  ->  (Q5.NAOK == "A001")
        S3 < 18                      ->  (S3.NAOK < 18)
        Q12 in ['Fully','Partly']    ->  (Q12.NAOK == "A001" or Q12.NAOK == "A002")
        Q1 contains_any ['A', 'B']   ->  (Q1_SQ001.NAOK == "Y" or Q1_SQ002.NAOK == "Y")

    A multiple-choice option is a subquestion, so it is addressed as
    QUESTION_SUBQUESTION and holds "Y" when ticked, not as a value on the
    parent question.
    """
    op = condition.get("op")
    if op not in SUPPORTED_OPS:
        raise ConditionError(f"operator {op!r} is not supported")

    if op in ("and", "or"):
        parts = [_relevance(part, by_title) for part in condition.get("operands") or []]
        if not parts:
            raise ConditionError(f"{op!r} with nothing to combine")
        return "(" + f" {op} ".join(parts) + ")"
    if op == "not":
        parts = condition.get("operands") or []
        if len(parts) != 1:
            raise ConditionError("'not' must negate exactly one condition")
        return f"not{_relevance(parts[0], by_title)}"

    left = condition.get("left") or {}
    right = condition.get("right") or {}
    if left.get("aggregate"):
        raise ConditionError(f"{left['aggregate']}() is not supported")
    if right.get("question_id"):
        raise ConditionError("comparing one question with another is not supported")
    question_id = left.get("question_id")
    question = _question(question_id, by_title)

    if op in _COMPARE and right.get("number") is not None:
        # A numeric question holds a typed-in number, so the value is compared
        # directly rather than looked up as an answer code.
        return f"({question_id}.NAOK {_COMPARE[op]} {_number(right['number'])})"

    labels = _labels(right)
    if not labels:
        raise ConditionError(f"{question_id}: condition names no answer")

    if op in ("eq", "ne"):
        if len(labels) != 1:
            raise ConditionError(f"{question_id}: {op} needs exactly one answer")
        code = _code_of_label(question, labels[0])
        return f'({question_id}.NAOK {_COMPARE[op]} "{code}")'

    if op in ("contains", "contains_any", "contains_all"):
        if not question.subquestions:
            raise ConditionError(f"{question_id}: {op} needs a multiple-choice question")
        joiner = " and " if op == "contains_all" else " or "
        tests = [
            f'{question_id}_{_code_of_label(question, label)}.NAOK == "{_CHECKED}"'
            for label in labels
        ]
        return "(" + joiner.join(tests) + ")"

    if op in ("in", "not_in"):
        negated = op == "not_in"
        operator = "!=" if negated else "=="
        joiner = " and " if negated else " or "
        tests = [
            f'{question_id}.NAOK {operator} "{_code_of_label(question, label)}"'
            for label in labels
        ]
        return "(" + joiner.join(tests) + ")"

    raise ConditionError(f"operator {op!r} cannot be applied to {question_id}")


def _named_question(condition: dict) -> str | None:
    """The question a single answer test is about, for a terminate rule.

    Only a plain answer comparison or membership test names the question the
    respondent is terminated at. A numeric comparison or a combination does
    not, and those keep the earlier behaviour of gating only the main group.
    """
    if condition.get("op") not in ("eq", "ne", "in", "not_in"):
        return None
    if (condition.get("right") or {}).get("number") is not None:
        return None
    return (condition.get("left") or {}).get("question_id")


def _invert(expression: str) -> str:
    """Negate a comparison so a terminate rule becomes a proceed rule."""
    if " or " in expression or " and " in expression:
        return f"not{expression}"
    if "==" in expression:
        return expression.replace("==", "!=", 1)
    if "!=" in expression:
        return expression.replace("!=", "==", 1)
    raise ConditionError(f"cannot invert {expression!r}")


def _end_text(messages: dict[str, str], terminations: list[tuple[str, str]]) -> str:
    """One end screen that varies by why the respondent got there.

    LimeSurvey has no terminate action, so the group relevance inverts the
    terminate rules into a proceed condition and the end text tests the
    originals. A QRE may define several disposition codes; rules sharing a
    message are OR-ed together, and distinct messages nest.
    """
    complete = messages.get("COMPLETE", "Thank you.")
    if not terminations:
        return f"<p>{complete}</p>"

    # Group conditions by the message they produce, preserving first-seen order.
    by_message: dict[str, list[str]] = {}
    for expression, code in terminations:
        message = messages.get(code, "You do not qualify for this survey.")
        by_message.setdefault(message, []).append(expression)

    text = f'"{complete}"'
    for message, expressions in reversed(list(by_message.items())):
        test = " or ".join(expressions)
        text = f'if({test}, "{message}", {text})'
    return f"<p>{{{text}}}</p>"


def read_canonical(directory: str | Path) -> dict:
    """The canonical specification in a folder, without its artifact envelope."""
    data = json.loads((Path(directory) / CANONICAL_FILE).read_text(encoding="utf-8"))
    return data["content"] if isinstance(data, dict) and "content" in data else data


def load(directory: str | Path) -> Survey:
    spec = read_canonical(directory)

    randomized = {r["question_id"] for r in spec.get("randomization") or []}
    screening: list[Question] = []
    main: list[Question] = []
    for raw in spec.get("questions") or []:
        target = screening if raw["question_id"].startswith(_SCREENING_PREFIX) else main
        target.append(
            _build_question(raw, order=len(target) + 1,
                            randomized=raw["question_id"] in randomized)
        )

    by_title = {q.title: q for q in [*screening, *main]}

    # A question's guard already combines the routing table's show rules with
    # the questionnaire's own display condition, so it is the one place to
    # read when a question is shown.
    for raw in spec.get("questions") or []:
        condition = (raw.get("guard") or {}).get("condition")
        if condition:
            by_title[raw["question_id"]].relevance = _relevance(condition, by_title)

    proceed: list[str] = []
    terminate: list[tuple[str, str]] = []
    terminate_at: list[tuple[str, str]] = []
    for rule in spec.get("rules") or []:
        if rule.get("kind") != "terminate":
            continue
        condition = rule.get("when")
        if not condition:
            raise ConditionError(
                f"{rule['rule_id']}: terminate rule has no readable condition "
                f"({rule.get('when_unread')!r})"
            )
        expression = _relevance(condition, by_title)
        terminate.append((expression, (rule.get("destination") or {}).get("id")))
        proceed.append(_invert(expression))
        named = _named_question(condition)
        if named:
            terminate_at.append((expression, named))

    # A terminate rule ends the interview at the question it names, so nothing
    # after that question should be asked. Gating the main group is not enough:
    # that stops the main survey but still shows the remaining screeners, so a
    # respondent who fails S1 is asked S2 before being let go. Each question
    # therefore also carries the negation of every terminate rule attached to a
    # question that comes before it.
    # Only questions sharing a group with the terminating question need this.
    # Anything in a later group is already covered by that group's own gate,
    # and repeating it on every question would say the same thing twice.
    screening_ids = [q.title for q in screening]
    for expression, question_id in terminate_at:
        if question_id not in screening_ids:
            continue
        gate = _invert(expression)
        for later in screening_ids[screening_ids.index(question_id) + 1:]:
            question = by_title[later]
            if question.relevance == "1":
                question.relevance = gate
            elif gate not in question.relevance:
                question.relevance = f"{question.relevance} and {gate}"

    # A question whose options are carried from an earlier question uses
    # array_filter, which names the source question by code.
    for raw in spec.get("questions") or []:
        source = (raw.get("option_source") or {}).get("from_question")
        if not source:
            continue
        if source not in by_title:
            raise ConditionError(
                f"{raw['question_id']}: options come from unknown question {source!r}"
            )
        by_title[raw["question_id"]].attributes["array_filter"] = source

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

    heading = spec.get("survey") or {}
    qre_id = heading.get("qre_id")
    title = heading.get("title") or ""
    if qre_id and not title.startswith(qre_id):
        title = f"{qre_id} - {title}"

    messages = {
        d["disposition_id"]: d["message"]
        for d in spec.get("dispositions") or []
        if d.get("disposition_id") and d.get("message")
    }

    return Survey(
        title=title,
        description=heading.get("description") or "",
        welcome_text=heading.get("welcome_text") or "",
        end_text=_end_text(messages, terminate),
        groups=groups,
    )
