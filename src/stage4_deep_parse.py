"""Stage 4 — deep parse. The first stage permitted to interpret.

All four targets are parsed concurrently via asyncio.gather. Routing carries one
real dependency: translating a condition such as "Q1 contains at least one brand"
into a formal expression needs the questionnaire's option codes. That is modelled
by awaiting the questionnaire task inside the routing task, so routing blocks on
the data it needs and on nothing else — the other two never wait at all.

LLM use: splitting a question's inline attributes, and translating a routing
condition. Everything a regex or json.loads can do is done without a model.
"""

from __future__ import annotations

import asyncio
import json
import re

from llm import LLMUnavailable, complete_async
from models import (
    AcceptanceScenario,
    CompletionMessage,
    ExtractedStatement,
    FlagSeverity,
    FlagStatus,
    FlagTarget,
    LLMQuestionFields,
    LLMRoutingExpression,
    Option,
    Origin,
    Question,
    ReviewFlag,
    RoutingRule,
    SourceReference,
    Stage3Block,
    TargetHeading,
)

# ---------------------------------------------------------------------------
# Column resolution — the source names its columns, we find them by keyword
# ---------------------------------------------------------------------------

_COLUMN_HINTS = {
    "id": ("id", "ref", "rule", "no", "code", "number"),
    "wording": ("wording", "question", "text", "instruction", "purpose"),
    "type": ("type", "format"),
    "options": ("option", "scale", "codeframe", "answer", "response"),
    "display": ("display", "validation", "condition", "base", "logic"),
    "action": ("action",),
    "destination": ("destination", "target", "go to", "goto"),
    "inputs": ("input",),
    "outcome": ("outcome", "expected", "result"),
}


def _find_column(row: dict[str, str], role: str) -> str | None:
    """Return the key in `row` whose name carries this role's keyword."""
    for key in row:
        lowered = key.lower()
        if any(hint in lowered for hint in _COLUMN_HINTS[role]):
            return key
    return None


def _value(row: dict[str, str], role: str) -> str:
    key = _find_column(row, role)
    return (row.get(key) or "").strip() if key else ""


def _source_for(block: Stage3Block, index: int) -> SourceReference | None:
    """Provenance for one row, when Stage 3 recorded it.

    Tolerates a short or absent list so artifacts written before provenance
    existed still parse.
    """
    if index < len(block.row_sources):
        return block.row_sources[index]
    return None


# ---------------------------------------------------------------------------
# Questionnaire
# ---------------------------------------------------------------------------

_NO_OPTIONS = {"", "—", "-", "–", "n/a", "na"}
#: "1 - Very poor", "1=Yes", "1) Yes". Hyphen needs a trailing space so "T-shirt"
#: is not read as code "T"; "=" and ")" do not occur inside words.
_CODE = re.compile(r"^\s*(\d+|[A-Za-z0-9]{1,3})\s*(?:[=)]\s*|-\s+)(.*\S)\s*$")
_MATRIX_PART = re.compile(r"^\s*(rows?|scale|columns?)\s*:\s*(.*)$", re.IGNORECASE)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
#: An identifier standing alone in a scenario's expected outcome: a question id
#: such as Q12, or a disposition code such as TERM_AGE or COMPLETE. Deliberately
#: broad, because Part 1 collects these without deciding which kind each one is.
_IDENTIFIER = re.compile(r"\b([A-Z][A-Za-z0-9_]{1,})\b")

#: An option whose code or label is a bare number, e.g. "3", "10", "-2".
#: Anchored so "21-29" and "60+" are correctly not numbers.
_NUMERIC_OPTION = re.compile(r"^-?\d+(?:\.\d+)?$")

#: A question id inside a routing condition, e.g. Q12, S1, A_2.
_QUESTION_REF = re.compile(r"\b([A-Z]{1,3}[A-Za-z]*_?\d+)\b")

_QUESTION_SYSTEM = """\
You separate the inline attributes written in one questionnaire cell into fields.

The cell holds instructions on separate lines, for example:
    Show if: Q5 == 'Yes'
    Validate: {"min_length": 10}
    Randomize

Assign each line to a field:
- display_condition: when the question is shown. Copy the text after "Show if:" \
verbatim. Use null when the cell only says the question is always shown.
- randomize: true if any line asks for randomised order.
- optional: true if any line marks the question optional.
- dynamic_option_source: a line saying options are carried from an earlier \
question, e.g. "Show only brands selected at Q1."
- other_attributes: any remaining instruction, keyed by a short name.

Do not put a validation rule in other_attributes; validation is parsed elsewhere. \
Copy text exactly. Never invent an attribute the cell does not state.
"""


