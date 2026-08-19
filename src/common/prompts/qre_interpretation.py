"""Agent 1 prompts — QRE interpretation (CLAUDE.md §42).

Each prompt carries a version string. When a prompt's wording changes, bump its
version: a run's recorded prompt version is what makes an output reproducible and
a regression explainable (CLAUDE.md §50, §55).

All functions here route through the shared client in `src/common/llm/`, never a
provider SDK directly (CLAUDE.md §52).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ..llm.groq_client import GroqClient, LLMCallError, build_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Step 2 — section heading classification
# ---------------------------------------------------------------------------

#: v2 strengthens the null bias. v1 let every available model map an adjacent but
#: distinct heading ("Weighting And Analysis Plan") onto the nearest label
#: ("study_specification") instead of declining — the precise over-reach
#: CLAUDE.md §30 prohibits. Bump this version on any wording change.
SECTION_CLASSIFICATION_PROMPT_VERSION = "section_classification.v2"

SECTION_CLASSIFICATION_SYSTEM_PROMPT = """\
You classify section headings from market-research questionnaire requirement \
documents (QREs).

You are given one heading and a fixed list of allowed section labels. Decide \
whether the heading names the SAME section type as one of the labels.

Decision rule, in order:
1. If the heading is a synonym or direct restatement of exactly one allowed \
label, return that label.
2. Otherwise return null.

"Related topic" is NOT a match. Survey documentation contains many section types \
beyond the allowed list, and a heading about a neighbouring subject must return \
null rather than the closest available label. A null answer costs nothing — the \
section is simply routed to a human reviewer. A wrong label silently misroutes \
the section's content into the wrong stage of an automated pipeline, which is far \
more damaging than declining to answer.

Never return a label that is not in the allowed list.
Judge only the wording given. Do not reason about which sections a QRE usually \
contains, or where this heading probably sits in the document.

Examples, assuming the allowed labels are \
[study_specification, questionnaire, routing_and_termination, quota_controls]:

  "Question List"            -> {"label": "questionnaire"}
  "Skip Logic"               -> {"label": "routing_and_termination"}
  "Sample Balancing Rules"   -> {"label": "quota_controls"}
  "Weighting And Analysis Plan" -> {"label": null}
      (analysis and weighting is its own section type, not a study specification)
  "Translation Requirements" -> {"label": null}
  "Fieldwork Timings"        -> {"label": null}

Respond with JSON only, in exactly this shape:
{"label": "<one allowed label>"}  or  {"label": null}
"""


def classify_section_heading(
    heading_text: str,
    allowed_labels: Sequence[str],
    client: GroqClient | None = None,
) -> str | None:
    """Classify one section heading against the allowed label vocabulary.

    Matches the `SectionClassifier` signature that Step 2's `detect_sections`
    expects, so it can be passed straight in as `classifier=`.

    Only the heading text and the label list are sent to the provider — never
    section bodies, question wording or respondent data.

    Args:
        heading_text:   raw heading text from the document.
        allowed_labels: the canonical labels the caller will accept.
        client:         optional pre-built client. When None, one is built from
                        settings; if the LLM is unavailable, returns None so the
                        caller flags the heading instead of guessing.

    Returns:
        A label from `allowed_labels`, or None when no confident match exists.
        Step 2 independently re-checks the returned label against its vocabulary
        (CLAUDE.md §17), so a bad answer here cannot widen the contract.
    """
    if not heading_text.strip():
        return None

    active_client = client if client is not None else build_client()
    if active_client is None:
        return None

    user_prompt = (
        f"Heading: {heading_text}\n"
        f"Allowed labels: {', '.join(allowed_labels)}\n"
        "Which allowed label does this heading refer to?"
    )

    try:
        payload = active_client.complete_json(
            SECTION_CLASSIFICATION_SYSTEM_PROMPT, user_prompt
        )
    except LLMCallError as exc:
        # A failed call must not stop the run. Returning None routes the heading
        # to the review queue, which is the correct unresolved state (§30, §31).
        logger.warning(
            "Section classification failed for heading %r (prompt %s): %s",
            heading_text,
            SECTION_CLASSIFICATION_PROMPT_VERSION,
            exc,
        )
        return None

    label = payload.get("label")
    if label is None or not isinstance(label, str) or not label.strip():
        return None
    return label.strip()


# ---------------------------------------------------------------------------
# Step 4 — table column-role classification
# ---------------------------------------------------------------------------

COLUMN_CLASSIFICATION_PROMPT_VERSION = "column_classification.v1"

#: What each role means, so the model judges intent rather than guessing from a
#: bare identifier. Keys must match question_parser's ROLE_* values.
_COLUMN_ROLE_DESCRIPTIONS = {
    "id": "the question's identifier or reference code, e.g. Q1, SC3, A_2",
    "wording": "the question text read to or shown to the respondent",
    "type": "the question or answer format, e.g. single, multi, grid, open text",
    "options_raw": "the answer options, response list, scale points or codeframe",
    "display_validation_raw": (
        "when the question is shown, and/or validation rules on the answer — "
        "base, display conditions, routing conditions, min/max checks"
    ),
}

COLUMN_CLASSIFICATION_SYSTEM_PROMPT = """\
You classify column headers from questionnaire requirement documents (QREs).

