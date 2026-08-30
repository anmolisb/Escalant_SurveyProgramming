"""Part 2 — reading a routing condition as a tree rather than a string.

This is where Agent 1 stops recording what the QRE said and starts working out
what it means. CLAUDE.md draws the line here: Part 1 preserves
"Show if: Q5 contains any touchpoint" as text, Part 2 decides that the operator
is contains_any.

Built from `RoutingRule.condition_raw`, which is verbatim source text. Never
from `condition_expression`, which a model wrote and which changed meaning on
two of C02's twenty rules.

Deterministic first. Most conditions in the corpus are already formal — the QRE
writes `S1 == 'No'` and `Q12 in ['Fully','Partly']` itself — and parsing those
needs no model, costs no rate limit, and gives the same answer every run. What
is left is genuine prose, such as "exclusive option selected with another
response at Q1 or Q5", and only that goes to a model.

The parser refuses rather than guesses. A condition it cannot read returns None
and becomes a review finding, because a wrong condition silently routes real
respondents down the wrong path, while an unread one merely asks a human.
"""

from __future__ import annotations

import re

from llm import LLMUnavailable, complete
from models import (
    Aggregate,
    Condition,
    ConditionOp,
    LLMConditionProposal,
    Operand,
    Origin,
)

#: A question id: S1, Q12, D4, A_2. Kept loose because ids are the QRE's
#: convention, not ours.
_QID = r"[A-Za-z]{1,4}_?\d+"

#: Every operator is infix: question, operator, value. One shape for all of
#: them, so a reader - or a regex - finds the question on the left of any
#: condition without having to know which operator it uses. Membership used to
#: be written as a call, `contains_any(Q1, [...])`, which put the question
#: inside the parentheses and made it the one comparison needing its own rule.
#:
#: Longest first, so "!=" is not read as "=", "not in" is not read as "in", and
#: "contains_any" is not read as "contains".
_OPERATORS: list[tuple[str, ConditionOp]] = [
    ("!=", ConditionOp.NE),
    ("==", ConditionOp.EQ),
    ("<=", ConditionOp.LE),
    (">=", ConditionOp.GE),
    ("=", ConditionOp.EQ),
    ("<", ConditionOp.LT),
    (">", ConditionOp.GT),
    (" not in ", ConditionOp.NOT_IN),
    (" in ", ConditionOp.IN),
    (" contains_any ", ConditionOp.CONTAINS_ANY),
    (" contains_all ", ConditionOp.CONTAINS_ALL),
    (" contains ", ConditionOp.CONTAINS),
]

#: Operators taking no value: "Q3 answered". Still question-first, so the same
#: reading applies. "unanswered" is listed first only for clarity; it cannot be
#: mistaken for "answered", which needs a space in front of it.
_POSTFIX = re.compile(r"^(.*?)\s+(unanswered|answered)\s*$", re.I)
_POSTFIX_OPS = {
    "answered": ConditionOp.ANSWERED,
    "unanswered": ConditionOp.UNANSWERED,
}

#: "sum(Q18)" or "count(Q5)".
_AGGREGATE = re.compile(r"^\s*(sum|count)\s*\(\s*(" + _QID + r")\s*\)\s*$", re.I)
_BARE_REF = re.compile(r"^\s*(" + _QID + r")\s*$")
_NUMBER = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*$")
_QUOTED = re.compile(r"^\s*['\"](.*)['\"]\s*$", re.S)
_LIST = re.compile(r"^\s*\[(.*)\]\s*$", re.S)
#: Top-level "and" / "or". Word-bounded so "brand" is not read as containing
#: "and".
_BOOLEAN = re.compile(r"\s+(and|or)\s+", re.I)


def _split_list(inner: str) -> list[str]:
    """Split a list literal's contents, honouring quotes.

    Written by hand rather than with json.loads because the QRE writes single
    quotes, which JSON rejects, and because an unquoted bare word inside a list
    is still meaningful.
    """
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in inner:
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
        elif char in "'\"":
            quote = char
        elif char == ",":
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current or items:
        items.append("".join(current).strip())
    return [i for i in items if i]