def _numeric_value(option: Option) -> float | None:
    """The number an option stands for, where the QRE wrote one.

    The code is preferred over the label because a coded scale states its number
    there — Q7 is `1 = Very poor`. Where there is no code the label may itself be
    the number, as in Q8's 0-to-10 recommendation scale.

    This reads a number the document already wrote; it does not assign one. An
    option with neither returns None rather than being given a position number,
    which would be an invention.
    """
    for candidate in (option.code, option.label):
        if candidate and _NUMERIC_OPTION.match(candidate.strip()):
            return float(candidate.strip())
    return None


def _split_options(text: str) -> list[Option]:
    if text.strip().lower() in _NO_OPTIONS:
        return []
    separator = ";" if ";" in text else ","
    options: list[Option] = []
    for part in text.split(separator):
        raw = part.strip()
        if not raw:
            continue
        match = _CODE.match(raw)
        if match:
            options.append(Option(code=match.group(1), label=match.group(2).strip()))
        else:
            options.append(Option(code=None, label=raw))
        options[-1].numeric_value = _numeric_value(options[-1])
    return options


def _split_matrix(text: str) -> tuple[list[Option], list[Option]]:
    """Return (rows, scale) for "Rows: … / Scale: …" notation."""
    rows: list[Option] = []
    scale: list[Option] = []
    for line in text.split("\n"):
        match = _MATRIX_PART.match(line)
        if not match:
            continue
        kind, payload = match.group(1).lower(), match.group(2)
        if kind.startswith("row"):
            rows = _split_options(payload)
        else:
            scale = _split_options(payload)
    return rows, scale


def _apply_validation(question: Question, cell: str) -> list[str]:
    """Lift every JSON validation payload in the cell onto typed fields."""
    errors: list[str] = []
    for line in cell.split("\n"):
        if "validate" not in line.lower():
            continue
        match = _JSON_OBJECT.search(line)
        if not match:
            errors.append(f"validation line without JSON: {line.strip()}")
            continue
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid validation JSON: {exc}")
            continue
        for key, value in payload.items():
            if key == "min_length":
                question.min_length = int(value)
            elif key == "max_length":
                question.max_length = int(value)
            elif key == "min":
                question.min_value = value
            elif key == "max":
                question.max_value = value
            elif key == "min_selections":
                question.min_selections = int(value)
            elif key == "exclusive_option":
                question.exclusive_option = str(value)
            elif key == "sum":
                question.sum_to = value
            else:
                # Stored with its own type. Flattening to a string here forced
                # every consumer to guess how to read it back.
                question.other_attributes[key] = value
    return errors


def _assign_option_ids(question: Question) -> None:
    """Give every option and matrix row a stable handle.

    Position-based, so it is derived rather than invented: it says where the
    option sits in the list the QRE wrote, and nothing more. Rows are lettered
    R so a matrix row and an answer option can never collide.

    Left alone when the question has no id, because a handle like `-O1` would
    collide across every unidentified question. The missing id is the real
    problem there and shows up on its own.
    """
    if not question.id:
        return
    for position, option in enumerate(question.options, start=1):
        option.option_id = f"{question.id}-O{position}"
    for position, row in enumerate(question.matrix_rows, start=1):
        row.option_id = f"{question.id}-R{position}"


