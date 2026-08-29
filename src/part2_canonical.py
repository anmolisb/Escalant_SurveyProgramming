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
    CanonicalDisposition,
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
    LLMQuota,
    LLMTextPipes,
    Quota,
    QuotaCell,
    Origin,
    Randomization,
    RandomizationScope,
    RuleKind,
    Semantics,
)
from llm import LLMUnavailable, complete
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


def _build_guards(
    parsed: dict,
    review: list[AuditFinding],
    read=None,
) -> dict[str, Guard]:
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
        conditions = [
            (
                read(t, FlagTarget(kind="question", id=question.id), f"{question.id}'s display condition")
                if read
                else part2_conditions.parse(t)
            )
            for t in texts
        ]
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


_PIPE_SYSTEM = """You are given the questions of a survey, in the order they are asked.

Find every question whose WORDING cannot be shown as written without knowing an
answer given earlier, because it refers back to that answer.

The usual sign is a definite reference to something the respondent already
chose: "the chosen ...", "the selected ...", "that you picked", "your earlier
answer". When a question says THE something, and an earlier question is what
decided which something, that is a reference and you should report it.

Qualifies. In this illustration only, the questions are labelled with letters so
they cannot be confused with the ids you will be given:
    AA: Which of these plans would you prefer?
    BB: How much would you pay for the selected plan?
  BB refers to the answer given at AA. Without it, "the selected plan" names
  nothing.

Does not qualify:
    CC: How satisfied are you with your provider?
    DD: Would you recommend your provider?
  Both talk about the same real thing, but neither needs the other's answer in
  order to be displayed.

For each one found, give the id of the question doing the referring, the id of
the earlier question being referred to, and the referring words copied exactly
from the wording.

Report nothing when a question stands on its own. A wrong link makes a question
show the wrong text to a real respondent.
"""


def _build_text_pipes(
    parsed: dict, review: list[AuditFinding]
) -> list[Dependency]:
    """Find wording that quotes an earlier answer.

    The only thing in Part 2 that genuinely needs a model. C02's Q20 asks
    "How appealing is the selected proposition?", which means the answer given
    at Q19 - and no table in the document says so. Nothing but reading the
    sentence can find it.
    """
    questions = [q for q in parsed.get("questions", []) if q.id and q.wording]
    if len(questions) < 2:
        return []

    listing = "\n".join(f"{q.id}: {q.wording}" for q in questions)
    try:
        # A list of objects needs more room than the default allows; running
        # out returns an empty completion, which reads as "found nothing".
        found = complete(_PIPE_SYSTEM, listing, LLMTextPipes, max_tokens=2000)
    except LLMUnavailable as exc:
        review.append(
            _review(
                "text_pipe_unchecked",
                FlagSeverity.WARNING,
                (
                    "Question wording was not checked for references to earlier "
                    f"answers: {exc}"
                ),
                target=FlagTarget(kind="survey", id=parsed.get("source", "")),
            )
        )
        return []

    known = {q.id for q in questions}
    order = {q.id: (q.seq or 0) for q in questions}
    pipes: list[Dependency] = []
    for pipe in found.pipes:
        if not pipe.is_pipe or not pipe.source_question_id:
            continue
        source = pipe.source_question_id.strip()
        target_id = (pipe.target_question_id or "").strip() or next(
            (q.id for q in questions if pipe.phrase and pipe.phrase in q.wording),
            None,
        )

        # The model must name two questions that exist, and the quoting one must
        # come after the quoted one. Each is a way a plausible-looking answer can
        # still be wrong. A proposal failing any of them is reported, not
        # dropped: silently discarding it would hide both a model mistake and a
        # real pipe we simply could not confirm.
        problem = None
        if source not in known:
            problem = f"names {source!r}, which is not a question in this QRE"
        elif not target_id or target_id not in known:
            problem = f"does not identify which question does the quoting"
        elif target_id == source:
            problem = "names the same question at both ends"
        elif order.get(target_id, 0) <= order.get(source, 0):
            problem = (
                f"has {target_id} quoting {source}, but {source} is not asked first"
            )
        if problem:
            review.append(
                _review(
                    "text_pipe_rejected",
                    FlagSeverity.WARNING,
                    (
                        "A possible reference to an earlier answer was reported "
                        f"but not accepted: it {problem}."
                    ),
                    target=FlagTarget(kind="question", id=target_id or source),
                    evidence=f"phrase {pipe.phrase!r}, confidence {pipe.confidence:.2f}",
                )
            )
            continue
        pipes.append(
            Dependency(
                from_question=source,
                to_question=target_id,
                kind=DependencyKind.TEXT_PIPE,
                detail=pipe.phrase or "",
                origin=Origin.INFERRED,
            )
        )
        review.append(
            _review(
                "text_pipe_inferred",
                FlagSeverity.WARNING,
                (
                    f"{target_id}'s wording appears to quote the answer given at "
                    f"{source}. No table states this; it was read out of the "
                    "sentence, so it is worth confirming."
                ),
                target=FlagTarget(kind="question", id=target_id),
                evidence=f"{pipe.phrase!r} (confidence {pipe.confidence:.2f})",
            )
        )
    return pipes


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


