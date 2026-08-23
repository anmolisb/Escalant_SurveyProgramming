"""Part 2 — building the canonical survey specification.

Takes Part 1's artifacts, which record what the QRE says, and produces a reading
of what it means. Part 1's files stay as they are: this is a separate artifact,
so a disagreement about interpretation never costs us the extraction.

Every value added here carries an origin. CLAUDE.md §14 is blunt about why:
never present an inference as if the QRE stated it. Three things in particular
are inferences and are marked as such — when a rule is checked, which rule wins
when two apply, and what a condition means when it names a question the
respondent was never asked.

Deterministic throughout. The one thing here that genuinely needs a model is
reading a pipe out of question wording, such as Q20's "the selected
proposition" meaning the answer to Q19; that is recorded as an open item rather
than guessed.
"""

from __future__ import annotations

import re

from models import (
    AuditFinding,
    CanonicalQuestion,
    CanonicalRule,
    CanonicalSurvey,
    Condition,
    ConditionOp,
    Dependency,
    DependencyKind,
    Destination,
    DestinationKind,
    FlagSeverity,
    FlagTarget,
    Guard,
    GuardAgreement,
    Origin,
    Randomization,
    RandomizationScope,
    RuleKind,
    Semantics,
)
import part2_conditions

#: A question id inside free text, so a pipe instruction such as
#: "Show only brands selected at Q1." can name its source.
_QID = re.compile(r"\b([A-Za-z]{1,4}_?\d+)\b")

#: Destinations naming a place in the flow rather than a thing.
_POSITIONS = {"CURRENT_QUESTION", "NEXT", "END", "SAME"}

_RULE_KINDS = {
    "terminate": RuleKind.TERMINATE,
    "skip": RuleKind.SKIP,
    "show": RuleKind.SHOW,
    "reject": RuleKind.REJECT,
}


def _review(check, severity, finding, *, target=None, evidence=None) -> AuditFinding:
    return AuditFinding(
        check=check,
        severity=severity,
        finding=finding,
        target=target,
        evidence=evidence,
    )


def _referenced_questions(condition: Condition | None, raw: str) -> list[str]:
    """Which questions a condition depends on.

    Read from the tree where there is one. Where the condition could not be
    parsed, fall back to picking ids out of the source text — less precise, but
    an unparsed condition still clearly depends on the questions it names, and
    an evaluation point derived from nothing at all would be worse.
    """
    if condition is None:
        return list(dict.fromkeys(_QID.findall(raw or "")))

    found: list[str] = []

    def walk(node: Condition) -> None:
        for side in (node.left, node.right):
            if side is not None and side.question_id and side.question_id not in found:
                found.append(side.question_id)
        for child in node.operands:
            walk(child)

    walk(condition)
    return found


# ---------------------------------------------------------------------------
# P3-03 — a destination that says what kind of thing it names
# ---------------------------------------------------------------------------


def _destination(raw: str, question_ids: set[str], codes: set[str]) -> Destination:
    value = (raw or "").strip()
    if value in _POSITIONS:
        return Destination(kind=DestinationKind.POSITION, id=value)
    if value in question_ids:
        return Destination(kind=DestinationKind.QUESTION, id=value)
    if value in codes:
        return Destination(kind=DestinationKind.DISPOSITION, id=value)
    return Destination(kind=DestinationKind.UNKNOWN, id=value, origin=Origin.UNKNOWN)


# ---------------------------------------------------------------------------
# P3-04 — one guard per question, from both places the QRE states it
# ---------------------------------------------------------------------------


