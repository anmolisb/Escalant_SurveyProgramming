"""Self-check for the condition parser and its canonical renderer.

Run directly: `python3 src/test_conditions.py`. No framework on purpose.

The renderer is what gives every condition one written shape, whatever the QRE
or a model wrote, so the property worth holding is that every shape a QRE might
write collapses onto one rendering, and that rendering reads back as the same
condition.
"""

import re
import sys
from pathlib import Path


from src.agents.qre_interpretation import stage6_conditions as pc
from src.agents.qre_interpretation.models import ConditionOp


def check_round_trip() -> None:
    """Rendering, re-parsing and rendering again gives the same string."""
    for text in (
        "S1 == 'No'",
        "Q12 in ['Fully','Partly']",
        "Q1 == ['None of these']",
        "sum(Q18) != 100",
        "Q1 contains_any ['a','b']",
        "Q3 != 'None' and Q5 == 'Yes'",
        "Q3 answered",
        "Q3 unanswered",
        "Q5 contains 'Dealer visit'",
        "Q5 contains Q6",
        "Q1 not in ['x']",
        "Q5 >= 3",
        "Q2 == \"Don't know\"",
    ):
        condition = pc.parse(text)
        assert condition is not None, f"did not parse: {text}"
        rendered = pc.render(condition)
        assert rendered is not None, f"did not render: {text}"
        again = pc.parse(rendered)
        assert again is not None, f"rendering did not parse back: {rendered}"
        assert pc.render(again) == rendered, f"not stable: {text} -> {rendered}"


def check_shapes_converge() -> None:
    """The three shapes that drifted all render as one.

    This is the defect that prompted the change: all three were in C02's
    routing file for the same operator, and every consumer needed a regex each.
    """
    shapes = [
        "Q1 CONTAINS_ANY ['a','b']",
        "Q1 contains_any ['a', 'b']",
        "Q1 contains_any 'a'",
    ]
    rendered = {pc.render(pc.parse(shape)) for shape in shapes[:2]}
    assert rendered == {"Q1 contains_any ['a', 'b']"}, rendered
    # A lone value given to a set operator is still a set of one.
    assert pc.render(pc.parse(shapes[2])) == "Q1 contains_any ['a']"


def check_question_is_always_leftmost() -> None:
    """Every rendered comparison starts with its question id.

    This is the property that lets one regex read any condition: the question
    is never inside brackets, whatever the operator. `contains_any(Q1, [...])`
    was the exception that forced a rule per operator downstream.
    """
    leading = re.compile(r"^(?:sum|count)\(([A-Za-z]{1,4}_?\d+)\)|^([A-Za-z]{1,4}_?\d+)\b")
    for text in (
        "Q1 contains_any ['a','b']",
        "Q1 contains_all ['a','b']",
        "Q5 contains 'Dealer visit'",
        "Q3 answered",
        "Q3 unanswered",
        "S1 == 'No'",
        "Q12 in ['Fully','Partly']",
        "sum(Q18) != 100",
    ):
        rendered = pc.render(pc.parse(text))
        assert rendered is not None, text
        match = leading.match(rendered)
        assert match, f"question is not leftmost: {rendered}"
        assert (match.group(1) or match.group(2)).startswith(("Q", "S")), rendered


def check_call_form_is_gone() -> None:
    """The old call syntax is no longer accepted, so it cannot come back."""
    for text in ("contains_any(Q1, ['a','b'])", "answered(Q3)", "contains(Q5, 'x')"):
        assert pc.parse(text) is None, f"still parses: {text}"


def check_set_equality_survives() -> None:
    """"Q1 == ['None of these']" is about the whole answer set, not one value."""
    condition = pc.parse("Q1 == ['None of these']")
    assert condition.op is ConditionOp.SET_EQ
    assert pc.render(condition) == "Q1 == ['None of these']"


def check_apostrophe_value() -> None:
    """A label containing an apostrophe must not terminate its own quoting."""
    condition = pc.parse("Q1 in [\"Don't know\", 'Yes']")
    rendered = pc.render(condition)
    assert pc.render(pc.parse(rendered)) == rendered, rendered


if __name__ == "__main__":
    checks = [v for k, v in sorted(globals().items()) if k.startswith("check_")]
    for check in checks:
        check()
        print(f"  ok  {check.__name__}")
    print(f"{len(checks)} checks passed")