_QUOTA_SYSTEM = """\
You read one sentence from a questionnaire's quota section into parts.

A quota limits how much of the sample may come from each group of respondents.
A sentence sets a quota when it says which question decides the group, and how
much each group may take.

Give: an id for the quota, whether it is hard or soft exactly as the sentence
says, the id of the question it counts, the answer labels it groups by copied
exactly, one percentage per label in the same order, and the ending code for a
respondent whose group is already full.

The ending is often stated in a DIFFERENT sentence from the one defining the
groups - you are given the whole section so you can find it there. Use it for
every quota in the section unless a quota states its own, different ending.

Some sentences in that section set no quota at all - they only say what happens
when one is full, or that quota status must be recorded. Return is_quota false
for those rather than inventing a quota to fit.

Copy labels exactly from the option list you are given. A label you cannot find
there is a label you should not use.
"""


def _build_quotas(
    parsed: dict, options_by_question: dict, review: list[AuditFinding]
) -> list[Quota]:
    """Read the quota sentences into something that can be built and tested.

    Part 1 captures the sentence whole, which is right - splitting it is
    interpretation. But left as a sentence it is unusable: LimeSurvey cannot
    create a quota without a variable, its values and a limit, the test designer
    cannot write a quota test, and the ending a full quota leads to exists as no
    node at all.

    The model proposes the split and deterministic checks decide. The checks are
    unusually strong here, because the quota names answers that either are or are
    not in the question's own option list, and percentages either total 100 or
    do not.
    """
    statements = parsed.get("quotas", [])
    if not statements:
        return []

    catalogue = "\n".join(
        f"{qid}: " + ", ".join(repr(label) for label in labels)
        for qid, labels in options_by_question.items()
        if labels
    )
    known_dispositions = {m.code for m in parsed.get("messages", []) if m.code}

    # The whole section, so a sentence that only names the full-quota ending -
    # C02 and C01 both put it in a sentence separate from the quota
    # definitions - is visible while a *different* statement in the loop below
    # is being read. Without this, the ending was there in the document and
    # simply never reached the reading that needed it.
    section_text = "\n".join(s.raw_text for s in statements)

    quotas: list[Quota] = []
    for statement in statements:
        try:
            proposal = complete(
                _QUOTA_SYSTEM,
                (
                    f"Whole quota section, for context:\n{section_text}\n\n"
                    f"Sentence to read now: {statement.raw_text}\n\n"
                    f"Answer options:\n{catalogue}"
                ),
                LLMQuota,
                max_tokens=1200,
            )
        except LLMUnavailable as exc:
            review.append(
                _review(
                    "quota_unread",
                    FlagSeverity.BLOCKING,
                    f"A quota sentence could not be read: {exc}",
                    target=FlagTarget(kind="statement", id=statement.code or "quota"),
                    evidence=statement.raw_text,
                )
            )
            continue

        if not proposal.is_quota:
            # Not every sentence in the section sets a quota. C02's third says
            # only what happens when one is full, which is behaviour the rules
            # need but is not a quota in itself.
            continue

        problem = None
        variable = (proposal.variable_question_id or "").strip()
        labels = proposal.cell_labels
        percents = proposal.cell_percents
        available = options_by_question.get(variable) or []

        if variable not in options_by_question:
            problem = f"names {variable!r}, which is not a question in this QRE"
        elif not labels:
            problem = "lists no groups"
        elif len(labels) != len(percents):
            problem = f"gives {len(labels)} groups but {len(percents)} percentages"
        else:
            unknown = [lab for lab in labels if lab not in available]
            if unknown:
                problem = (
                    f"groups by {unknown!r}, which are not answers offered at "
                    f"{variable}"
                )
            elif abs(sum(percents) - 100.0) > 1.0:
                problem = f"percentages total {sum(percents):.0f}, not 100"

        if problem:
            review.append(
                _review(
                    "quota_rejected",
                    FlagSeverity.BLOCKING,
                    (
                        "A quota was proposed but not accepted: it "
                        + problem
                        + ". The sentence is kept as written."
                    ),
                    target=FlagTarget(kind="statement", id=statement.code or variable),
                    evidence=statement.raw_text,
                )
            )
            continue

        option_ids = {}
        for question in parsed.get("questions", []):
            if question.id == variable:
                option_ids = {o.label: o.option_id for o in question.options}

        on_full = (proposal.on_full or "").strip() or None
        if on_full and on_full not in known_dispositions:
            review.append(
                _review(
                    "quota_ending_missing",
                    FlagSeverity.WARNING,
                    (
                        f"Quota {proposal.quota_id or variable} sends a full "
                        f"group to {on_full!r}, which no completion message "
                        "defines. Nothing can show that respondent anything."
                    ),
                    target=FlagTarget(kind="disposition", id=on_full),
                    evidence=statement.raw_text,
                )
            )

        quotas.append(
            Quota(
                quota_id=proposal.quota_id or statement.code or variable,
                enforcement=(proposal.enforcement or "unknown").strip().lower(),
                variable_question_id=variable,
                cells=[
                    QuotaCell(
                        option_label=label,
                        option_id=option_ids.get(label),
                        target_percent=percent,
                    )
                    for label, percent in zip(labels, percents)
                ],
                on_full=on_full,
                evaluation_point=variable,
                confidence=proposal.confidence,
                source_text=statement.raw_text,
            )
        )
        review.append(
            _review(
                "quota_inferred",
                FlagSeverity.WARNING,
                (
                    f"Quota {proposal.quota_id or variable} was read out of a "
                    "sentence by a model and passed the checks. Worth a human eye."
                ),
                target=FlagTarget(kind="statement", id=statement.code or variable),
                evidence=f"{statement.raw_text[:70]} -> {variable}, {len(labels)} groups",
            )
        )
    return quotas


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


