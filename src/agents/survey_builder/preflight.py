"""Report everything in a stage 4 output that the builder cannot handle.

The builder raises on the first problem it meets, which is fine once a QRE is
known to work but slow when meeting a new one: fix the first gap, rerun, meet
the second. This walks the whole input and collects every gap in one pass.

What counts as supported is read from the loader itself rather than restated
here, so this cannot claim support the builder does not have.

    python -m src.agents.survey_builder.preflight fixtures/stage4-outputs/C02
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from src.agents.survey_builder.loader import (
    _SOURCE_QUESTION,
    _TYPE_MAP,
    ConditionError,
    _build_question,
    _relevance,
)

#: Routing actions the loader does something with. "reject" is included because
#: skipping it is a decision, not an oversight.
_HANDLED_ACTIONS = {"terminate", "show", "skip", "reject"}

_REQUIRED_FILES = [
    "stage4_survey.json",
    "stage4_questionnaire.json",
    "stage4_routing.json",
    "stage4_messages.json",
]


@dataclass
class Gap:
    where: str
    problem: str
    detail: str = ""

    def __str__(self) -> str:
        line = f"  {self.where:12} {self.problem}"
        return f"{line}\n{'':14} {self.detail}" if self.detail else line


def check(directory: str | Path) -> list[Gap]:
    directory = Path(directory)
    gaps: list[Gap] = []

    missing = [name for name in _REQUIRED_FILES if not (directory / name).exists()]
    for name in missing:
        gaps.append(Gap(name, "file not found"))
    if "stage4_questionnaire.json" in missing:
        return gaps  # nothing further can be checked without the questions

    questions_raw = json.loads((directory / "stage4_questionnaire.json").read_text())

    # Question types, and any other construct that stops a question building.
    by_title = {}
    for raw in questions_raw:
        kind = (raw.get("type") or "").strip().lower()
        if kind not in _TYPE_MAP:
            gaps.append(
                Gap(raw.get("id", "?"), f"question type {kind!r} is not mapped",
                    f"add it to _TYPE_MAP with the LimeSurvey type letter")
            )
            continue
        try:
            by_title[raw["id"]] = _build_question(raw, 1)
        except Exception as error:  # noqa: BLE001 - reporting, not handling
            gaps.append(Gap(raw.get("id", "?"), "question cannot be built", str(error)))

    # Conditions, checked by actually running the parser.
    def _try(where: str, condition: str, source: str) -> None:
        if not condition:
            return
        try:
            _relevance(condition, by_title)
        except ConditionError as error:
            gaps.append(Gap(where, f"{source} cannot be resolved", str(error)))

    routing_path = directory / "stage4_routing.json"
    if routing_path.exists():
        for rule in json.loads(routing_path.read_text()):
            name = rule.get("rule", "?")
            action = (rule.get("action") or "").strip().lower()
            if action not in _HANDLED_ACTIONS:
                gaps.append(Gap(name, f"routing action {action!r} is not handled"))
                continue
            if action in {"skip", "reject"}:
                continue  # neither emits an expression
            condition = (
                rule.get("condition_expression")
                or rule.get("condition")
                or rule.get("condition_raw")
                or ""
            )
            if not condition:
                gaps.append(
                    Gap(name, "no condition given",
                        "extraction returned null, so the rule cannot be built")
                )
                continue
            _try(name, condition, "condition")

    # Display conditions only matter where no routing rule covers the question.
    covered = set()
    if routing_path.exists():
        covered = {
            rule["destination"]
            for rule in json.loads(routing_path.read_text())
            if (rule.get("action") or "").strip().lower() == "show"
        }
    for raw in questions_raw:
        if raw["id"] in covered or raw["id"] not in by_title:
            continue
        _try(raw["id"], raw.get("display_condition") or "", "display_condition")

    # Option sources name their question in prose, which may not resolve.
    for raw in questions_raw:
        source = raw.get("dynamic_option_source")
        if not source:
            continue
        match = _SOURCE_QUESTION.search(source)
        if not match or match.group(1) not in by_title:
            gaps.append(
                Gap(raw["id"], "cannot tell which question the options come from",
                    repr(source))
            )

    return gaps


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    directory = sys.argv[1]
    gaps = check(directory)
    if not gaps:
        print(f"{directory}: no gaps, safe to build")
        return 0

    print(f"{directory}: {len(gaps)} thing(s) the builder cannot handle\n")
    for gap in gaps:
        print(gap)
    print(
        "\nFor an unmapped question type, the reliable way to fill the gap is to "
        "build one of that type by hand in LimeSurvey, export the .lss, and read "
        "the real structure off it."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
