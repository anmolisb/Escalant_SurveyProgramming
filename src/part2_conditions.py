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

from models import Aggregate, Condition, ConditionOp, Operand, Origin

#: A question id: S1, Q12, D4, A_2. Kept loose because ids are the QRE's
#: convention, not ours.
_QID = r"[A-Za-z]{1,4}_?\d+"

#: Comparison operators, longest first so "!=" is not read as "=" and "not in"
#: is not read as "in".
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
]

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
        elif char == "[":
            depth += 1
        elif char == "]":
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
    for token, op in _OPERATORS:
        # Search rather than split, so only the first operator counts and a
        # value containing "=" does not confuse things.
        position = text.lower().find(token) if token.strip().isalpha() else text.find(token)
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
        return Condition(op=op, left=left, right=right, source_text=text.strip())
    return None


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
            child = _comparison(part)
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

    condition = _comparison(text)
    if condition is not None:
        condition.source_text = text
        condition.origin = Origin.DERIVED
    return condition


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
