"""Can Agents 2, 3 and 4 handle this canonical specification? Asked before they run.

Each agent meets an unsupported construct only when it reaches it: the Survey
Builder raises partway through a build, the Test Designer quietly designs no
answer for a question kind it does not know, and the Respondent Bot is left
stuck on a page it cannot fill. M01's age question was exactly that: Agent 3
had no answer for an `integer` question, so 51 of 82 journeys stopped at it.

This reads `agent1_canonical_survey_spec.json` once, lists what it uses, and checks each
agent against what that agent says it supports. The lists are imported from
each agent's own code, never retyped here, so adding support in an agent
updates this check with it.

    python -m src.common.readiness out/C01_chronic_care_patient_journey

Exit status 1 when anything blocks, so it can gate a pipeline.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from src.agents.respondent_bot.run_browser import FILLABLE_VALUE_KINDS
from src.agents.survey_builder import loader as survey_loader
from src.agents.survey_builder.preflight import check_spec as survey_builder_gaps
from src.agents.test_design import b2_witness, b3_oracle
from src.agents.test_design.spec import DISPLAY_KINDS
from src.agents.test_design.c_compile_executable import VALUE_KIND_BY_TYPE
from src.common.paths import agent1_dir

AGENTS = {
    2: "Survey Builder",
    3: "Test Designer",
    4: "Respondent Bot",
}

_LOGICAL = {"and", "or", "not"}


@dataclass
class Finding:
    agent: int
    where: str
    problem: str
    blocking: bool = True

    def __str__(self) -> str:
        mark = "BLOCKS" if self.blocking else "note  "
        return f"  {mark}  {self.where:10} {self.problem}"


def _atoms(condition: dict | None):
    """Every comparison inside a condition tree, with and/or/not opened up."""
    if not condition:
        return
    if condition.get("op") in _LOGICAL:
        for part in condition.get("operands") or []:
            yield from _atoms(part)
        return
    yield condition


def _shape(atom: dict) -> str:
    """Which family a comparison belongs to: plain, sum, count or cross_question."""
    left = atom.get("left") or {}
    right = atom.get("right") or {}
    if left.get("aggregate"):
        return str(left["aggregate"])
    if right.get("question_id"):
        return "cross_question"
    return "plain"


def _conditions(spec: dict):
    """(where, condition or None, raw text) for every guard and every rule."""
    for q in spec.get("questions") or []:
        guard = q.get("guard") or {}
        if guard:
            yield (q["question_id"], guard.get("condition"),
                   "; ".join(guard.get("raw_texts") or []))
    for r in spec.get("rules") or []:
        yield r["rule_id"], r.get("when"), r.get("when_unread") or ""


def _supports(table: dict, atom: dict) -> bool:
    return atom.get("op") in table.get(_shape(atom), frozenset())


def test_designer(spec: dict) -> list[Finding]:
    findings: list[Finding] = []
    for q in spec.get("questions") or []:
        kind = (q.get("kind") or "").strip().lower()
        if kind not in b2_witness.SUPPORTED_KINDS:
            findings.append(Finding(
                3, q["question_id"],
                f"question kind {kind!r} gets no answer, so every journey "
                f"through it stops there"))
            continue
        if kind in DISPLAY_KINDS:
            continue  # nothing to answer, so nothing to bind
        lime_type = survey_loader._TYPE_MAP.get(kind)
        if lime_type and lime_type not in VALUE_KIND_BY_TYPE:
            findings.append(Finding(
                3, q["question_id"],
                f"LimeSurvey type {lime_type!r} has no field binding, so its "
                f"answers cannot be written into the survey"))

    for where, condition, raw in _conditions(spec):
        if condition is None:
            findings.append(Finding(
                3, where, f"condition not read, so it cannot be tested: {raw!r}",
                blocking=False))
            continue
        for atom in _atoms(condition):
            solvable = _supports(b2_witness.SUPPORTED_CONDITIONS, atom)
            predictable = _supports(b3_oracle.SUPPORTED_CONDITIONS, atom)
            if solvable and predictable:
                continue
            why = " and ".join(
                part for part, ok in (("the solver cannot build answers for it", solvable),
                                      ("the oracle cannot predict it", predictable))
                if not ok)
            findings.append(Finding(
                3, where,
                f"no test for {atom.get('source_text') or raw!r}: {why}",
                blocking=False))
    return findings


def respondent_bot(spec: dict) -> list[Finding]:
    findings: list[Finding] = []
    for q in spec.get("questions") or []:
        kind = (q.get("kind") or "").strip().lower()
        if kind in DISPLAY_KINDS:
            continue  # the bot only presses Next
        value_kind = VALUE_KIND_BY_TYPE.get(survey_loader._TYPE_MAP.get(kind, ""))
        if value_kind and value_kind not in FILLABLE_VALUE_KINDS:
            findings.append(Finding(
                4, q["question_id"],
                f"cannot fill a {value_kind!r} field, so it cannot answer {kind!r}"))
    return findings


def survey_builder(spec: dict) -> list[Finding]:
    return [Finding(2, gap.where, gap.problem + (f": {gap.detail}" if gap.detail else ""),
                    gap.blocking)
            for gap in survey_builder_gaps(spec)]


def check_spec(spec: dict) -> list[Finding]:
    return [*survey_builder(spec), *test_designer(spec), *respondent_bot(spec)]


def check(directory: str | Path) -> list[Finding]:
    folder = agent1_dir(directory)
    if not (folder / survey_loader.CANONICAL_FILE).exists():
        return [Finding(2, survey_loader.CANONICAL_FILE, f"not found in {folder}")]
    return check_spec(survey_loader.read_canonical(folder))


def report(findings: list[Finding], agents=tuple(AGENTS)) -> str:
    lines = []
    for number in agents:
        name = AGENTS[number]
        mine = [f for f in findings if f.agent == number]
        blocking = sum(f.blocking for f in mine)
        if not mine:
            status = "ready"
        elif blocking:
            status = f"{blocking} blocking, {len(mine) - blocking} note(s)"
        else:
            status = f"ready, {len(mine)} note(s)"
        lines.append(f"Agent {number} {name}: {status}")
        lines.extend(str(f) for f in sorted(mine, key=lambda f: not f.blocking))
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    findings = check(sys.argv[1])
    print(report(findings))
    return 1 if any(f.blocking for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
