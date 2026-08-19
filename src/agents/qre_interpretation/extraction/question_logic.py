"""Agent 1 · Part 1 · Step 5 — Build the logic for each question.

    In:  RawQuestion list from Step 4
    Out: list of Question objects
         {id, wording, type, options[], validation_rules[], display_condition,
          randomize, dynamic_option_source}

Step 4 separated the compound cell and handed on strings. Step 5 turns those
strings into structures Agent 2 can act on without re-parsing:

  - "Yes; No"                        → [Option("Yes"), Option("No")]
  - "1 - Very poor; 2 - Poor"        → options carrying code "1", "2"
  - "Rows: A; B\\nScale: 1 - Low"     → MatrixSpec(rows=[...], scale=[...])
  - 'Validate: {"min_length": 10}'   → ValidationRule(parameters={"min_length": 10})
  - "Show if: Q5 == 'Yes'"           → DisplayCondition(equals, Q5, ("Yes",))
  - "Show if: Q7 contains any problem" → resolved against Q7's own option list

On not repeating Step 4. The step table lists "splits multi-part display cells"
under Step 5, but Step 4 already does that: it runs `instruction_splitter` and
each RawQuestion arrives carrying `instructions`, classified and in order. This
module therefore reads `question.display_conditions`, `.validation_rules`,
`.randomize` and `.dynamic_option_source` rather than re-splitting the cell. One
splitter, one vocabulary, one place to fix — re-implementing it here would give
two classifiers that could disagree about the same text.

Condition conversion is layered, as elsewhere in this agent (CLAUDE.md §29):

  1. Deterministic parse of the operator forms the corpus actually uses —
     "Always show", `==`, `!=`, `in [...]`. These are already formal; sending
     them to a model would add cost and a chance of a wrong answer.
  2. An optional model call for genuinely prose conditions such as "contains any
     touchpoint", where resolving "any touchpoint" requires the referenced
     question's own option list. This is the case the step table describes as
     "using each question's own option list".
  3. Neither → the condition is kept with its source text, marked unresolved and
     flagged. Never guessed (§30).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence

from .question import (
    KNOWN_OPERATORS,
    OP_ALWAYS,
    OP_EQUALS,
    OP_IN,
    OP_NOT_EQUALS,
    OP_NOT_IN,
    PROV_DERIVED,
    PROV_EXTRACTED,
    PROV_INFERRED,
    PROV_UNKNOWN,
    DisplayCondition,
    MatrixSpec,
    Option,
    Question,
    QuestionLogic,
    ValidationRule,
)
from .raw_question import RawQuestion
from .sectioned_document import ReviewItem

# ---------------------------------------------------------------------------
# Option-list parsing
# ---------------------------------------------------------------------------

#: Separator between options. Semicolon in every corpus QRE; comma is accepted
#: only as a fallback when no semicolon is present, because option labels
#: themselves frequently contain commas.
_PRIMARY_SEPARATOR = ";"

#: Text meaning "this question has no option list". Interpreting the em dash is
#: legitimate here — Step 5 is the interpreting step — where Step 4 correctly
#: left it as the literal "—".
_NO_OPTIONS_MARKERS = {"—", "-", "–", "n/a", "na", "none", ""}

#: A leading response code. Deliberately narrow: a looser rule would read
#: "Very poor - never again" as code "Very", inventing a code the document never
#: gave (§13, §30).
#:
#: Two forms, and the whitespace rule differs between them on purpose:
#:   "1 - Very poor"  a hyphen REQUIRES a following space. Without that,
#:                    "T-shirt" and "US-based" would parse as code + label.
#:   "1=Yes", "1) Yes"  "=" and ")" do not occur inside words, so the space is
#:                    optional after them.
#: The code itself is digits or at most three alphanumerics, so no ordinary word
#: can be mistaken for one.
_CODE_PREFIX = re.compile(
    r"^\s*(\d+|[A-Za-z0-9]{1,3})\s*(?:[=)]\s*|-\s+)(.*\S)\s*$"
)

#: "Rows: ... / Scale: ..." matrix notation, as used by the corpus.
_MATRIX_PART = re.compile(r"^\s*(rows?|scale|columns?|cols?)\s*:\s*(.*)$", re.IGNORECASE)


def split_option_list(text: str) -> tuple[Option, ...]:
    """Split an option cell into typed Options.

    Splits on semicolons, falling back to commas only when no semicolon appears —
    labels such as "Thank you, that is all" contain commas, so comma-splitting
    a semicolon-delimited list would shred them.

    A leading "1 - " or "1=" becomes the option's `code`; anything else leaves
    `code` as None rather than inventing one.
    """
    if not text or text.strip().lower() in _NO_OPTIONS_MARKERS:
        return ()

    separator = _PRIMARY_SEPARATOR if _PRIMARY_SEPARATOR in text else ","
    options: list[Option] = []
    for part in text.split(separator):
        raw = part.strip()
        if not raw:
            continue
        match = _CODE_PREFIX.match(raw)
        if match:
            options.append(Option(label=match.group(2).strip(), code=match.group(1), raw=raw))
        else:
            options.append(Option(label=raw, code=None, raw=raw))
    return tuple(options)


def parse_matrix(text: str) -> MatrixSpec | None:
    """Parse "Rows: …" / "Scale: …" notation into rows and scale.

    Returns None when the cell is not in that form, so a caller can fall back to
    treating it as a flat option list.
    """
    if not text or not text.strip():
        return None

    rows: tuple[Option, ...] = ()
    scale: tuple[Option, ...] = ()
    found = False

    for line in text.split("\n"):
        match = _MATRIX_PART.match(line)
        if not match:
            continue
        found = True
        kind, payload = match.group(1).lower(), match.group(2)
        if kind.startswith("row"):
            rows = split_option_list(payload)
        else:
            scale = split_option_list(payload)

    return MatrixSpec(rows=rows, scale=scale) if found else None


# ---------------------------------------------------------------------------
# Validation parsing
# ---------------------------------------------------------------------------

#: The JSON object inside an instruction such as 'Validate: {"min_length": 10}'.
_JSON_PAYLOAD = re.compile(r"\{.*\}", re.DOTALL)


def parse_validation_rule(raw: str) -> ValidationRule:
    """Decode the JSON payload of a validation instruction.

    "reads structured validation JSON verbatim" in the step table: the payload is
    decoded, not reinterpreted. Keys are whatever the QRE wrote — no renaming,
    no defaults added.

    A payload that will not decode yields a rule with the error recorded and the
    raw text intact, so a malformed rule is visible rather than dropped (§16).
    """
    match = _JSON_PAYLOAD.search(raw)
    if not match:
        return ValidationRule(raw=raw, parse_error="no JSON object found")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return ValidationRule(raw=raw, parse_error=f"invalid JSON: {exc}")
    if not isinstance(parsed, dict):
        return ValidationRule(
            raw=raw, parse_error=f"expected a JSON object, got {type(parsed).__name__}"
        )
    return ValidationRule(raw=raw, parameters=parsed)


# ---------------------------------------------------------------------------
# Display-condition conversion
# ---------------------------------------------------------------------------

_ALWAYS = re.compile(r"^\s*(always\s+show|ask\s+all|all\s+respondents)\s*\.?\s*$", re.I)
#: "Show if: <question> <operator> <value>" — the conditional forms in the corpus.
_CONDITION_BODY = re.compile(r"^\s*(?:show|ask|display)\s+if\s*:?\s*(.+?)\s*\.?\s*$", re.I)
_COMPARISON = re.compile(
    r"^([A-Za-z][\w.]*)\s*(==|!=|>=|<=|>|<|=)\s*(.+)$"
)
_IN_LIST = re.compile(r"^([A-Za-z][\w.]*)\s+(not\s+in|in)\s*\[(.*)\]\s*$", re.I)
_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")

#: Signature of an optional converter for prose conditions. Receives the
#: condition text and the options of the question it references; returns
#: {"operator": ..., "question_id": ..., "values": [...]}, or None to decline.
ConditionConverter = Callable[[str, str, Sequence[str]], dict | None]

#: Default for `converter`, meaning "use whatever the project is configured to
#: use". Distinct from None, which explicitly disables the model.
USE_CONFIGURED_LLM = "__use_configured_llm__"


def _configured_converter() -> ConditionConverter | None:
    """The project's configured condition converter, or None if unavailable.

    Imported lazily and only when the LLM is enabled, so this module keeps no
    import-time dependency on any provider (CLAUDE.md §52).
    """
    from common.config import get_settings

    if not get_settings().llm_enabled:
        return None
    from common.prompts.qre_interpretation import convert_display_condition

    return convert_display_condition


def _values_from(text: str) -> tuple[str, ...]:
    """Pull comparison values out of a condition's right-hand side."""
    quoted = [a or b for a, b in _QUOTED.findall(text)]
    if quoted:
        return tuple(v.strip() for v in quoted if v.strip())
    return tuple(v.strip() for v in text.split(",") if v.strip())