def _read_condition(
    condition_raw: str,
    options_by_question: dict,
    cache: dict,
    review: list[AuditFinding],
    label: str,
    target: FlagTarget,
) -> Condition | None:
    """Read a condition, falling back to a model proposal the parser then checks.

    Cached by text, because a QRE states the same condition many times over -
    C02 writes "Q1 contains at least one brand" for both Q2 and Q3 - and each
    distinct wording is worth exactly one call.
    """
    text = (condition_raw or "").strip()
    if not text:
        return None
    if text in cache:
        return cache[text]

    condition = part2_conditions.parse(text)
    if condition is None:
        referenced = list(dict.fromkeys(_QID.findall(text)))
        condition, note = part2_conditions.propose(
            text, referenced, options_by_question
        )
        if condition is None:
            review.append(
                _review(
                    "condition_unread",
                    FlagSeverity.WARNING,
                    f"{label} could not be read as a condition: {note}",
                    target=target,
                    evidence=text,
                )
            )
        else:
            review.append(
                _review(
                    "condition_inferred",
                    FlagSeverity.WARNING,
                    (
                        f"{label} was prose, so a model proposed a reading which "
                        "the parser then accepted. Worth a human eye."
                    ),
                    target=target,
                    evidence=f"{text}  ->  {part2_conditions.describe(condition)}",
                )
            )
    cache[text] = condition
    return condition


