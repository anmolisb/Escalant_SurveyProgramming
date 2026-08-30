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
# The condition parser and its renderer. Deterministic syntax reading with no
# Part 2 semantics in it, so using it here does not move interpretation
# earlier - it is what decides that a condition needs no interpreting at all.
import part2_conditions
from models import (
    AcceptanceScenario,
    CompletionMessage,
    ExtractedStatement,
    FlagSeverity,
    FlagStatus,
    FlagTarget,
    Condition,
    ConditionOp,
    DirectiveKind,
    LLMComparisonOp,
    LLMQuestionFields,
    LLMRoutingExpression,
    Operand,
    Option,
    Origin,
    Paragraph,
    Question,
    ReviewFlag,
    RoutingRule,
    SourceReference,
    Stage3Block,
    SurveyInformation,
    TargetHeading,
)

# ---------------------------------------------------------------------------
# Column resolution — the source names its columns, we find them by keyword
# ---------------------------------------------------------------------------

#: What a column called by some name is likely to hold. Names are the QRE's own
#: convention, so these are guesses ranked by fit, never a required vocabulary.
#:
#: Split by table because the same word means different things in each. A column
#: headed "Rule" is the identifier of a routing rule, but in a questionnaire a
#: column headed "Gating rule" is the condition for showing a question - reading
#: the second as an identifier is how Z01 ended up with every question id set to
#: "everyone".
_QUESTION_HINTS = {
    "id": ("id", "qid", "code", "number", "no", "item", "ref", "marker", "label"),
    "wording": ("wording", "question", "text", "instruction", "verbatim", "stem"),
    "type": ("type", "format", "kind", "mode", "capture"),
    "options": ("option", "scale", "codeframe", "answer", "response", "reply", "choice"),
    "display": ("display", "validation", "condition", "base", "logic", "gating", "rule", "show"),
}

_ROUTING_HINTS = {
    "id": ("rule", "id", "ref", "no", "number"),
    "display": ("condition", "display", "logic", "when", "base", "if"),
    "action": ("action", "do", "effect"),
    "destination": ("destination", "target", "go to", "goto", "then", "jump"),
}

_SCENARIO_HINTS = {
    "id": ("id", "ref", "no", "number", "case", "test"),
    "wording": ("purpose", "description", "name", "scenario", "objective"),
    "inputs": ("input", "given", "answer"),
    "outcome": ("outcome", "expected", "result"),
}

#: Kept for anything still reading the old name.
_COLUMN_HINTS = _QUESTION_HINTS


def _words(name: str) -> list[str]:
    """Split a column name into comparable words."""
    return [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]


def _stem(word: str) -> str:
    """Crude singular. "options" and "option" should match; "notes" and "no"
    should not."""
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es"):
        return word[:-2]
    if len(word) > 2 and word.endswith("s"):
        return word[:-1]
    return word


def _hint_score(name: str, hint: str) -> int:
    """How well a column name fits one hint. Zero means it does not.

    Whole words only. Substring matching is what made "no" match "Scripter
    notes" and "rule" match "Gating rule", so a column of scripting notes became
    the question id and every id was lost.
    """
    words = _words(name)
    if not words:
        return 0
    hint_words = _words(hint)
    if len(hint_words) > 1:
        # A multi-word hint such as "go to" only counts if it appears in order.
        joined = " ".join(words)
        return 40 if " ".join(hint_words) in joined else 0
    hint_word = hint_words[0]
    for position, word in enumerate(words):
        if word == hint_word or _stem(word) == _stem(hint_word):
            # A one-word column named exactly after the hint is the clearest
            # signal there is; earlier words beat later ones.
            score = 50 if len(words) == 1 else 30
            return score - position
    return 0