def convert_condition(
    raw: str,
    options_by_question: dict[str, Sequence[str]] | None = None,
    converter: ConditionConverter | None = None,
) -> DisplayCondition:
    """Turn one display instruction into a typed DisplayCondition.

    Args:
        raw:                 the instruction, e.g. "Show if: Q5 == 'Yes'".
        options_by_question: {question_id: option labels}, used to give a prose
                             converter the referenced question's own option list.
        converter:           optional semantic converter for prose conditions.

    Returns:
        A DisplayCondition. Unresolvable input still returns one — carrying the
        raw text, `operator=None` and a note — rather than raising or guessing.
    """
    text = raw.strip()

    if _ALWAYS.match(text):
        return DisplayCondition(
            raw=raw, operator=OP_ALWAYS, provenance=PROV_EXTRACTED
        )

    body_match = _CONDITION_BODY.match(text)
    body = body_match.group(1) if body_match else text

    # "Q9 in ['A','B']" / "Q9 not in [...]"
    in_match = _IN_LIST.match(body)
    if in_match:
        question_id, keyword, payload = in_match.groups()
        operator = OP_NOT_IN if keyword.lower().startswith("not") else OP_IN
        return DisplayCondition(
            raw=raw,
            operator=operator,
            question_id=question_id,
            values=_values_from(payload),
            provenance=PROV_DERIVED,
        )

    # "Q10 == 'Yes'" / "Q3 != 'None'"
    comparison = _COMPARISON.match(body)
    if comparison:
        question_id, symbol, right = comparison.groups()
        operator = {
            "==": OP_EQUALS,
            "=": OP_EQUALS,
            "!=": OP_NOT_EQUALS,
            ">": "greater_than",
            ">=": "greater_than",
            "<": "less_than",
            "<=": "less_than",
        }[symbol]
        return DisplayCondition(
            raw=raw,
            operator=operator,
            question_id=question_id,
            values=_values_from(right),
            provenance=PROV_DERIVED,
        )

    # Prose — "Q7 contains any problem". Resolving "any problem" needs Q7's
    # options, which is exactly what the step table means by converting
    # "using each question's own option list".
    referenced = re.match(r"^([A-Za-z][\w.]*)\b", body)
    question_id = referenced.group(1) if referenced else None

    if converter is not None:
        options = list((options_by_question or {}).get(question_id or "", ()))
        proposed = converter(raw, question_id or "", options)
        if isinstance(proposed, dict):
            operator = proposed.get("operator")
            # Guard the boundary: a converter must not invent an operator
            # outside the agreed set (§17).
            if operator in KNOWN_OPERATORS:
                values = proposed.get("values") or ()
                return DisplayCondition(
                    raw=raw,
                    operator=operator,
                    question_id=proposed.get("question_id") or question_id,
                    values=tuple(str(v) for v in values),
                    provenance=PROV_INFERRED,
                )

    return DisplayCondition(
        raw=raw,
        question_id=question_id,
        provenance=PROV_UNKNOWN,
        note=(
            "Condition is not in a recognized operator form and no converter "
            "resolved it. The source text is preserved for review."
        ),
    )