#: What an ending's id says about the kind of ending it is. Matched as a word
#: so "COMPLETE" is a completion but "TERM_INCOMPLETE_DATA" is not read as one.
_DISPOSITION_KINDS = (
    ("quota", "quota_full"),
    ("term", "screenout"),
    ("screen", "screenout"),
    ("complete", "complete"),
    ("finish", "complete"),
)


def _disposition_kind(disposition_id: str) -> str:
    """Guess what sort of ending this is from its id.

    Only a reading of the name, which is why it is a guess: the QRE names its
    endings by its own convention and nothing states what each one means. Used
    to tell a screenout from a completion when counting routes, never to decide
    behaviour.
    """
    lowered = disposition_id.lower()
    for needle, kind in _DISPOSITION_KINDS:
        if needle in lowered:
            return kind
    return "unknown"


def _build_dispositions(
    parsed: dict, rules: list[CanonicalRule], quotas: list[Quota]
) -> list[CanonicalDisposition]:
    """Every way the survey can end, including the ones nobody defined.

    Two sources. The completion messages give the endings the QRE spells out.
    The rules and quotas give the endings something actually sends people to -
    and those two sets are not the same: C01 and C02 both route quota-full
    respondents to TERM_QUOTA_FULL and then never say what it shows them.

    An ending that is referred to but never defined is kept, marked
    `defined_in_source=False`. It is a real terminal state that a respondent can
    reach, so the graph needs a node for it; leaving it out would make a hole in
    the survey look like a tidy graph.
    """
    dispositions: dict[str, CanonicalDisposition] = {}

    for message in parsed.get("messages", []):
        if not message.code:
            continue
        dispositions[message.code] = CanonicalDisposition(
            disposition_id=message.code,
            kind=_disposition_kind(message.code),
            message=message.message,
            defined_in_source=True,
        )

    referenced = [
        rule.destination.id
        for rule in rules
        if rule.destination.kind is DestinationKind.DISPOSITION
    ]
    referenced += [q.on_full for q in quotas if q.on_full]

    for disposition_id in referenced:
        if disposition_id and disposition_id not in dispositions:
            dispositions[disposition_id] = CanonicalDisposition(
                disposition_id=disposition_id,
                kind=_disposition_kind(disposition_id),
                message=None,
                defined_in_source=False,
            )

    return sorted(dispositions.values(), key=lambda d: d.disposition_id)


def run(source: str, parsed: dict) -> CanonicalSurvey:
    review: list[AuditFinding] = []
    question_ids = {q.id for q in parsed.get("questions", []) if q.id}
    codes = {m.code for m in parsed.get("messages", []) if m.code}
    seq_of = {q.id: q.seq for q in parsed.get("questions", []) if q.id}

    options_by_question = {
        q.id: [o.label for o in q.options] for q in parsed.get("questions", []) if q.id
    }
    cache: dict = {}

    def read(text: str, target: FlagTarget, label: str) -> Condition | None:
        return _read_condition(
            text, options_by_question, cache, review, label, target
        )

    guards = _build_guards(parsed, review, read)
    _check_partial_codes(parsed, review)

    rules: list[CanonicalRule] = []
    for position, rule in enumerate(parsed.get("routing", []), start=1):
        condition = read(
            rule.condition_raw,
            FlagTarget(kind="rule", id=rule.rule),
            f"Rule {rule.rule}",
        )
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

    quotas = _build_quotas(parsed, options_by_question, review)

    survey = CanonicalSurvey(
        source=source,
        semantics=Semantics(),
        questions=questions,
        dispositions=_build_dispositions(parsed, rules, quotas),
        rules=rules,
        dependencies=_build_dependencies(parsed, review)
        + _build_text_pipes(parsed, review),
        randomization=_build_randomization(parsed, review),
        quotas=quotas,
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