def _resolve_columns(row: dict[str, str], hints: dict) -> dict[str, str]:
    """Decide which column serves which role, one column per role.

    Every role is scored against every column and the strongest pairings are
    taken first. Without this, roles were filled in dictionary order and the
    first passable column won: in Z02 the column headed "Answer Type" was taken
    as the answer options, so the real codeframe was never read and every
    question came out with its type as its only option.
    """
    candidates = []
    for role, role_hints in hints.items():
        for name in row:
            best = max((_hint_score(name, h) for h in role_hints), default=0)
            if best > 0:
                candidates.append((best, role, name))
    candidates.sort(key=lambda c: -c[0])

    resolved: dict[str, str] = {}
    taken: set[str] = set()
    for _score, role, name in candidates:
        if role in resolved or name in taken:
            continue
        resolved[role] = name
        taken.add(name)
    return resolved


def _find_column(row: dict[str, str], role: str, hints: dict | None = None) -> str | None:
    """Return the column serving this role, or None."""
    return _resolve_columns(row, hints or _QUESTION_HINTS).get(role)


def _value(row: dict[str, str], role: str, hints: dict | None = None) -> str:
    key = _find_column(row, role, hints)
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
#: "cols" is Z02's own abbreviation for "columns", which is itself only ever
#: the scale in this pipeline's two-part rows/scale model. Kept as a fixed set
#: rather than a stemming rule, since an abbreviation cannot be derived from
#: the word it stands for the way a plural can.
_MATRIX_PART = re.compile(
    r"^\s*(rows?|scale|columns?|cols?)\s*:\s*(.*)$", re.IGNORECASE
)
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
You read the instructions written in one questionnaire cell and label each one.

The cell holds instructions on separate lines, for example:
    Show if: Q5 == 'Yes'
    Validate: {"min_length": 10}
    Randomize
    Show only brands selected at Q1.

Return one entry per instruction, with its kind and its text. Read every line; \
a cell often holds several instructions of different kinds, and one kind can \
appear more than once.

Kinds:
  always_show        the question is shown to everyone
  display_condition  when the question is shown; text is the condition alone,
                     without the leading "Show if:"
  validation         a constraint on the answer, usually carrying JSON
  randomize          options or rows are shuffled
  option_source      the answer list is narrowed to an earlier answer,
                     e.g. "Show only brands selected at Q1."
  optional           an answer is not required
  mandatory          an answer is required
  other              an instruction that is none of the above

Copy text exactly, minus only the leading keyword and its colon. Never reword, \
never merge two instructions into one entry, and never invent an instruction \
the cell does not state.
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
    """Return (rows, scale) for "Rows: … / Scale: …" notation.

    A QRE writes the two parts as separate lines, or joined on one line with
    "||" — "ROWS: Staff; Stock || COLS: 1=Poor; 2=OK". Splitting only on the
    newline read the second form as one blob, so the last row swallowed the
    whole scale and the scale's own values fell apart at their commas. Each
    part is matched by its own leading keyword regardless of how the QRE joined
    them, so both forms read the same way rather than favouring the one the
    sample fixtures happen to use.
    """
    rows: list[Option] = []
    scale: list[Option] = []
    for line in re.split(r"\n|\|\|", text):
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