async def parse_questionnaire(
    block: Stage3Block | None,
) -> tuple[list[Question], list[ReviewFlag]]:
    if block is None:
        return [], []

    questions: list[Question] = []
    flags: list[ReviewFlag] = []

    async def one(index: int, row: dict[str, str]) -> Question:
        options_cell = _value(row, "options")
        display_cell = _value(row, "display")

        question = Question(
            id=_value(row, "id"),
            seq=index + 1,
            wording=_value(row, "wording"),
            type=_value(row, "type"),
            source_reference=_source_for(block, index),
        )

        matrix_rows, scale = _split_matrix(options_cell)
        if matrix_rows or scale:
            question.matrix_rows = matrix_rows
            question.options = scale
        else:
            question.options = _split_options(options_cell)

        _assign_option_ids(question)

        for error in _apply_validation(question, display_cell):
            flags.append(
                ReviewFlag(
                    target_heading=TargetHeading.QUESTIONNAIRE,
                    status=FlagStatus.POSSIBLE_MATCH,
                    candidate_heading=question.id,
                    severity=FlagSeverity.BLOCKING,
                    target=FlagTarget(kind="question", id=question.id),
                    reasoning=error,
                )
            )

        if display_cell:
            try:
                fields = await complete_async(
                    _QUESTION_SYSTEM,
                    f"Question {question.id} cell:\n{display_cell}",
                    LLMQuestionFields,
                )
                question.display_condition = fields.display_condition
                question.randomize = fields.randomize
                question.optional = fields.optional
                question.dynamic_option_source = fields.dynamic_option_source
                question.other_attributes.update(fields.other_attributes)
            except LLMUnavailable as exc:
                flags.append(
                    ReviewFlag(
                        target_heading=TargetHeading.QUESTIONNAIRE,
                        status=FlagStatus.POSSIBLE_MATCH,
                        candidate_heading=question.id,
                        # The display condition and randomisation flag are in
                        # that cell. Without them the question is incomplete.
                        severity=FlagSeverity.BLOCKING,
                        target=FlagTarget(kind="question", id=question.id),
                        reasoning=f"Inline attributes not split: {exc}",
                    )
                )
        return question

    questions = list(
        await asyncio.gather(
            *(one(index, row) for index, row in enumerate(block.rows))
        )
    )
    return questions, flags


# ---------------------------------------------------------------------------
# Routing — depends on the questionnaire's option codes
# ---------------------------------------------------------------------------

_ROUTING_SYSTEM = """\
You translate a routing condition from a questionnaire into a formal expression.

You are given the condition and the option codes of the questions it references.

Use these operators: ==, !=, IN, NOT IN, CONTAINS_ANY, CONTAINS_ALL, >, <.
Refer to questions by id. Refer to an answer by its CODE where the question has \
codes, otherwise by its exact label in single quotes. Copy codes and labels \
exactly as listed; never emit a placeholder for a code that is not given.

Prose such as "Q1 contains at least one brand" becomes CONTAINS_ANY over the \
option codes that are brands, excluding any "none of these" option.

Return expression null when the condition cannot be resolved from the codes \
given. A wrong expression silently routes real respondents down the wrong path.
"""


async def parse_routing(
    block: Stage3Block | None, questions: list[Question]
) -> tuple[list[RoutingRule], list[ReviewFlag]]:
    if block is None:
        return [], []

    by_id = {q.id: q for q in questions}

    def _render(question: Question) -> str:
        """One catalogue line. A codeless option is listed by label alone —
        writing a placeholder for the missing code invites the model to copy the
        placeholder into the expression."""
        rendered = ", ".join(
            f"{o.code}={o.label}" if o.code else o.label for o in question.options
        )
        has_codes = any(o.code for o in question.options)
        suffix = "" if has_codes else "   (no codes; refer to these by label)"
        return f"{question.id}: {rendered}{suffix}"

    def _catalogue_for(condition: str) -> str:
        """Only the questions this condition actually names.

        Sending every question's options made the prompt scale with the
        questionnaire — on a 31-question QRE it overflowed the completion budget
        and buried the one list that mattered.
        """
        referenced = [
            by_id[qid]
            for qid in dict.fromkeys(_QUESTION_REF.findall(condition))
            if qid in by_id and by_id[qid].options
        ]
        if not referenced:
            return "(the condition names no question with a known option list)"
        return "\n".join(_render(q) for q in referenced)

    flags: list[ReviewFlag] = []

    async def one(index: int, row: dict[str, str]) -> RoutingRule:
        condition = _value(row, "display") or row.get("Condition", "")
        rule = RoutingRule(
            rule=_value(row, "id"),
            condition_raw=condition,
            action=_value(row, "action"),
            destination=_value(row, "destination"),
            source_reference=_source_for(block, index),
        )
        if not condition:
            return rule
        try:
            translated = await complete_async(
                _ROUTING_SYSTEM,
                f"Condition: {condition}\n\nOption codes:\n{_catalogue_for(condition)}",
                LLMRoutingExpression,
            )
            rule.condition_expression = translated.expression
            if translated.expression is not None:
                # A model wrote it, so it is an inference and nothing downstream
                # may treat it as something the QRE stated (CLAUDE.md §14).
                rule.condition_expression_origin = Origin.INFERRED
            if translated.expression is None:
                flags.append(
                    ReviewFlag(
                        target_heading=TargetHeading.ROUTING_AND_TERMINATION,
                        status=FlagStatus.POSSIBLE_MATCH,
                        candidate_heading=rule.rule,
                        # condition_raw still holds what the QRE said, and Part 2
                        # builds the real condition from that, so a missing
                        # expression loses nothing that mattered.
                        severity=FlagSeverity.WARNING,
                        target=FlagTarget(kind="rule", id=rule.rule),
                        reasoning=translated.reasoning,
                    )
                )
        except LLMUnavailable as exc:
            flags.append(
                ReviewFlag(
                    target_heading=TargetHeading.ROUTING_AND_TERMINATION,
                    status=FlagStatus.POSSIBLE_MATCH,
                    candidate_heading=rule.rule,
                    severity=FlagSeverity.WARNING,
                    target=FlagTarget(kind="rule", id=rule.rule),
                    reasoning=f"Condition not translated: {exc}",
                )
            )
        return rule

    rules = list(
        await asyncio.gather(
            *(one(index, row) for index, row in enumerate(block.rows))
        )
    )
    return rules, flags


