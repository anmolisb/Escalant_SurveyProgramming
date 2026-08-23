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


#: contains(Q5, 'x') / contains_any(Q1, ['a','b']) / answered(Q3).
_CALL = re.compile(r"^\s*([A-Za-z_]+)\s*\((.*)\)\s*$", re.S)

_CALL_OPS = {
    "contains": ConditionOp.CONTAINS,
    "contains_any": ConditionOp.CONTAINS_ANY,
    "contains_all": ConditionOp.CONTAINS_ALL,
    "answered": ConditionOp.ANSWERED,
    "unanswered": ConditionOp.UNANSWERED,
}


def _split_args(inner: str) -> list[str]:
    """Split a call's arguments on commas outside quotes and brackets."""
    args: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current.append(char)
        elif char in "[(":
            depth += 1
            current.append(char)
        elif char in "])":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current.strip() if isinstance(current, str) else "".join(current).strip():
        args.append("".join(current).strip())
    return [a for a in args if a]


def _call(text: str) -> Condition | None:
    """Read a function-style condition, or refuse.

    These forms do not appear in any QRE we have seen — the documents write
    prose instead. They exist because a model proposing a reading of that prose
    has to express it in something, and a grammar this parser can check is far
    safer than free text that nobody can.
    """
    match = _CALL.match(text)
    if not match:
        return None
    name = match.group(1).lower()
    op = _CALL_OPS.get(name)
    if op is None:
        return None
    args = _split_args(match.group(2))

    if op in (ConditionOp.ANSWERED, ConditionOp.UNANSWERED):
        if len(args) != 1:
            return None
        left = _operand(args[0])
        if left is None or left.question_id is None:
            return None
        return Condition(op=op, left=left, source_text=text.strip())

    if len(args) < 2:
        return None
    left = _operand(args[0])
    if left is None or left.question_id is None:
        return None
    if len(args) == 2:
        right = _operand(args[1])
    else:
        # contains_any(Q1, 'a', 'b') - loose arguments rather than a list.
        collected: list[str] = []
        for raw in args[1:]:
            value = _operand(raw)
            if value is None or value.text is None:
                return None
            collected.append(value.text)
        right = Operand(values=collected)
    if right is None:
        return None
    # A single value handed to a set operator is still a set of one.
    if right.values is None and right.text is not None and op is not ConditionOp.CONTAINS:
        right = Operand(values=[right.text])
    return Condition(op=op, left=left, right=right, source_text=text.strip())


def _term(text: str) -> Condition | None:
    """One piece of an expression: a negation, a bracketed group, a call, or a
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

    call = _call(text)
    if call is not None:
        return call
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
  membership   contains(Q5, 'Dealer visit')
               contains_any(Q1, ['Auto Brand A','Auto Brand B'])
               contains_all(Q1, ['Auto Brand A','Auto Brand B'])
               contains(Q5, Q6)
  asked or not answered(Q3)      unanswered(Q3)
  combining    A and B           A or B           not A
               (A and B) or (C and D)

Refer to questions by the ids given. Refer to answers by their exact label in
single quotes, copied from the option list. Never invent a label or an id.

Two operators are easy to confuse and mean different things:
  Q1 == ['None of these']   the answer set is EXACTLY that, and nothing else
  contains(Q1, 'None of these')   that was chosen, possibly among others
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