def _apply_directives(
    question: Question, fields: LLMQuestionFields
) -> list[ReviewFlag]:
    """Group one cell's labelled instructions onto the question's fields.

    Validation keeps being read from its JSON by `_apply_validation` rather than
    from the label: the payload is machine-readable already, and a model reading
    it back would be a chance to change a number for nothing.
    """
    flags: list[ReviewFlag] = []
    conditions = [
        d.text.strip()
        for d in fields.directives
        if d.kind is DirectiveKind.DISPLAY_CONDITION and d.text.strip()
    ]
    if conditions:
        if len(conditions) > 1:
            # Two guards on one question. Joining them with "and" is the reading
            # every survey tool takes, but it is still a reading, so it is said
            # out loud rather than done quietly.
            flags.append(
                ReviewFlag(
                    target_heading=TargetHeading.QUESTIONNAIRE,
                    status=FlagStatus.POSSIBLE_MATCH,
                    candidate_heading=question.id,
                    severity=FlagSeverity.WARNING,
                    target=FlagTarget(kind="question", id=question.id),
                    reasoning=(
                        f"The cell states {len(conditions)} display conditions "
                        "and does not say how they combine; they are being read "
                        "as all having to hold."
                    ),
                )
            )
        question.display_condition = " and ".join(conditions)

    for directive in fields.directives:
        text = directive.text.strip()
        if directive.kind is DirectiveKind.RANDOMIZE:
            question.randomize = True
        elif directive.kind is DirectiveKind.OPTIONAL:
            question.optional = True
        elif directive.kind is DirectiveKind.MANDATORY:
            question.optional = False
        elif directive.kind is DirectiveKind.OPTION_SOURCE:
            question.dynamic_option_source = text
        elif directive.kind is DirectiveKind.OTHER and text:
            # Kept under the kind that was read, so a reader can tell an
            # unclassified instruction from a recognised one (CLAUDE.md §16).
            question.other_attributes.setdefault("other_instructions", []).append(text)
    return flags


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
                flags.extend(_apply_directives(question, fields))
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

    # Second pass. A display condition names other questions - "Q1 contains at
    # least one brand" needs Q1's options - and the first pass parses every
    # question at once, so no question can see another's answer list while it
    # runs. Resolving here, once they all exist, is the same dependency routing
    # already has, kept inside this function rather than made someone else's.
    by_id = {q.id: q for q in questions if q.id}

    async def normalise(question: Question) -> None:
        expression, origin, refusal = await _resolve_condition(
            question.display_condition or "", by_id
        )
        question.display_condition_expression = expression
        question.display_condition_expression_origin = origin
        if refusal:
            flags.append(
                ReviewFlag(
                    target_heading=TargetHeading.QUESTIONNAIRE,
                    status=FlagStatus.POSSIBLE_MATCH,
                    candidate_heading=question.id,
                    # The condition is still there in `display_condition`, and
                    # Part 2 builds its guard from that, so an unresolved
                    # expression costs the reader convenience, not the fact.
                    severity=FlagSeverity.WARNING,
                    target=FlagTarget(kind="question", id=question.id),
                    reasoning=refusal,
                )
            )

    await asyncio.gather(
        *(normalise(q) for q in questions if q.display_condition)
    )
    return questions, flags


# ---------------------------------------------------------------------------
# Routing — depends on the questionnaire's option codes
# ---------------------------------------------------------------------------

#: Says nothing about syntax, because the model no longer writes any. It reports
#: which question, which operator and which values; this codebase writes the
#: expression from that (`part2_conditions.render`).
_ROUTING_SYSTEM = """\
You break a routing condition from a questionnaire into its comparisons.

You are given the condition and the option codes of the questions it references.

For each comparison report the question id, the operator, and the values.
Use a value's CODE where the question has codes, otherwise its exact label. \
Copy codes and labels exactly as listed; never invent one that is not given.

Operators:
  eq / ne              the answer is, or is not, the single value
  set_eq               the answer set is exactly these values and nothing else
  contains_any         at least one of these values is among the answers
  contains_all         all of these values are among the answers
  in / not_in          the answer is, or is not, one of these values
  lt / le / gt / ge    numeric comparison
  answered/unanswered  whether the question was put to the respondent at all

Prose such as "Q1 contains at least one brand" is contains_any over the option \
codes that are brands, excluding any "none of these" option.

Where a condition compares two answers rather than an answer and a value - \
"selected option at Q6 was not selected at Q5" - set compare_to_question to the \
other question and leave values empty.

Where the condition has more than one comparison, set joiner to how they \
combine. Where it has one, leave joiner null.

Return no comparisons at all when the condition cannot be resolved from the \
codes given. A wrong condition silently routes real respondents down the wrong \
path, and saying so costs only a review.
"""


