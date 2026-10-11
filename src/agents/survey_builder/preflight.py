"""Report everything in a canonical specification the builder cannot handle.

The builder raises on the first problem it meets, which is fine once a QRE is
known to work but slow when meeting a new one: fix the first gap, rerun, meet
the second. This walks the whole specification and collects every gap in one
pass.

What counts as supported is read from the loader itself rather than restated
here, so this cannot claim support the builder does not have.

    python -m src.agents.survey_builder.preflight out/S01_campus_cafeteria_experience
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from src.agents.survey_builder.loader import (
    CANONICAL_FILE,
    SUPPORTED_KINDS,
    SUPPORTED_RULE_KINDS,
    ConditionError,
    _NUMERIC_TYPES,
    _build_question,
    _relevance,
    read_canonical,
)
from src.common.paths import agent1_dir

#: Attributes that actually constrain what a respondent may submit. A reject
#: rule is only safe to skip when the question carries one of these, so
#: cosmetic settings like num_value_int_only or answer_order do not count.
_VALIDATING_ATTRIBUTES = {
    "min_num_value_n", "max_num_value_n", "equals_num_value",
    "min_answers", "max_answers", "exclude_all_others",
    "em_validation_q", "array_filter", "maximum_chars",
}


@dataclass
class Gap:
    """Something the builder cannot do with this input.

    `blocking` separates "the build will fail or be wrong" from "something in
    the input is being ignored". Only the first should stop a build; the second
    is worth reading but usually means a field the QRE filled in that has no
    LimeSurvey equivalent.
    """

    where: str
    problem: str
    detail: str = ""
    blocking: bool = True

    def __str__(self) -> str:
        mark = "" if self.blocking else "note: "
        line = f"  {self.where:12} {mark}{self.problem}"
        return f"{line}\n{'':14} {self.detail}" if self.detail else line


def check_spec(spec: dict) -> list[Gap]:
    """Every gap between one canonical specification and what the builder does."""
    gaps: list[Gap] = []
    questions_raw = spec.get("questions") or []
    randomized = {r["question_id"]: r.get("scope") for r in spec.get("randomization") or []}

    # Question kinds, and any other construct that stops a question building.
    by_title = {}
    for raw in questions_raw:
        qid = raw.get("question_id", "?")
        kind = (raw.get("kind") or "").strip().lower()
        if kind not in SUPPORTED_KINDS:
            gaps.append(
                Gap(qid, f"question kind {kind!r} is not supported",
                    "add it to the loader's _TYPE_MAP with the LimeSurvey type letter")
            )
            continue
        try:
            by_title[qid] = _build_question(raw, 1, qid in randomized)
        except Exception as error:  # noqa: BLE001 - reporting, not handling
            gaps.append(Gap(qid, "question cannot be built", str(error)))

    # Fields the specification fills in that the builder would drop without
    # saying so. An unsupported kind stops the build and an unreadable
    # condition raises, but a field that is simply never read fails quietly:
    # the survey builds, and is wrong in a way nothing reports.
    for raw in questions_raw:
        qid = raw.get("question_id", "?")
        question = by_title.get(qid)
        if question is None:
            continue
        validation = raw.get("validation") or {}
        if question.type not in _NUMERIC_TYPES:
            for field in ("min_value", "max_value"):
                if validation.get(field) is not None:
                    gaps.append(
                        Gap(qid, f"{field} is set but the question is not numeric",
                            f"kind {raw.get('kind')!r} has no bounds in LimeSurvey",
                            blocking=False)
                    )
        if randomized.get(qid) == "rows":
            gaps.append(
                Gap(qid, "rows are randomised, but the build randomises answers",
                    "answer_order shuffles the scale, not the rows of the grid",
                    blocking=False)
            )
        if raw.get("extra"):
            gaps.append(
                Gap(qid, "extra settings will be dropped",
                    repr(raw["extra"]), blocking=False)
            )

    # When each question is shown. An unread guard would show the question to
    # everybody, so it stops the build rather than passing quietly.
    for raw in questions_raw:
        qid = raw.get("question_id", "?")
        guard = raw.get("guard") or {}
        if not guard or qid not in by_title:
            continue
        condition = guard.get("condition")
        if condition is None:
            gaps.append(
                Gap(qid, "display condition was not read",
                    f"{guard.get('raw_texts')!r}. Agent 1 left it for a person")
            )
            continue
        try:
            _relevance(condition, by_title)
        except ConditionError as error:
            gaps.append(Gap(qid, "display condition cannot be built", str(error)))

    # Routing rules.
    for rule in spec.get("rules") or []:
        name = rule.get("rule_id", "?")
        kind = rule.get("kind")
        if kind not in SUPPORTED_RULE_KINDS:
            gaps.append(Gap(name, f"rule kind {kind!r} is not handled"))
            continue
        if kind in ("skip", "show"):
            continue  # carried by the destination question's guard
        destination = (rule.get("destination") or {}).get("id")
        if kind == "reject":
            # Skipped on the basis that a reject rule restates a constraint the
            # question already carries. Check that something does.
            target = by_title.get(destination)
            piped = any(
                raw.get("question_id") == destination and raw.get("option_source")
                for raw in questions_raw
            )
            if target is not None and not piped and not (
                _VALIDATING_ATTRIBUTES & set(target.attributes)
            ):
                gaps.append(
                    Gap(name, "reject rule has nothing to fall back on",
                        f"{destination} carries no validation, so skipping this "
                        f"rule drops the constraint entirely",
                        blocking=False)
                )
            continue
        condition = rule.get("when")
        if condition is None:
            gaps.append(
                Gap(name, "terminate condition was not read",
                    f"{rule.get('when_unread')!r}. Agent 1 left it for a person")
            )
            continue
        try:
            _relevance(condition, by_title)
        except ConditionError as error:
            gaps.append(Gap(name, "terminate condition cannot be built", str(error)))

    # Piped options name the question they come from.
    for raw in questions_raw:
        source = (raw.get("option_source") or {}).get("from_question")
        if source and source not in by_title:
            gaps.append(
                Gap(raw.get("question_id", "?"),
                    "options come from a question the survey does not have",
                    repr(source))
            )

    return gaps


def check(directory: str | Path) -> list[Gap]:
    """Every gap for the canonical specification in a run or Agent 1 folder."""
    folder = agent1_dir(directory)
    if not (folder / CANONICAL_FILE).exists():
        return [Gap(CANONICAL_FILE, "file not found", str(folder))]
    return check_spec(read_canonical(folder))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    directory = sys.argv[1]
    gaps = check(directory)
    if not gaps:
        print(f"{directory}: no gaps, safe to build")
        return 0

    blocking = [g for g in gaps if g.blocking]
    notes = [g for g in gaps if not g.blocking]
    if blocking:
        print(f"{directory}: {len(blocking)} thing(s) the builder cannot handle\n")
        for gap in blocking:
            print(gap)
    else:
        print(f"{directory}: safe to build, with {len(notes)} thing(s) to be aware of\n")
    for gap in notes:
        print(gap)
    if not blocking:
        return 0
    print(
        "\nFor an unsupported question kind, the reliable way to fill the gap is "
        "to build one of that kind by hand in LimeSurvey, export the .lss, and "
        "read the real structure off it."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