def _build_guards(parsed: dict, review: list[AuditFinding]) -> dict[str, Guard]:
    """Combine the questionnaire's display conditions with the routing table's
    show rules.

    Combining rather than choosing, because C02 proves neither is complete: Q15's
    condition appears only in the questionnaire, and the routing table - which
    someone might reasonably treat as the authority on routing - simply omits it.
    """
    show_rules: dict[str, list[tuple[str, str]]] = {}
    for rule in parsed.get("routing", []):
        if (rule.action or "").strip().lower() == "show":
            show_rules.setdefault(rule.destination.strip(), []).append(
                (rule.rule, rule.condition_raw)
            )

    guards: dict[str, Guard] = {}
    for question in parsed.get("questions", []):
        stated: list[tuple[str, str]] = []
        if question.display_condition:
            stated.append(("questionnaire", question.display_condition))
        stated.extend(show_rules.get(question.id, []))
        if not stated:
            continue

        texts = [text for _, text in stated]
        sources = [source for source, _ in stated]
        conditions = [part2_conditions.parse(t) for t in texts]
        readable = [c for c in conditions if c is not None]

        normalised = {
            c.model_dump_json(exclude={"source_text", "origin", "confidence"})
            for c in readable
        }
        if len(texts) == 1:
            agreement = GuardAgreement.SINGLE_SOURCE
        elif not readable:
            agreement = GuardAgreement.UNREAD
        elif len(normalised) == 1:
            agreement = GuardAgreement.AGREE
        else:
            agreement = GuardAgreement.DISAGREE
            review.append(
                _review(
                    "guard_disagreement",
                    FlagSeverity.BLOCKING,
                    (
                        f"{question.id} is given two different display "
                        "conditions, and nothing says which is correct."
                    ),
                    target=FlagTarget(kind="question", id=question.id),
                    evidence=" | ".join(
                        f"{source}: {text}" for source, text in stated
                    ),
                )
            )

        if agreement is GuardAgreement.UNREAD:
            review.append(
                _review(
                    "guard_unread",
                    FlagSeverity.WARNING,
                    (
                        f"{question.id}'s display condition is prose and could "
                        "not be read as a condition."
                    ),
                    target=FlagTarget(kind="question", id=question.id),
                    evidence=texts[0],
                )
            )
        elif len(texts) == 1 and sources == ["questionnaire"]:
            review.append(
                _review(
                    "guard_single_source",
                    FlagSeverity.WARNING,
                    (
                        f"{question.id} has a display condition in the "
                        "questionnaire but no matching rule in the routing "
                        "table, so reading only the routing table would miss it."
                    ),
                    target=FlagTarget(kind="question", id=question.id),
                    evidence=texts[0],
                )
            )

        guards[question.id] = Guard(
            condition=readable[0] if readable else None,
            agreement=agreement,
            sources=sources,
            raw_texts=texts,
        )
    return guards


# ---------------------------------------------------------------------------
# P3-06 — piping as a link between two questions
# ---------------------------------------------------------------------------


def _build_dependencies(parsed: dict, review: list[AuditFinding]) -> list[Dependency]:
    """Turn a piping sentence into a link.

    "Show only brands selected at Q1." names its source question, so the link is
    read rather than guessed. Where the sentence names no question, that is
    reported instead.
    """
    dependencies: list[Dependency] = []
    for question in parsed.get("questions", []):
        instruction = (question.dynamic_option_source or "").strip()
        if not instruction:
            continue
        sources = [q for q in _QID.findall(instruction) if q != question.id]
        if not sources:
            review.append(
                _review(
                    "piping_unresolved",
                    FlagSeverity.BLOCKING,
                    (
                        f"{question.id} carries a piping instruction that names "
                        "no source question, so nothing can build it."
                    ),
                    target=FlagTarget(kind="question", id=question.id),
                    evidence=instruction,
                )
            )
            continue
        dependencies.append(
            Dependency(
                from_question=sources[0],
                to_question=question.id,
                kind=DependencyKind.OPTION_SOURCE,
                detail=instruction,
            )
        )

    # A guard is a dependency too: Q7 cannot be decided before Q3 is answered.
    return dependencies


# ---------------------------------------------------------------------------
# P3-07 — what is shuffled, and what is anchored
# ---------------------------------------------------------------------------


def _build_randomization(
    parsed: dict, review: list[AuditFinding]
) -> list[Randomization]:
    entries: list[Randomization] = []
    for question in parsed.get("questions", []):
        if not question.randomize:
            continue
        is_matrix = bool(question.matrix_rows)
        entry = Randomization(
            question_id=question.id,
            scope=RandomizationScope.ROWS if is_matrix else RandomizationScope.OPTIONS,
        )
        if question.exclusive_option:
            # Convention anchors an exclusive option at the bottom. The QRE does
            # not say so, and a silent decision here is the kind that is argued
            # about months later, so it is asked rather than assumed.
            entry.anchored_origin = Origin.AMBIGUOUS
            review.append(
                _review(
                    "randomization_anchoring",
                    FlagSeverity.WARNING,
                    (
                        f"{question.id} shuffles its options and has "
                        f"{question.exclusive_option!r} as an exclusive option. "
                        "Convention keeps such an option at the bottom, but the "
                        "QRE does not say so."
                    ),
                    target=FlagTarget(kind="question", id=question.id),
                    evidence=f"randomize=true, exclusive_option={question.exclusive_option!r}",
                )
            )
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# P3-02 — a scale coded only at its ends
# ---------------------------------------------------------------------------