#: Comparison operators, as the model names them, mapped onto the closed set the
#: condition tree uses. Same names, so this is a lookup rather than a
#: translation, but it is written out so an operator can never reach the tree
#: without passing through it.
_LLM_OPS = {op.value: ConditionOp(op.value) for op in LLMComparisonOp}


def _condition_from(answer: LLMRoutingExpression) -> Condition | None:
    """Build a condition tree from what the model reported, or refuse.

    The model supplies parts; the shape is decided here. Nothing it returns is
    a string of syntax any more, so there is no syntax to vary and no regex
    needed to read it back.
    """
    if not answer.comparisons:
        return None

    built: list[Condition] = []
    for comparison in answer.comparisons:
        op = _LLM_OPS.get(comparison.operator.value)
        if op is None:
            return None
        left = Operand(question_id=comparison.question_id)
        if op in (ConditionOp.ANSWERED, ConditionOp.UNANSWERED):
            built.append(Condition(op=op, left=left))
            continue
        if comparison.compare_to_question:
            # Comparing two answers rather than an answer and a value.
            built.append(
                Condition(
                    op=op,
                    left=left,
                    right=Operand(question_id=comparison.compare_to_question),
                )
            )
            continue
        if not comparison.values:
            return None
        if op in (ConditionOp.EQ, ConditionOp.NE, ConditionOp.LT, ConditionOp.LE,
                  ConditionOp.GT, ConditionOp.GE):
            # A single-value operator handed several values is a contradiction,
            # not something to resolve by picking one.
            if len(comparison.values) != 1:
                return None
            right = Operand(text=comparison.values[0])
        else:
            right = Operand(values=list(comparison.values))
        built.append(Condition(op=op, left=left, right=right))

    if len(built) == 1:
        return built[0]
    if answer.joiner not in ("and", "or"):
        # Several comparisons and nothing saying how they combine. Reading that
        # as "and" would be a guess about which respondents are routed.
        return None
    return Condition(op=ConditionOp(answer.joiner), operands=built)


def _catalogue_line(question: Question) -> str:
    """One catalogue line. A codeless option is listed by label alone - writing
    a placeholder for the missing code invites the model to copy the placeholder
    into the expression."""
    rendered = ", ".join(
        f"{o.code}={o.label}" if o.code else o.label for o in question.options
    )
    has_codes = any(o.code for o in question.options)
    suffix = "" if has_codes else "   (no codes; refer to these by label)"
    return f"{question.id}: {rendered}{suffix}"


def _catalogue_for(condition: str, by_id: dict[str, Question]) -> str:
    """Only the questions this condition actually names.

    Sending every question's options made the prompt scale with the
    questionnaire - on a 31-question QRE it overflowed the completion budget and
    buried the one list that mattered.
    """
    referenced = [
        by_id[qid]
        for qid in dict.fromkeys(_QUESTION_REF.findall(condition))
        if qid in by_id and by_id[qid].options
    ]
    if not referenced:
        return "(the condition names no question with a known option list)"
    return "\n".join(_catalogue_line(q) for q in referenced)


async def _resolve_condition(
    condition: str, by_id: dict[str, Question]
) -> tuple[str | None, Origin | None, str | None]:
    """Read one condition into the canonical grammar.

    The single path for every condition in the document, whichever column it was
    written in. C02 states the guard on Q2 twice - the questionnaire writes
    "Q1 contains at least one brand" and the routing table writes it formally -
    and before this only the routing one came out parseable, so anything reading
    the artifact needed the routing table as a first choice and the
    questionnaire as a fallback, with nothing keeping the two in agreement.
    Running both through here means the same sentence produces the same string
    no matter which column it appeared in.

    Returns (expression, origin, refusal reason). Every element is None where
    there is nothing to read.
    """
    if not condition or not condition.strip():
        return None, None, None

    # Already formal: the QRE wrote the grammar itself, so no model is needed
    # and none is asked.
    parsed = part2_conditions.parse(condition)
    if parsed is not None:
        return part2_conditions.render(parsed), Origin.DERIVED, None

    try:
        answer = await complete_async(
            _ROUTING_SYSTEM,
            f"Condition: {condition}\n\nOption codes:\n{_catalogue_for(condition, by_id)}",
            LLMRoutingExpression,
        )
    except LLMUnavailable as exc:
        return None, None, f"Condition not translated: {exc}"

    tree = _condition_from(answer)
    expression = part2_conditions.render(tree) if tree is not None else None
    if expression is None:
        return (
            None,
            None,
            answer.reasoning
            if not answer.comparisons
            else f"The comparisons reported do not form a condition: {answer.reasoning}",
        )
    # A model decided the reading, so it is an inference and nothing downstream
    # may treat it as something the QRE stated (CLAUDE.md §14).
    return expression, Origin.INFERRED, None