def _operand(text: str) -> Operand | None:
    """Read one side of a comparison, or refuse."""
    text = text.strip()
    if not text:
        return None

    match = _AGGREGATE.match(text)
    if match:
        return Operand(
            question_id=match.group(2),
            aggregate=Aggregate(match.group(1).lower()),
        )

    match = _BARE_REF.match(text)
    if match:
        return Operand(question_id=match.group(1))

    match = _LIST.match(text)
    if match:
        values = _split_list(match.group(1))
        return Operand(values=values) if values else None

    match = _QUOTED.match(text)
    if match:
        return Operand(text=match.group(1))

    if _NUMBER.match(text):
        return Operand(number=float(text))

    return None


def _split_top_level(text: str) -> list[str] | None:
    """Split on and / or, but only outside quotes and brackets.

    Without the depth check, "Q12 in ['Fully','Partly'] and Q3 == 'x'" would
    split inside the list if a value ever contained the word.
    """
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif depth == 0:
            match = _BOOLEAN.match(text, index)
            if match:
                parts.append(text[start : index])
                parts.append(match.group(1).lower())
                index = match.end()
                start = index
                continue
        index += 1
    parts.append(text[start:])
    return parts if len(parts) > 1 else None


def _comparison(text: str) -> Condition | None:
    """Read a single comparison, or refuse."""
    postfix = _POSTFIX.match(text)
    if postfix:
        left = _operand(postfix.group(1))
        if left is not None and left.question_id is not None:
            return Condition(
                op=_POSTFIX_OPS[postfix.group(2).lower()],
                left=left,
                source_text=text.strip(),
            )

    for token, op in _OPERATORS:
        # Search rather than split, so only the first operator counts and a
        # value containing "=" does not confuse things. Word operators are
        # matched case-insensitively; testing for letters rather than for
        # `isalpha` because "contains_any" holds an underscore and so would
        # have been compared case-sensitively.
        word = any(character.isalpha() for character in token)
        position = text.lower().find(token) if word else text.find(token)
        if position <= 0:
            continue
        left = _operand(text[:position])
        right = _operand(text[position + len(token) :])
        if left is None or right is None:
            continue
        if left.question_id is None:
            continue  # the left side must name a question
        # "Q1 == ['None of these']" is a claim about the whole answer set, not
        # about one value. Losing that is exactly what went wrong with R5.
        if op is ConditionOp.EQ and right.values is not None:
            op = ConditionOp.SET_EQ
        elif op is ConditionOp.NE and right.values is not None:
            return Condition(
                op=ConditionOp.NOT,
                operands=[
                    Condition(
                        op=ConditionOp.SET_EQ,
                        left=left,
                        right=right,
                        source_text=text.strip(),
                    )
                ],
                source_text=text.strip(),
            )
        if (
            op in (ConditionOp.CONTAINS_ANY, ConditionOp.CONTAINS_ALL, ConditionOp.IN,
                   ConditionOp.NOT_IN)
            and right.values is None
            and right.text is not None
        ):
            # A lone value handed to a set operator is still a set of one.
            right = Operand(values=[right.text])
        return Condition(op=op, left=left, right=right, source_text=text.strip())
    return None


def _term(text: str) -> Condition | None:
    """One piece of an expression: a negation, a bracketed group, or a
    comparison."""
    text = text.strip()
    if not text:
        return None

    if text.lower().startswith("not ") or text.lower().startswith("not("):
        inner = _term(text[3:].strip())
        return (
            Condition(op=ConditionOp.NOT, operands=[inner], source_text=text)
            if inner
            else None
        )

    if text.startswith("(") and text.endswith(")"):
        depth = 0
        wraps = True
        for index, char in enumerate(text):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index < len(text) - 1:
                    wraps = False
                    break
        if wraps:
            return parse(text[1:-1])

    return _comparison(text)


def parse(condition_raw: str) -> Condition | None:
    """Read a condition into a tree, or return None if it is not formal.

    None means "this needs a model", not "this is fine". The caller records a
    finding either way, so an unread condition is visible rather than silently
    absent.
    """
    text = (condition_raw or "").strip()
    if not text:
        return None

    parts = _split_top_level(text)
    if parts:
        operands: list[Condition] = []
        connectors: set[str] = set()
        for part in parts:
            if part in ("and", "or"):
                connectors.add(part)
                continue
            child = _term(part)
            if child is None:
                return None
            operands.append(child)
        # Mixed and/or without brackets is genuinely ambiguous; refuse rather
        # than pick a precedence the QRE never stated.
        if len(connectors) != 1 or len(operands) < 2:
            return None
        op = ConditionOp.AND if connectors == {"and"} else ConditionOp.OR
        return Condition(
            op=op, operands=operands, source_text=text, origin=Origin.DERIVED
        )

    condition = _term(text)
    if condition is not None:
        condition.source_text = text
        condition.origin = Origin.DERIVED
    return condition