def _check_partial_codes(parsed: dict, review: list[AuditFinding]) -> None:
    for question in parsed.get("questions", []):
        coded = [o for o in question.options if o.code]
        if not coded or len(coded) == len(question.options):
            continue
        review.append(
            _review(
                "partial_option_codes",
                FlagSeverity.WARNING,
                (
                    f"{question.id} has codes on {len(coded)} of "
                    f"{len(question.options)} options. A bot told to answer by "
                    "code cannot resolve the rest, and inventing the missing "
                    "codes is not allowed."
                ),
                target=FlagTarget(kind="question", id=question.id),
                evidence="; ".join(
                    f"{o.code or '-'}={o.label}" for o in question.options
                ),
            )
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(source: str, parsed: dict) -> CanonicalSurvey:
    review: list[AuditFinding] = []
    question_ids = {q.id for q in parsed.get("questions", []) if q.id}
    codes = {m.code for m in parsed.get("messages", []) if m.code}
    seq_of = {q.id: q.seq for q in parsed.get("questions", []) if q.id}

    guards = _build_guards(parsed, review)
    _check_partial_codes(parsed, review)

    rules: list[CanonicalRule] = []
    for position, rule in enumerate(parsed.get("routing", []), start=1):
        condition = part2_conditions.parse(rule.condition_raw)
        referenced = _referenced_questions(condition, rule.condition_raw)

        # P3-05: check a rule once every question it depends on has been asked.
        # The QRE never states this, and it says plainly not to infer unstated
        # routing - so it is derived, marked inferred, and surfaced for review
        # rather than buried.
        known = [q for q in referenced if q in seq_of and seq_of[q] is not None]
        evaluation_point = max(known, key=lambda q: seq_of[q]) if known else None

        destination = _destination(rule.destination, question_ids, codes)
        if destination.kind is DestinationKind.UNKNOWN and codes:
            review.append(
                _review(
                    "destination_unknown",
                    FlagSeverity.BLOCKING,
                    (
                        f"Rule {rule.rule} points at {destination.id!r}, which "
                        "is neither a question nor an ending."
                    ),
                    target=FlagTarget(kind="rule", id=rule.rule),
                )
            )
        if condition is None and rule.condition_raw.strip():
            review.append(
                _review(
                    "condition_unread",
                    FlagSeverity.WARNING,
                    (
                        f"Rule {rule.rule}'s condition is prose and could not be "
                        "read as a condition. It needs a model to propose one, "
                        "which this parser would then check."
                    ),
                    target=FlagTarget(kind="rule", id=rule.rule),
                    evidence=rule.condition_raw,
                )
            )

        rules.append(
            CanonicalRule(
                rule_id=rule.rule,
                kind=_RULE_KINDS.get(
                    (rule.action or "").strip().lower(), RuleKind.OTHER
                ),
                when=condition,
                when_unread=None if condition else (rule.condition_raw or None),
                destination=destination,
                evaluation_point=evaluation_point,
                precedence=position,
                source_reference=rule.source_reference,
            )
        )

    questions = [
        CanonicalQuestion(
            question_id=q.id, seq=q.seq, guard=guards.get(q.id)
        )
        for q in parsed.get("questions", [])
    ]

    survey = CanonicalSurvey(
        source=source,
        semantics=Semantics(),
        questions=questions,
        rules=rules,
        dependencies=_build_dependencies(parsed, review),
        randomization=_build_randomization(parsed, review),
        review=review,
    )

    # P3-08: the semantics block holds decisions, not readings. Say so once,
    # loudly, rather than letting later stages each assume their own.
    survey.review.append(
        _review(
            "semantics_unconfirmed",
            FlagSeverity.BLOCKING,
            (
                "The semantics block records three decisions the QRE never "
                "states: that a condition naming an unasked question is false, "
                "that the first matching rule wins, and that '==' against a "
                "multi-select compares the whole answer set. Each changes which "
                "questions appear on many routes and needs confirming."
            ),
            target=FlagTarget(kind="survey", id=source),
            evidence=survey.semantics.model_dump_json(),
        )
    )
    return survey