async def parse_routing(
    block: Stage3Block | None, questions: list[Question]
) -> tuple[list[RoutingRule], list[ReviewFlag]]:
    if block is None:
        return [], []

    by_id = {q.id: q for q in questions}
    flags: list[ReviewFlag] = []

    async def one(index: int, row: dict[str, str]) -> RoutingRule:
        condition = _value(row, "display", _ROUTING_HINTS) or row.get("Condition", "")
        rule = RoutingRule(
            rule=_value(row, "id", _ROUTING_HINTS),
            condition_raw=condition,
            action=_value(row, "action", _ROUTING_HINTS),
            destination=_value(row, "destination", _ROUTING_HINTS),
            source_reference=_source_for(block, index),
        )
        if not condition:
            return rule

        expression, origin, refusal = await _resolve_condition(condition, by_id)
        rule.condition_expression = expression
        rule.condition_expression_origin = origin
        if refusal:
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
                    reasoning=refusal,
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
            id=_value(row, "id", _SCENARIO_HINTS),
            purpose=_value(row, "wording", _SCENARIO_HINTS),
            source_reference=_source_for(block, index),
        )
        for role, field in (("inputs", "key_inputs"), ("outcome", "expected_outcome")):
            cell = _value(row, role, _SCENARIO_HINTS)
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


# ---------------------------------------------------------------------------
# Survey information — the headings the survey itself is presented under
# ---------------------------------------------------------------------------

#: Labels a QRE might use for each heading, best first. The first group states
#: the thing outright; the second is a near neighbour being read as the thing,
#: which is a judgement and so raises a flag saying what was read as what.
_INFORMATION_LABELS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "qre_id": (
        ("qre id", "qre reference", "study id", "project id", "project number",
         "job number", "reference"),
        (),
    ),
    "title": (
        ("title", "survey title", "study title", "project title", "survey name",
         "study name", "project name"),
        (),
    ),
    "description": (
        ("description", "survey description", "study description", "summary",
         "overview"),
        ("business objective", "objective", "purpose", "research objective"),
    ),
    "welcome_text": (
        ("welcome text", "welcome message", "welcome", "intro text",
         "introduction", "intro", "opening text", "landing text", "splash text"),
        (),
    ),
}

#: "S01 • SIMPLE", "C02 - COMPLEX", "M03". The id is the leading token; whatever
#: follows it is the corpus's own difficulty tag, not part of the id.
_FRONT_ID = re.compile(r"^\s*([A-Za-z]{1,4}\d{1,3})\b")

#: The line naming the genre of the document. Every fixture writes it and it is
#: never the survey's title, so it is skipped rather than read as one.
_BOILERPLATE = re.compile(
    r"questionnaire\s+requirement\s+document|^\s*\(?qre\)?\s*$", re.I
)


def _labelled(
    statements: list[ExtractedStatement], aliases: tuple[str, ...]
) -> ExtractedStatement | None:
    """The first statement whose label is one of `aliases`, in preference order."""
    for alias in aliases:
        for statement in statements:
            if (statement.label or "").strip().lower() == alias:
                return statement
    return None