Each header names one column of a table whose rows are survey questions. Decide \
which of the given roles the column holds.

Decision rule, in order:
1. If the header clearly names the content of exactly one role, return that role.
2. Otherwise return null.

Return null when a column is something else entirely — scripter instructions, \
translation notes, internal comments, page numbers, revision history, timings. \
QRE tables routinely carry such columns and they belong to no role. A null answer \
costs nothing: the column is preserved and shown to a reviewer. A wrong role \
silently feeds the wrong text into an automated survey build.

Never return a role that is not in the allowed list.
Judge only the header wording given.

Respond with JSON only, in exactly this shape:
{"role": "<one allowed role>"}  or  {"role": null}
"""


def classify_table_column(
    header_text: str,
    allowed_roles: Sequence[str],
    client: GroqClient | None = None,
) -> str | None:
    """Classify one table column header against the allowed roles.

    Matches the `ColumnClassifier` signature that Step 4's `parse_questions`
    expects, so it can be passed straight in as `classifier=`.

    Only the header text and the role list are sent — never cell contents,
    question wording or answer options.

    Args:
        header_text:   raw column header from the table.
        allowed_roles: roles the caller will accept.
        client:        optional pre-built client. When None, one is built from
                       settings; if the LLM is unavailable, returns None so the
                       caller leaves the column unmapped rather than guessing.

    Returns:
        A role from `allowed_roles`, or None when no confident match exists. Step
        4 re-checks the returned role against its own vocabulary (CLAUDE.md §17).
    """
    if not header_text.strip():
        return None

    active_client = client if client is not None else build_client()
    if active_client is None:
        return None

    described = [
        f"- {role}: {_COLUMN_ROLE_DESCRIPTIONS[role]}"
        if role in _COLUMN_ROLE_DESCRIPTIONS
        else f"- {role}"
        for role in allowed_roles
    ]
    user_prompt = (
        f"Column header: {header_text}\n\n"
        "Allowed roles:\n" + "\n".join(described) + "\n\n"
        "Which allowed role does this column hold?"
    )

    try:
        payload = active_client.complete_json(
            COLUMN_CLASSIFICATION_SYSTEM_PROMPT, user_prompt
        )
    except LLMCallError as exc:
        logger.warning(
            "Column classification failed for header %r (prompt %s): %s",
            header_text,
            COLUMN_CLASSIFICATION_PROMPT_VERSION,
            exc,
        )
        return None

    role = payload.get("role")
    if role is None or not isinstance(role, str) or not role.strip():
        return None
    return role.strip()


# ---------------------------------------------------------------------------
# Step 5 — prose display-condition conversion
# ---------------------------------------------------------------------------

CONDITION_CONVERSION_PROMPT_VERSION = "condition_conversion.v1"

CONDITION_CONVERSION_SYSTEM_PROMPT = """\
You convert display conditions from survey questionnaires into structured form.