# ---------------------------------------------------------------------------
# Acceptance test scenarios — JSON already embedded in the cells
# ---------------------------------------------------------------------------


def _identifiers_in(value: object) -> list[str]:
    """Every identifier-shaped token inside a scenario's expected outcome.

    Walks whatever shape the cell held — the QRE writes it as JSON and nothing
    guarantees which keys it uses — and returns the tokens in first-seen order.
    No attempt is made to say which are questions and which are dispositions;
    that needs the questionnaire and the message list, which Stage 5 has.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                walk(key)
                walk(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            for token in _IDENTIFIER.findall(node):
                if token not in found:
                    found.append(token)

    walk(value)
    return found


async def parse_scenarios(
    block: Stage3Block | None,
) -> tuple[list[AcceptanceScenario], list[ReviewFlag]]:
    if block is None:
        return [], []

    scenarios: list[AcceptanceScenario] = []
    flags: list[ReviewFlag] = []

    for index, row in enumerate(block.rows):
        scenario = AcceptanceScenario(
            id=_value(row, "id"),
            purpose=_value(row, "wording"),
            source_reference=_source_for(block, index),
        )
        for role, field in (("inputs", "key_inputs"), ("outcome", "expected_outcome")):
            cell = _value(row, role)
            if not cell:
                continue
            match = _JSON_OBJECT.search(cell)
            if not match:
                scenario.parse_errors.append(f"{role}: no JSON object in {cell!r}")
                continue
            try:
                setattr(scenario, field, json.loads(match.group(0)))
            except json.JSONDecodeError as exc:
                scenario.parse_errors.append(f"{role}: {exc}")

        scenario.input_question_ids = list(scenario.key_inputs)
        scenario.referenced_ids = _identifiers_in(scenario.expected_outcome)
        if scenario.parse_errors:
            flags.append(
                ReviewFlag(
                    target_heading=TargetHeading.ACCEPTANCE_TEST_SCENARIOS,
                    status=FlagStatus.POSSIBLE_MATCH,
                    candidate_heading=scenario.id,
                    severity=FlagSeverity.BLOCKING,
                    target=FlagTarget(kind="scenario", id=scenario.id),
                    reasoning="; ".join(scenario.parse_errors),
                )
            )
        scenarios.append(scenario)

    return scenarios, flags


# ---------------------------------------------------------------------------
# Completion messages
# ---------------------------------------------------------------------------

_CODE_MESSAGE = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*[:\-–]\s*(.+)$")
#: A disposition code on its own, e.g. COMPLETE, TERM_INELIGIBLE.
_CODE_LIKE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


async def parse_messages(
    block: Stage3Block | None,
) -> tuple[list[CompletionMessage], list[ReviewFlag]]:
    if block is None:
        return [], []

    messages: list[CompletionMessage] = []
    flags: list[ReviewFlag] = []

    for index, row in enumerate(block.rows):
        code = row.get("code") or _value(row, "id")
        text = row.get("message") or _value(row, "wording")

        # A single-pair row keyed by the code itself, e.g.
        # {"TERM_INELIGIBLE": "Thank you for your interest."}.
        if (not code or not text) and len(row) == 1:
            only_key, only_value = next(iter(row.items()))
            if _CODE_LIKE.match(only_key.strip()):
                code, text = only_key.strip(), only_value.strip()

        # Or "CODE: message" run together in one cell.
        if not code or not text:
            joined = " ".join(v for v in row.values() if v)
            match = _CODE_MESSAGE.match(joined)
            if match:
                code, text = match.group(1), match.group(2)

        if code and text:
            messages.append(
                CompletionMessage(
                    code=code.strip(),
                    message=text.strip(),
                    source_reference=_source_for(block, index),
                )
            )
        else:
            flags.append(
                ReviewFlag(
                    target_heading=TargetHeading.COMPLETION_MESSAGES,
                    status=FlagStatus.POSSIBLE_MATCH,
                    severity=FlagSeverity.BLOCKING,
                    target=FlagTarget(kind="message", id=str(index)),
                    reasoning=f"Row is not a code/message pair: {row}",
                )
            )

    return messages, flags


# ---------------------------------------------------------------------------
# Prose sections captured as statements — quotas, study spec, programming notes
# ---------------------------------------------------------------------------


async def parse_statements(
    block: Stage3Block | None,
) -> tuple[list[ExtractedStatement], list[ReviewFlag]]:
    """Carry Stage 3's literal prose rows onto typed statements.

    No parsing beyond what Stage 3 already did. A quota line keeps its cells and
    percentages as written; deciding that "North=20%" means a 20 percent target
    on option North is Part 2's job. Part 1's contribution is that the statement
    now exists, is addressable, and knows where it came from — none of which was
    true before, because these sections never reached Stage 3 at all.
    """
    if block is None:
        return [], []

    statements: list[ExtractedStatement] = []
    for index, row in enumerate(block.rows):
        raw = (row.get("raw_text") or "").strip()
        text = (row.get("text") or raw).strip()
        if not text:
            continue
        statements.append(
            ExtractedStatement(
                code=row.get("code") or None,
                label=row.get("label") or None,
                text=text,
                raw_text=raw or text,
                source_reference=_source_for(block, index),
            )
        )
    return statements, []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_async(blocks: list[Stage3Block]) -> tuple[dict, list[ReviewFlag]]:
    by_target = {b.target: b for b in blocks}

    questionnaire_task = asyncio.create_task(
        parse_questionnaire(by_target.get(TargetHeading.QUESTIONNAIRE))
    )

    async def routing_after_questionnaire():
        # The only dependency in the stage: routing needs the option codes the
        # questionnaire task produces, so it awaits that task and nothing else.
        questions, _ = await questionnaire_task
        return await parse_routing(
            by_target.get(TargetHeading.ROUTING_AND_TERMINATION), questions
        )

    (
        (questions, q_flags),
        (routing, r_flags),
        (scenarios, s_flags),
        (messages, m_flags),
        (quotas, quota_flags),
        (study, study_flags),
        (programming, programming_flags),
    ) = await asyncio.gather(
        questionnaire_task,
        routing_after_questionnaire(),
        parse_scenarios(by_target.get(TargetHeading.ACCEPTANCE_TEST_SCENARIOS)),
        parse_messages(by_target.get(TargetHeading.COMPLETION_MESSAGES)),
        parse_statements(by_target.get(TargetHeading.QUOTA_CONTROLS)),
        parse_statements(by_target.get(TargetHeading.STUDY_SPECIFICATION)),
        parse_statements(by_target.get(TargetHeading.PROGRAMMING_AND_QA)),
    )

    return (
        {
            "questions": questions,
            "routing": routing,
            "scenarios": scenarios,
            "messages": messages,
            "quotas": quotas,
            "study": study,
            "programming": programming,
        },
        [
            *q_flags,
            *r_flags,
            *s_flags,
            *m_flags,
            *quota_flags,
            *study_flags,
            *programming_flags,
        ],
    )


def run(blocks: list[Stage3Block]) -> tuple[dict, list[ReviewFlag]]:
    return asyncio.run(run_async(blocks))