def parse_survey(
    source: str, front_matter: list[Paragraph], study: list[ExtractedStatement]
) -> tuple[SurveyInformation, list[ReviewFlag]]:
    """Read the survey's headings out of the document.

    Two places, in order. A labelled line in the study specification wins,
    because a QRE writing "Title: X" has stated its title and there is nothing
    to work out. Failing that the front matter is read positionally: the id is
    the leading token of the first line that starts with one, and the title is
    the first line left once that line and the "Questionnaire Requirement
    Document" boilerplate are set aside.

    Anything neither place supplies stays None and raises a flag naming the
    field, so what still needs a person is listed rather than left to be
    noticed. Nothing is defaulted (CLAUDE.md §30).
    """
    information = SurveyInformation(source_file=source)
    flags: list[ReviewFlag] = []

    def flag(severity: FlagSeverity, field: str, reasoning: str) -> None:
        flags.append(
            ReviewFlag(
                target_heading=TargetHeading.STUDY_SPECIFICATION,
                status=FlagStatus.NOT_PRESENT,
                severity=severity,
                target=FlagTarget(kind="survey_information", id=field),
                reasoning=reasoning,
            )
        )

    # --- the front matter, read positionally --------------------------------
    spare: list[str] = []
    for paragraph in front_matter:
        line = paragraph.text.strip()
        if not line or _BOILERPLATE.search(line):
            continue
        match = _FRONT_ID.match(line)
        if match and information.qre_id is None:
            information.qre_id = match.group(1)
            # "S01 • SIMPLE" is an id and a tag, nothing more; but a line like
            # "C02 Automotive Purchase Journey" carries the title too, so what
            # follows the id is kept as a candidate rather than discarded.
            remainder = line[match.end() :].strip(" •-–—:|")
            if len(remainder.split()) > 1:
                spare.append(remainder)
            continue
        spare.append(line)

    if spare:
        information.title = spare[0]

    # --- a labelled line beats anything read off the cover page --------------
    for field in ("qre_id", "title", "description", "welcome_text"):
        stated, near = _INFORMATION_LABELS[field]
        statement = _labelled(study, stated)
        if statement is None:
            statement = _labelled(study, near)
            if statement is not None:
                # Reading an objective as a description is a judgement, so say
                # which line was read as what rather than presenting it as
                # something the QRE labelled (CLAUDE.md §14).
                flag(
                    FlagSeverity.INFO,
                    field,
                    f"No line is labelled as the survey {field.replace('_', ' ')}; "
                    f"the line labelled {statement.label!r} is being read as it.",
                )
        if statement is not None and statement.text.strip():
            setattr(information, field, statement.text.strip())

    # --- the id, last of all, from the filename ------------------------------
    if information.qre_id is None:
        match = _FRONT_ID.match(source)
        if match:
            information.qre_id = match.group(1)
            flag(
                FlagSeverity.INFO,
                "qre_id",
                "No line in the document states a study id; it is taken from "
                f"the filename, which is a convention rather than a statement.",
            )

    for field, why in (
        ("qre_id", "no line and no filename supplies one"),
        ("title", "the document has no titled line above its first heading"),
        ("description", "no line is labelled as a description or an objective"),
        ("welcome_text", "the document never states what a respondent is shown "
                         "before the first question"),
    ):
        if getattr(information, field) is None:
            flag(
                FlagSeverity.WARNING,
                field,
                f"The survey's {field.replace('_', ' ')} is not stated: {why}.",
            )
    return information, flags


async def run_async(
    blocks: list[Stage3Block], source: str, front_matter: list[Paragraph]
) -> tuple[dict, list[ReviewFlag]]:
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

    # Read after the gather because a labelled line in the study
    # specification outranks anything on the cover page.
    information, info_flags = parse_survey(source, front_matter, study)

    return (
        {
            "survey": information,
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
            *info_flags,
        ],
    )


def run(
    blocks: list[Stage3Block], source: str, front_matter: list[Paragraph]
) -> tuple[dict, list[ReviewFlag]]:
    return asyncio.run(run_async(blocks, source, front_matter))