#: The one way each operator is written. `describe` renders for a human and
#: names the operator in words; this renders for a machine, and every string it
#: produces must read back through `parse` as the same condition.
_RENDER_SYMBOL = {
    ConditionOp.EQ: "==",
    ConditionOp.NE: "!=",
    ConditionOp.LT: "<",
    ConditionOp.LE: "<=",
    ConditionOp.GT: ">",
    ConditionOp.GE: ">=",
    ConditionOp.IN: "in",
    ConditionOp.NOT_IN: "not in",
    #: A claim about the whole answer set, written as equality against a list -
    #: which is the form `parse` reads back as SET_EQ.
    ConditionOp.SET_EQ: "==",
    ConditionOp.CONTAINS: "contains",
    ConditionOp.CONTAINS_ANY: "contains_any",
    ConditionOp.CONTAINS_ALL: "contains_all",
}

#: Operators with nothing on the right: "Q3 answered".
_RENDER_POSTFIX = {
    ConditionOp.ANSWERED: "answered",
    ConditionOp.UNANSWERED: "unanswered",
}


def _render_value(value: str) -> str:
    """Quote one value. Double quotes where the value itself has an apostrophe.

    The list splitter honours whichever quote opened the value and has no escape
    character, so a label like "Don't know" has to be quoted the other way round
    or it would terminate halfway through.
    """
    return f'"{value}"' if "'" in value else f"'{value}'"


def _render_operand(operand: Operand | None) -> str | None:
    if operand is None:
        return None
    if operand.question_id:
        return (
            f"{operand.aggregate.value}({operand.question_id})"
            if operand.aggregate
            else operand.question_id
        )
    if operand.values is not None:
        return "[" + ", ".join(_render_value(v) for v in operand.values) + "]"
    if operand.number is not None:
        number = operand.number
        return str(int(number)) if float(number).is_integer() else str(number)
    if operand.text is not None:
        return _render_value(operand.text)
    return None


def render(condition: Condition) -> str | None:
    """Write a condition in the one canonical form, or refuse.

    The point of this is that there is exactly one, and that it is the same
    shape for every operator: the question, then the operator, then the value.
    A reader that has found the question on the left of `Q1 == 'x'` finds it in
    the same place on `Q1 contains_any ['x','y']`.

    Stage 4's expression used to be whatever text a model happened to produce,
    so one document held `CONTAINS_ANY(Q1, 'a', 'b')`, `Q1 CONTAINS_ANY
    ('a','b')` and `CONTAINS_ANY(Q1, ['a','b'])` for a single operator, each
    needing its own rule downstream. Rendering from the tree means the shape
    cannot vary: it is produced by this function or it is not produced at all.

    Returns None rather than a partial string where any piece cannot be
    rendered, so a caller never receives something half-formed that happens to
    look valid.
    """
    if condition.op in (ConditionOp.AND, ConditionOp.OR):
        parts = [render(child) for child in condition.operands]
        if not parts or any(part is None for part in parts):
            return None
        return "(" + f" {condition.op.value} ".join(parts) + ")"

    if condition.op is ConditionOp.NOT:
        if len(condition.operands) != 1:
            return None
        inner = render(condition.operands[0])
        return None if inner is None else f"not ({inner})"

    left = _render_operand(condition.left)
    if left is None:
        return None

    postfix = _RENDER_POSTFIX.get(condition.op)
    if postfix:
        return f"{left} {postfix}"

    symbol = _RENDER_SYMBOL.get(condition.op)
    right = _render_operand(condition.right)
    if symbol is None or right is None:
        return None
    return f"{left} {symbol} {right}"


