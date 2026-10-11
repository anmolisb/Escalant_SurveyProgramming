"""Stage 5 — extraction quality check.

Audits Stage 4's output against what it was produced from. **Audits, not
re-extracts**: a second independent extraction tends to repeat the first one's
mistakes, so it agrees with a wrong answer instead of catching it.

Every check here is deterministic. No model is called, nothing is inferred, and
the same inputs always produce the same findings — which is what makes this
usable as a gate rather than as advice.

Six checks:

    source_coverage        every block Stage 1 read is accounted for
    row_accounting         every Stage 3 row became a Stage 4 object
    content_fidelity       each question and rule says what its Stage 3 row says
    reference_integrity    every identifier points at something that exists
    condition_consistency  scenarios treat identical conditions identically
    piping_symmetry        piped questions are validated the way their peers are

What is deliberately NOT here: anything needing a condition to be evaluated.
Deciding whether "Q3 != 'None/currently not using'" holds means parsing it, and
parsing it is Part 2's job. `condition_consistency` gets at the same defect
without an evaluator, by comparing condition text for equality.
"""

from __future__ import annotations

import json
import re

from .models import (
    AuditFinding,
    DirectiveKind,
    FlagSeverity,
    FlagTarget,
    SectionScore,
    Stage1Document,
    Stage2Blocks,
    Stage3Block,
    Stage5Audit,
    TargetHeading,
)
from .stage4_deep_parse import (
    _JSON_OBJECT,
    _LABELLED_LINES,
    _MATRIX_PART,
    _ROUTING_HINTS,
    _value,
)

#: From the README. Small sections get 100% because a percentage over four rows
#: swings too wildly to mean anything.
_THRESHOLDS = {
    TargetHeading.QUESTIONNAIRE: 0.95,
    TargetHeading.ROUTING_AND_TERMINATION: 0.95,
    TargetHeading.ACCEPTANCE_TEST_SCENARIOS: 1.0,
    TargetHeading.COMPLETION_MESSAGES: 1.0,
    TargetHeading.QUOTA_CONTROLS: 1.0,
    TargetHeading.STUDY_SPECIFICATION: 1.0,
    TargetHeading.PROGRAMMING_AND_QA: 1.0,
}

#: Destinations that name a place in the flow rather than a question or an
#: ending. Recognised so they are reported as untyped rather than as missing.
_SENTINEL_DESTINATIONS = {"CURRENT_QUESTION", "NEXT", "END", "SAME"}

#: An identifier inside prose: a question id, a rule id, a disposition code.
_IDENTIFIER = re.compile(r"\b([A-Z][A-Za-z0-9_]{1,})\b")

#: Words that look like identifiers but are ordinary prose at the start of a
#: sentence. Checked case-sensitively, so "Quota" matches but "QUOTA_AGE" does not.
_PROSE_WORDS = {
    "Quota", "Store", "Capture", "Record", "Reject", "Produce", "Do", "The",
    "This", "All", "Show", "Business", "Target", "Mode", "Estimated", "General",
    "Purchased", "Understand", "Self", "Not", "Aware", "None", "Yes", "No",
}