# ---------------------------------------------------------------------------
# Step 5 entry point
# ---------------------------------------------------------------------------

#: Question types whose option cell is a matrix rather than a flat list. Used
#: only as a hint — the "Rows:/Scale:" notation is detected on the cell itself,
#: so a matrix written under any type name is still parsed correctly.
_MATRIX_TYPE_HINTS = ("matrix", "grid")


def build_questions(
    raw_questions: Sequence[RawQuestion],
    converter: ConditionConverter | None | str = USE_CONFIGURED_LLM,
) -> QuestionLogic:
    """Interpret Step 4's raw questions into typed Question objects.

    Args:
        raw_questions: Step 4 output (`QuestionExtraction.questions`).
        converter:     semantic converter for prose display conditions.
                       Defaults to the project's configured LLM. Pass None to
                       force deterministic-only behaviour, or a callable to
                       inject your own. Without one, prose conditions are
                       flagged, not guessed.

    Returns:
        QuestionLogic. `.questions` is the list the step table specifies;
        `.review_queue` carries anything a human should check.
    """
    if converter is USE_CONFIGURED_LLM:
        converter = _configured_converter()

    # Option labels per question, so a condition referencing another question can
    # be resolved against that question's own options.
    options_by_question: dict[str, list[str]] = {}
    for raw in raw_questions:
        matrix = parse_matrix(raw.options_raw)
        options = matrix.scale if matrix else split_option_list(raw.options_raw)
        if raw.id:
            options_by_question[raw.id] = [o.label for o in options]

    # Identical conditions are common — one QRE states "Show if: Q7 contains any
    # problem" on twelve questions — and converting each separately would repeat
    # the same model call twelve times. Cached per run and keyed on the option
    # list too, so two documents whose Q1 offers different options can never
    # share an answer. Deterministic conversions are cheap but cached alike, to
    # keep one code path.
    condition_cache: dict[tuple[str, tuple[str, ...]], DisplayCondition] = {}

    def resolve(raw_condition: str, referenced: str | None) -> DisplayCondition:
        key = (raw_condition, tuple(options_by_question.get(referenced or "", ())))
        if key not in condition_cache:
            condition_cache[key] = convert_condition(
                raw_condition, options_by_question, converter
            )
        return condition_cache[key]

    questions: list[Question] = []
    review_queue: list[ReviewItem] = []

    for raw in raw_questions:
        matrix = parse_matrix(raw.options_raw)
        if matrix is not None:
            options = matrix.scale
        else:
            options = split_option_list(raw.options_raw)
            if raw.type.lower() in _MATRIX_TYPE_HINTS:
                review_queue.append(
                    ReviewItem(
                        element=raw.id,
                        reason="matrix_structure_not_found",
                        detail=(
                            f"Question {raw.id} is typed '{raw.type}' but its "
                            "options cell has no rows/scale structure. It was "
                            "read as a flat option list."
                        ),
                        source_reference=raw.source_reference,
                    )
                )

        rules = tuple(parse_validation_rule(v) for v in raw.validation_rules)
        for rule in rules:
            if rule.parse_error is not None:
                review_queue.append(
                    ReviewItem(
                        element=raw.id,
                        reason="validation_payload_unparseable",
                        detail=(
                            f"Validation rule on {raw.id} could not be decoded "
                            f"({rule.parse_error}). Raw text preserved: {rule.raw!r}"
                        ),
                        source_reference=raw.source_reference,
                    )
                )

        condition: DisplayCondition | None = None
        if raw.display_conditions:
            # Step 4 already separated these; a cell stating more than one is
            # rare, so convert the first and report the rest rather than
            # inventing a conjunction the document did not write.
            first = raw.display_conditions[0]
            referenced = re.match(r"^\s*(?:show|ask|display)\s+if\s*:?\s*([A-Za-z][\w.]*)", first, re.I)
            condition = resolve(first, referenced.group(1) if referenced else None)
            if len(raw.display_conditions) > 1:
                review_queue.append(
                    ReviewItem(
                        element=raw.id,
                        reason="multiple_display_conditions",
                        detail=(
                            f"Question {raw.id} states {len(raw.display_conditions)} "
                            "display conditions. Only the first was converted; the "
                            f"others are preserved on the Step 4 record: "
                            f"{list(raw.display_conditions[1:])}"
                        ),
                        source_reference=raw.source_reference,
                    )
                )
            if not condition.is_resolved:
                review_queue.append(
                    ReviewItem(
                        element=raw.id,
                        reason="display_condition_unresolved",
                        detail=(
                            f"Could not convert {condition.raw!r} on {raw.id} into a "
                            "typed condition. Preserved as source text."
                        ),
                        source_reference=raw.source_reference,
                    )
                )

        # A condition pointing at a question that does not exist breaks routing
        # downstream, so check the reference (§39.26).
        if (
            condition is not None
            and condition.question_id
            and condition.question_id not in options_by_question
        ):
            review_queue.append(
                ReviewItem(
                    element=raw.id,
                    reason="condition_references_unknown_question",
                    detail=(
                        f"Display condition on {raw.id} references "
                        f"'{condition.question_id}', which is not a question in "
                        "this questionnaire."
                    ),
                    source_reference=raw.source_reference,
                )
            )

        questions.append(
            Question(
                id=raw.id,
                wording=raw.wording,
                type=raw.type,
                options=options,
                validation_rules=rules,
                display_condition=condition,
                randomize=bool(raw.randomize),
                randomize_notes=tuple(raw.randomize),
                dynamic_option_source=raw.dynamic_option_source,
                matrix=matrix,
                source_reference=raw.source_reference,
                raw_question_id=raw.id,
            )
        )

    return QuestionLogic(questions=questions, review_queue=review_queue)