A display condition says when a question is shown, by testing an earlier \
question's answer. Operator forms like "Q5 == 'Yes'" are already structured and \
never reach you. You are given the ones written as prose, such as \
"Show if: Q5 contains any touchpoint".

You are given the condition, the id of the question it tests, and that \
question's own answer options. Resolve the prose against those options: \
"contains any touchpoint" over options [Physician, Hospital, Pharmacy, None of \
these] means any of the real touchpoints, and excludes the "none" option.

Allowed operators:
- equals          answer is exactly this value
- not_equals      answer is anything but this value
- in              answer is one of these values
- not_in          answer is none of these values
- contains_any    a multi-select answer includes at least one of these values
- contains_all    a multi-select answer includes every one of these values
- greater_than    numeric answer above this value
- less_than       numeric answer below this value

Rules:
- "values" must be option labels copied EXACTLY from the supplied option list. \
Never invent, reword, translate or abbreviate an option.
- If the condition cannot be resolved against the supplied options, or the \
option list is empty, return null. A null answer sends the condition to a human \
reviewer, which is cheap. A wrong operator silently routes real respondents \
down the wrong path, which is not.
- Never return an operator outside the allowed list.

Respond with JSON only:
{"operator": "<allowed operator>", "question_id": "<id>", "values": ["..."]}
or {"operator": null}
"""


def convert_display_condition(
    condition_text: str,
    question_id: str,
    options: Sequence[str],
    client: GroqClient | None = None,
) -> dict | None:
    """Convert one prose display condition into a structured form.

    Matches the `ConditionConverter` signature Step 5's `build_questions`
    expects, so it can be passed straight in as `converter=`.

    Only the condition text and the referenced question's option labels are sent
    — never question wording, other questions, or document content.

    Args:
        condition_text: e.g. "Show if: Q5 contains any touchpoint".
        question_id:    the question the condition tests, e.g. "Q5".
        options:        that question's option labels, which the prose is
                        resolved against.
        client:         optional pre-built client.

    Returns:
        {"operator", "question_id", "values"}, or None when unresolvable. Step 5
        re-checks the operator against its own set, and a value not present in
        the supplied options is dropped, so a bad answer cannot widen the
        contract or invent an option (CLAUDE.md §17, §30).
    """
    if not condition_text.strip() or not options:
        return None

    active_client = client if client is not None else build_client()
    if active_client is None:
        return None

    user_prompt = (
        f"Condition: {condition_text}\n"
        f"Tests question: {question_id}\n"
        f"That question's options:\n"
        + "\n".join(f"- {o}" for o in options)
        + "\n\nConvert this condition."
    )

    try:
        payload = active_client.complete_json(
            CONDITION_CONVERSION_SYSTEM_PROMPT, user_prompt
        )
    except LLMCallError as exc:
        logger.warning(
            "Condition conversion failed for %r (prompt %s): %s",
            condition_text,
            CONDITION_CONVERSION_PROMPT_VERSION,
            exc,
        )
        return None

    operator = payload.get("operator")
    if not operator or not isinstance(operator, str):
        return None

    # Keep only values the referenced question actually offers. A model that
    # invents an option would otherwise put a non-existent answer into routing.
    proposed = payload.get("values") or []
    allowed = {str(o) for o in options}
    values = [str(v) for v in proposed if str(v) in allowed]
    if proposed and not values:
        logger.warning(
            "Condition conversion for %r returned no value matching %s's options; "
            "treating as unresolved.",
            condition_text,
            question_id,
        )
        return None

    return {
        "operator": operator.strip(),
        "question_id": str(payload.get("question_id") or question_id),
        "values": values,
    }