def _finding(check, severity, finding, *, target=None, evidence=None):
    return AuditFinding(
        check=check,
        severity=severity,
        finding=finding,
        target=target,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# 1. Source coverage — did anything the document said get dropped?
# ---------------------------------------------------------------------------


def check_source_coverage(
    document: Stage1Document, stage2: Stage2Blocks
) -> list[AuditFinding]:
    """Account for every block Stage 1 read.

    This is the check that would have caught C02's missing quota section on the
    day it went missing. A block is accounted for if it sits under a matched
    heading, or under an unmatched one that was kept anyway. Anything else was
    read from the document and then quietly went nowhere.
    """
    findings: list[AuditFinding] = []
    seen: set[int] = set()

    for block in stage2.blocks:
        seen.add(block.heading_order)
        seen.update(b.order for b in block.blocks)

    for section in stage2.unclassified:
        seen.add(section.heading_order)
        seen.update(b.order for b in section.blocks)
        findings.append(
            _finding(
                "source_coverage",
                FlagSeverity.WARNING,
                (
                    f"Section {section.heading_text!r} matched no target. Its "
                    f"{len(section.blocks)} block(s) are preserved but nothing "
                    "has parsed them."
                ),
                target=FlagTarget(kind="section", id=section.heading_text),
                evidence="; ".join(
                    getattr(b, "text", "")[:80] for b in section.blocks[:3]
                ),
            )
        )

    unaccounted = [b for b in document.blocks if b.order not in seen]
    if unaccounted:
        findings.append(
            _finding(
                "source_coverage",
                FlagSeverity.WARNING,
                (
                    f"{len(unaccounted)} block(s) sit outside every heading and "
                    "reached no stage. Content before the first heading is not "
                    "captured by any target."
                ),
                target=FlagTarget(kind="document", id=document.source),
                evidence="; ".join(
                    getattr(b, "text", "(table)")[:60] for b in unaccounted[:4]
                ),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# 2. Row accounting — did every transcribed row become an object?
# ---------------------------------------------------------------------------

_TARGET_KEYS = {
    TargetHeading.QUESTIONNAIRE: ("questions", "id"),
    TargetHeading.ROUTING_AND_TERMINATION: ("routing", "rule"),
    TargetHeading.ACCEPTANCE_TEST_SCENARIOS: ("scenarios", "id"),
    TargetHeading.COMPLETION_MESSAGES: ("messages", "code"),
    TargetHeading.QUOTA_CONTROLS: ("quotas", "text"),
    TargetHeading.STUDY_SPECIFICATION: ("study", "text"),
    TargetHeading.PROGRAMMING_AND_QA: ("programming", "text"),
}


def check_row_accounting(
    stage3: list[Stage3Block], parsed: dict
) -> tuple[list[SectionScore], list[AuditFinding]]:
    """Compare what Stage 3 transcribed against what Stage 4 produced.

    A row that goes in and no object that comes out is silent data loss, and an
    object with no identifier cannot be referred to by anything downstream.
    """
    scores: list[SectionScore] = []
    findings: list[AuditFinding] = []

    for block in stage3:
        key, id_field = _TARGET_KEYS[block.target]
        objects = parsed.get(key, [])
        identified = sum(1 for o in objects if (getattr(o, id_field, "") or "").strip())
        rows_in = len(block.rows)
        threshold = _THRESHOLDS[block.target]
        # A matched section with no rows scores zero, not one. It was found in
        # the document and produced nothing, which is a failure however you
        # divide it — and reporting it as a pass beside a blocking finding
        # about the same section reads as a contradiction.
        score = identified / rows_in if rows_in else 0.0
        passed = bool(rows_in) and score >= threshold
        scores.append(
            SectionScore(
                target=block.target,
                rows_in=rows_in,
                objects_out=len(objects),
                identified=identified,
                score=round(score, 4),
                threshold=threshold,
                passed=passed,
            )
        )
        if rows_in == 0:
            findings.append(
                _finding(
                    "row_accounting",
                    FlagSeverity.BLOCKING,
                    (
                        f"{block.target.value} was matched in the document but "
                        "transcribed no rows, so everything downstream that "
                        "refers to it will fail to resolve."
                    ),
                    target=FlagTarget(kind="section", id=block.target.value),
                )
            )
            continue

        if not passed:
            findings.append(
                _finding(
                    "row_accounting",
                    FlagSeverity.BLOCKING,
                    (
                        f"{block.target.value}: {identified} of {rows_in} "
                        f"transcribed rows produced an identified object "
                        f"({score:.0%}, threshold {threshold:.0%})."
                    ),
                    target=FlagTarget(kind="section", id=block.target.value),
                )
            )

    for scenario in parsed.get("scenarios", []):
        if scenario.parse_errors:
            findings.append(
                _finding(
                    "row_accounting",
                    FlagSeverity.BLOCKING,
                    f"Scenario {scenario.id} did not parse cleanly.",
                    target=FlagTarget(kind="scenario", id=scenario.id),
                    evidence="; ".join(scenario.parse_errors),
                )
            )
    return scores, findings


# ---------------------------------------------------------------------------
# 2b. Content fidelity - does each object say what its row says?
# ---------------------------------------------------------------------------
#
# Row accounting counts objects; this compares their content. Stage 3 is a
# literal copy of the document's cells, so every question and rule can be held
# against the row it came from: an altered wording, a lost option, a changed
# validation bound or a dropped instruction all show here, where a count would
# pass them. Column roles, matrix labels and instruction labels are read with
# Stage 4's own definitions, so both stages agree on the document's notation.

#: `Validate:` JSON keys and the Question field each lands on. A key not listed
#: here is kept in `other_attributes` under its own name.
_VALIDATION_FIELDS = {
    "min_length": "min_length",
    "max_length": "max_length",
    "min": "min_value",
    "max": "max_value",
    "min_selections": "min_selections",
    "exclusive_option": "exclusive_option",
    "sum": "sum_to",
}


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _option_text_left(cell: str, question) -> str:
    """What remains of the options cell once every option label and code the
    question holds is taken out, along with matrix part labels."""
    parts = []
    for segment in re.split(r"\n|\|\|", cell):
        match = _MATRIX_PART.match(segment)
        parts.append(match.group(2) if match else segment)
    rest = _norm(" ".join(parts))
    for option in [*question.options, *question.matrix_rows]:
        for piece in (option.label, option.code):
            if piece:
                rest = rest.replace(_norm(piece), " ", 1)
    return _norm(rest)


def _question_differences(row: dict, question) -> list[str]:
    found: list[str] = []
    for role in ("id", "wording", "type"):
        cell, got = _norm(_value(row, role)), _norm(getattr(question, role))
        if cell != got:
            found.append(f"{role}: QRE says {cell!r}, Stage 4 has {got!r}")

    options_cell = _value(row, "options")
    for option in [*question.options, *question.matrix_rows]:
        for piece in (option.label, option.code):
            if piece and _norm(piece) not in _norm(options_cell):
                found.append(f"option {piece!r} is not in the QRE's options cell")
    left = _option_text_left(options_cell, question)
    if re.search(r"[A-Za-z0-9]", left):
        found.append(f"options cell text missing from Stage 4: {left!r}")

    carried = [
        question.display_condition or "",
        question.dynamic_option_source or "",
        *question.other_attributes.get("other_instructions", []),
    ]
    flags_set = {
        DirectiveKind.ALWAYS_SHOW: True,
        DirectiveKind.RANDOMIZE: question.randomize is True,
        DirectiveKind.OPTIONAL: question.optional is True,
        DirectiveKind.MANDATORY: question.optional is False,
    }
    for line in (l.strip() for l in _value(row, "display").split("\n")):
        if not line:
            continue
        payload = _JSON_OBJECT.search(line)
        if payload and "validate" in line.lower():
            try:
                stated = json.loads(payload.group(0))
            except json.JSONDecodeError:
                continue  # Stage 4 already flags unreadable validation JSON
            for key, value in stated.items():
                field = _VALIDATION_FIELDS.get(key)
                got = (getattr(question, field) if field
                       else question.other_attributes.get(key))
                if got != value:
                    found.append(f"validation {key}: QRE says {value!r}, Stage 4 has {got!r}")
            continue
        kind = next((k for pattern, k, _ in _LABELLED_LINES if pattern.match(line)), None)
        ok = flags_set.get(kind)
        if ok is None:
            ok = any(c and _norm(c) in _norm(line) for c in carried)
        if not ok:
            found.append(f"instruction missing from Stage 4: {line!r}")
    return found


def _rule_differences(row: dict, rule) -> list[str]:
    found: list[str] = []
    for role, field in (("id", "rule"), ("display", "condition_raw"),
                        ("action", "action"), ("destination", "destination")):
        cell = _norm(_value(row, role, _ROUTING_HINTS))
        got = _norm(getattr(rule, field))
        if cell != got:
            found.append(f"{field}: QRE says {cell!r}, Stage 4 has {got!r}")
    return found


def check_content_fidelity(stage3: list[Stage3Block], parsed: dict) -> list[AuditFinding]:
    """Hold every question and routing rule against the Stage 3 row it came from.

    Rows and objects are paired by position. Where the counts differ,
    row accounting has already reported it and the pairing is skipped rather
    than compared out of step.
    """
    findings: list[AuditFinding] = []
    pairs = (
        (TargetHeading.QUESTIONNAIRE, "questions", "question", "id", _question_differences),
        (TargetHeading.ROUTING_AND_TERMINATION, "routing", "rule", "rule", _rule_differences),
    )
    for target, key, kind, id_field, compare in pairs:
        block = next((b for b in stage3 if b.target is target), None)
        objects = parsed.get(key, [])
        if block is None or len(block.rows) != len(objects):
            continue
        for row, obj in zip(block.rows, objects):
            for difference in compare(row, obj):
                findings.append(
                    _finding(
                        "content_fidelity",
                        FlagSeverity.BLOCKING,
                        difference,
                        target=FlagTarget(kind=kind, id=getattr(obj, id_field) or "?"),
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# 3. Reference integrity — does every identifier point at something real?
# ---------------------------------------------------------------------------


def check_reference_integrity(parsed: dict) -> list[AuditFinding]:
    """Resolve every identifier the artifacts mention.

    Routing destinations, the identifiers a scenario expects, and any code named
    in a prose statement all have to name a question that exists or an ending
    that exists. One that names neither is a hole in the extraction or in the
    QRE itself, and either way somebody needs to know.
    """
    findings: list[AuditFinding] = []
    question_ids = {q.id for q in parsed.get("questions", []) if q.id}
    disposition_codes = {m.code for m in parsed.get("messages", []) if m.code}
    rule_ids = {r.rule for r in parsed.get("routing", []) if r.rule}
    known = question_ids | disposition_codes | rule_ids

    # When no endings came out at all, every destination looks broken. That is
    # one failure upstream, not fifty here: report it once and check only what
    # can still be checked.
    if not disposition_codes:
        findings.append(
            _finding(
                "reference_integrity",
                FlagSeverity.BLOCKING,
                (
                    "No endings were extracted, so no destination or expected "
                    "outcome that names one can be resolved. Checks needing them "
                    "were skipped rather than reported as broken references."
                ),
                target=FlagTarget(
                    kind="section", id=TargetHeading.COMPLETION_MESSAGES.value
                ),
            )
        )

    for rule in parsed.get("routing", []):
        destination = (rule.destination or "").strip()
        if not destination:
            findings.append(
                _finding(
                    "reference_integrity",
                    FlagSeverity.BLOCKING,
                    f"Rule {rule.rule} has no destination.",
                    target=FlagTarget(kind="rule", id=rule.rule),
                )
            )
        elif destination in _SENTINEL_DESTINATIONS:
            findings.append(
                _finding(
                    "reference_integrity",
                    FlagSeverity.WARNING,
                    (
                        f"Rule {rule.rule} points at {destination!r}, which names "
                        "a position in the flow rather than a question or an "
                        "ending. The destination column mixes three kinds of "
                        "thing, so a reader has to guess which is meant."
                    ),
                    target=FlagTarget(kind="rule", id=rule.rule),
                    evidence=rule.condition_raw,
                )
            )
        elif destination not in known and disposition_codes:
            findings.append(
                _finding(
                    "reference_integrity",
                    FlagSeverity.BLOCKING,
                    (
                        f"Rule {rule.rule} points at {destination!r}, which is "
                        "neither a question nor an ending in this QRE."
                    ),
                    target=FlagTarget(kind="rule", id=rule.rule),
                    evidence=rule.condition_raw,
                )
            )

    for scenario in parsed.get("scenarios", []):
        for identifier in scenario.input_question_ids:
            if identifier not in question_ids:
                findings.append(
                    _finding(
                        "reference_integrity",
                        FlagSeverity.BLOCKING,
                        (
                            f"Scenario {scenario.id} answers {identifier!r}, "
                            "which is not a question in this QRE."
                        ),
                        target=FlagTarget(kind="scenario", id=scenario.id),
                    )
                )
        for identifier in scenario.referenced_ids:
            if identifier not in known and disposition_codes:
                findings.append(
                    _finding(
                        "reference_integrity",
                        FlagSeverity.BLOCKING,
                        (
                            f"Scenario {scenario.id} expects {identifier!r}, "
                            "which is neither a question nor an ending."
                        ),
                        target=FlagTarget(kind="scenario", id=scenario.id),
                    )
                )

    # Prose statements name endings too. C02's quota rule terminates at
    # TERM_QUOTA_FULL, an ending the completion messages never define.
    for group in ("quotas", "study", "programming"):
        for statement in parsed.get(group, []):
            for identifier in _IDENTIFIER.findall(statement.text):
                if identifier in _PROSE_WORDS or identifier in known:
                    continue
                if "_" not in identifier and not identifier.isupper():
                    continue  # ordinary capitalised prose, not a code
                findings.append(
                    _finding(
                        "reference_integrity",
                        FlagSeverity.WARNING,
                        (
                            f"{identifier!r} is named in a {group} statement but "
                            "is not a question or an ending in this QRE."
                        ),
                        target=FlagTarget(
                            kind="statement", id=statement.code or identifier
                        ),
                        evidence=statement.raw_text,
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# 4. Condition consistency — are identical conditions treated identically?
# ---------------------------------------------------------------------------


def check_condition_consistency(parsed: dict) -> list[AuditFinding]:
    """Catch a scenario that treats one condition two ways.

    Questions sharing a display condition, character for character, must appear
    or not appear together. Where a scenario expects some of them hidden and
    says nothing about the rest, either the scenario is incomplete or the
    conditions are not really the same.

    Nothing is evaluated here. The check is string equality on the condition
    text, which is why it works in Part 1 at all — and it is enough to find the
    defect in C02's scenario T3.
    """
    findings: list[AuditFinding] = []

    by_condition: dict[str, list[str]] = {}
    for question in parsed.get("questions", []):
        condition = (question.display_condition or "").strip()
        if condition:
            by_condition.setdefault(condition, []).append(question.id)
    shared = {c: ids for c, ids in by_condition.items() if len(ids) > 1}
    if not shared:
        return findings

    for scenario in parsed.get("scenarios", []):
        expected = set(scenario.referenced_ids)
        for condition, ids in shared.items():
            named = [i for i in ids if i in expected]
            missing = [i for i in ids if i not in expected]
            if named and missing:
                findings.append(
                    _finding(
                        "condition_consistency",
                        FlagSeverity.BLOCKING,
                        (
                            f"Scenario {scenario.id} names {', '.join(named)} "
                            f"but not {', '.join(missing)}, though all of them "
                            "carry the same display condition and so can only "
                            "appear or not appear together."
                        ),
                        target=FlagTarget(kind="scenario", id=scenario.id),
                        evidence=f"shared condition: {condition}",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# 5. Piping symmetry — is one piped question validated and another not?
# ---------------------------------------------------------------------------


def check_piping_symmetry(parsed: dict) -> list[AuditFinding]:
    """Compare how piped questions are guarded against each other.

    A question whose options are carried from an earlier one can be sent an
    answer that was never offered. Where one such question has a rule rejecting
    that and another does not, the difference is worth surfacing: in C02, Q6 has
    R20 and Q2 has nothing, and so Q2's piping would never be tested.
    """
    findings: list[AuditFinding] = []
    piped = [q for q in parsed.get("questions", []) if q.dynamic_option_source]
    if len(piped) < 2:
        return findings

    guarded, unguarded = [], []
    for question in piped:
        has_rule = any(
            (rule.action or "").strip().lower() == "reject"
            and question.id in f"{rule.condition_raw} {rule.destination}"
            for rule in parsed.get("routing", [])
        )
        (guarded if has_rule else unguarded).append(question.id)

    if guarded and unguarded:
        for question_id in unguarded:
            findings.append(
                _finding(
                    "piping_symmetry",
                    FlagSeverity.WARNING,
                    (
                        f"{question_id} carries a piping instruction but no rule "
                        f"rejects an answer outside the piped set, while "
                        f"{', '.join(guarded)} has one. Its piping would not be "
                        "tested."
                    ),
                    target=FlagTarget(kind="question", id=question_id),
                    evidence=next(
                        q.dynamic_option_source
                        for q in piped
                        if q.id == question_id
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    document: Stage1Document,
    stage2: Stage2Blocks,
    stage3: list[Stage3Block],
    parsed: dict,
) -> Stage5Audit:
    """Run every check and gather the result.

    An empty findings list here means the checks ran and found nothing — which
    is the point of naming them in `checks_run`. Before this stage existed, an
    empty flag list could equally have meant nothing was ever looked at.
    """
    findings: list[AuditFinding] = []
    findings += check_source_coverage(document, stage2)
    scores, row_findings = check_row_accounting(stage3, parsed)
    findings += row_findings
    findings += check_content_fidelity(stage3, parsed)
    findings += check_reference_integrity(parsed)
    findings += check_condition_consistency(parsed)
    findings += check_piping_symmetry(parsed)

    blocking = sum(1 for f in findings if f.severity is FlagSeverity.BLOCKING)
    return Stage5Audit(
        source=document.source,
        checks_run=[
            "source_coverage",
            "row_accounting",
            "content_fidelity",
            "reference_integrity",
            "condition_consistency",
            "piping_symmetry",
        ],
        sections=scores,
        findings=findings,
        blocking=blocking,
        passed=blocking == 0,
    )