def describe(condition: Condition) -> str:
    """Render a condition back to readable text.

    Used to show a reviewer what was understood, so a wrong reading can be
    spotted without reading JSON.
    """

    def operand(value: Operand | None) -> str:
        if value is None:
            return "?"
        if value.question_id:
            return (
                f"{value.aggregate.value}({value.question_id})"
                if value.aggregate
                else value.question_id
            )
        if value.values is not None:
            return "[" + ", ".join(repr(v) for v in value.values) + "]"
        if value.number is not None:
            number = value.number
            return str(int(number)) if number == int(number) else str(number)
        return repr(value.text)

    if condition.op in (ConditionOp.AND, ConditionOp.OR):
        joiner = f" {condition.op.value} "
        return "(" + joiner.join(describe(c) for c in condition.operands) + ")"
    if condition.op is ConditionOp.NOT:
        return "not " + describe(condition.operands[0])
    if condition.op in (ConditionOp.ANSWERED, ConditionOp.UNANSWERED):
        return f"{condition.op.value}({operand(condition.left)})"
    return f"{operand(condition.left)} {condition.op.value} {operand(condition.right)}"


# ---------------------------------------------------------------------------
# Prose conditions: the model proposes, the parser decides
# ---------------------------------------------------------------------------

_GRAMMAR = """Write the condition using ONLY this grammar. Anything else is rejected.

  comparison   Q3 != 'None/currently not using'
               Q12 in ['Fully','Partly']
               S3 < 18
               sum(Q18) != 100
  set is exactly
               Q1 == ['None of these']
  membership   Q5 contains 'Dealer visit'
               Q1 contains_any ['Auto Brand A','Auto Brand B']
               Q1 contains_all ['Auto Brand A','Auto Brand B']
               Q5 contains Q6
  asked or not Q3 answered       Q3 unanswered
  combining    A and B           A or B           not A
               (A and B) or (C and D)

Every operator is written the same way: the question, the operator, then the
value. Never put the question inside brackets.

Refer to questions by the ids given. Refer to answers by their exact label in
single quotes, copied from the option list. Never invent a label or an id.

Two operators are easy to confuse and mean different things:
  Q1 == ['None of these']       the answer set is EXACTLY that, nothing else
  Q1 contains 'None of these'   that was chosen, possibly among others
"""

_PROPOSE_SYSTEM = """You rewrite one routing condition from a questionnaire into a formal expression.

You are given the condition as the document wrote it, and the answer options of
the questions it names.

""" + _GRAMMAR + """
Return expression null when the condition cannot be written in this grammar from
what you were given, or when you are unsure which answers it means. A wrong
expression silently routes real respondents down the wrong path; a null one only
asks a person to look.
"""


def _catalogue(question_ids: list[str], options_by_question: dict) -> str:
    lines = []
    for qid in question_ids:
        options = options_by_question.get(qid) or []
        if options:
            lines.append(f"{qid}: " + ", ".join(repr(o) for o in options))
    return "\n".join(lines) if lines else "(no option lists available)"


def propose(
    condition_raw: str, question_ids: list[str], options_by_question: dict
) -> tuple[Condition | None, str]:
    """Ask a model to express a prose condition, then check its answer.

    The model's reply is text in the grammar above, never a tree. It is handed
    straight to `parse`, so anything the parser would refuse from a QRE it also
    refuses from the model. That is the whole safety argument: the model can
    only propose what the document could have written formally itself.

    Returns the condition and a note explaining what happened, so a refusal is
    recorded rather than silently dropped.
    """
    try:
        proposal = complete(
            _PROPOSE_SYSTEM,
            f"Condition as written: {condition_raw}\n\n"
            f"Answer options:\n{_catalogue(question_ids, options_by_question)}",
            LLMConditionProposal,
        )
    except LLMUnavailable as exc:
        return None, f"no model available: {exc}"

    if not proposal.expression:
        return None, f"model declined: {proposal.reasoning}"

    condition = parse(proposal.expression)
    if condition is None:
        # The model wrote something outside the grammar. Rejected rather than
        # patched, because a proposal we have to repair is one we cannot check.
        return None, (
            f"model proposed {proposal.expression!r}, which is not valid in the "
            "grammar and was rejected"
        )

    condition.source_text = condition_raw
    condition.origin = Origin.INFERRED
    condition.confidence = proposal.confidence
    return condition, f"read by model (confidence {proposal.confidence:.2f})"
