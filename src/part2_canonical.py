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
    CanonicalOption,
    CanonicalQuestion,
    CanonicalScenario,
    CanonicalStatement,
    CanonicalValidation,
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
    OptionSource,
    Quota,
    QuotaCell,
    Origin,
    Randomization,
    RandomizationScope,
    RuleKind,
    ScenarioExpectation,
    ScenarioInput,
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


def _review(
    check, severity, finding, *, target=None, evidence=None, source=None
) -> AuditFinding:
    return AuditFinding(
        check=check,
        severity=severity,
        finding=finding,
        target=target,
        evidence=evidence,
        source_reference=source,
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


def _option_sources(
    parsed: dict, review: list[AuditFinding]
) -> dict[str, OptionSource]:
    """Read each piping sentence once, keyed by the question it narrows.

    "Show only brands selected at Q1." names its source question, so the link is
    read rather than guessed. Where the sentence names no question, that is
    reported instead.

    One reading serves two purposes - the link between the two questions, and
    the note on the narrowed question itself - because two readings of the same
    sentence are two things that can disagree.
    """
    found: dict[str, OptionSource] = {}
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
        found[question.id] = OptionSource(
            from_question=sources[0],
            instruction=instruction,
            source_reference=question.source_reference,
        )
    return found


def _build_dependencies(option_sources: dict[str, OptionSource]) -> list[Dependency]:
    """Turn each piping sentence into a link between two questions."""
    # A guard is a dependency too: Q7 cannot be decided before Q3 is answered.
    # That one is drawn by the graph builder, which already walks every guard.
    return [
        Dependency(
            from_question=source.from_question,
            to_question=question_id,
            kind=DependencyKind.OPTION_SOURCE,
            detail=source.instruction,
            source_reference=source.source_reference,
        )
        for question_id, source in option_sources.items()
    ]


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
                confidence=pipe.confidence,
                source_reference=next(
                    (q.source_reference for q in questions if q.id == target_id),
                    None,
                ),
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
            source_reference=question.source_reference,
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
) -> tuple[list[Quota], list[CanonicalStatement]]:
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

    Not every sentence in the section sets a quota - one might say only what
    happens when a group is full, or that quota status must be logged. Those are
    real requirements and were previously discarded once the model correctly
    said they define no quota; they are now returned alongside the quotas as
    `requirements`, verbatim, rather than folded into a `Quota` that would claim
    a variable and cells the sentence does not give.
    """
    statements = parsed.get("quotas", [])
    if not statements:
        return [], []

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
    requirements: list[CanonicalStatement] = []
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
            # Not every sentence in the section sets a quota - some say only
            # what happens when one is full, or that status must be logged.
            # Real requirements, not quota definitions, so they are carried as
            # statements rather than dropped or forced into a Quota shape.
            requirements.append(
                CanonicalStatement(
                    code=statement.code,
                    label=statement.label,
                    text=statement.text,
                    raw_text=statement.raw_text,
                    source_reference=statement.source_reference,
                )
            )
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
    return quotas, requirements


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
# What the document says about itself, and about how to build it
# ---------------------------------------------------------------------------


def _build_statements(rows) -> list[CanonicalStatement]:
    """Carry a prose section across as statements, unchanged."""
    return [
        CanonicalStatement(
            code=row.code,
            label=row.label,
            text=row.text,
            raw_text=row.raw_text,
            source_reference=row.source_reference,
        )
        for row in rows or []
    ]


def _read_default_mandatory(
    statements: list[CanonicalStatement],
) -> tuple[bool | None, Origin, str]:
    """Find a sentence setting whether an unmarked question must be answered.

    Both fixtures write "All questions are mandatory unless explicitly marked
    optional", and nothing read it, so `mandatory` was defaulted to true on no
    evidence. Read by a fixed rule rather than by a model: a statement naming
    both states sets the default to whichever it names first, since that is the
    one the sentence is about and the other is its exception. A document naming
    neither leaves the default unknown, which is the honest answer.
    """
    for statement in statements:
        lowered = (statement.text or "").lower()
        at_mandatory = lowered.find("mandator")
        at_optional = lowered.find("optional")
        if at_mandatory < 0 or at_optional < 0:
            continue
        return (at_mandatory < at_optional, Origin.DERIVED, statement.text)
    return (None, Origin.UNKNOWN, "")


# ---------------------------------------------------------------------------
# The QRE's own acceptance tests
# ---------------------------------------------------------------------------

#: Operators whose right-hand side is a set of answers rather than a single one.
#: Only these can be under-inclusive in the way `_check_inferred_subsets` looks
#: for; flagging `eq` against one option would flag every ordinary condition.
_SET_OPERATORS = frozenset(
    {
        ConditionOp.IN,
        ConditionOp.NOT_IN,
        ConditionOp.CONTAINS_ANY,
        ConditionOp.CONTAINS_ALL,
        ConditionOp.SET_EQ,
    }
)


def _labels_in(value) -> list[str]:
    """The answer labels a scenario cell names, whatever shape the cell has.

    A cell holds a label, a list of them, or a mapping from label to amount as a
    constant sum does. Numbers and free text name no option and yield nothing.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(k) for k in value]
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str)]
    return []


def _build_scenarios(
    parsed: dict,
    questions_by_id: dict,
    disposition_ids: set[str],
    review: list[AuditFinding],
) -> list[CanonicalScenario]:
    """Carry the document's own acceptance tests across, with references resolved.

    Kept as statements of expected behaviour, never executed here: deciding
    whether a scenario holds means evaluating conditions against an answer set,
    which is the test designer's job and not this layer's.

    What this does add is resolution. A scenario names answers and questions by
    label and id; both are checked against the survey that was actually read, so
    a scenario naming something the questionnaire does not offer is reported
    rather than passed downstream to fail confusingly much later.
    """
    scenarios: list[CanonicalScenario] = []
    for row in parsed.get("scenarios", []):
        inputs: list[ScenarioInput] = []
        for question_id, value in (row.key_inputs or {}).items():
            question = questions_by_id.get(question_id)
            if question is None:
                inputs.append(
                    ScenarioInput(
                        question_id=question_id, value=value, unknown_question=True
                    )
                )
                review.append(
                    _review(
                        "scenario_unknown_question",
                        FlagSeverity.BLOCKING,
                        (
                            f"Scenario {row.id} supplies an answer for "
                            f"{question_id}, which this questionnaire does not "
                            "ask."
                        ),
                        target=FlagTarget(kind="scenario", id=row.id),
                        evidence=f"{question_id}: {value!r}",
                        source=row.source_reference,
                    )
                )
                continue

            wanted = _labels_in(value)
            by_label = {o.label: o.option_id for o in question.options}
            by_label.update({o.label: o.option_id for o in question.matrix_rows})
            option_ids = None
            if wanted and by_label:
                found = [by_label.get(label) for label in wanted]
                if all(found):
                    option_ids = [f for f in found if f]
                else:
                    missing = [
                        label for label, hit in zip(wanted, found) if not hit
                    ]
                    review.append(
                        _review(
                            "scenario_option_unresolved",
                            FlagSeverity.WARNING,
                            (
                                f"Scenario {row.id} answers {question_id} with "
                                f"{missing!r}, which {question_id} does not "
                                "offer."
                            ),
                            target=FlagTarget(kind="scenario", id=row.id),
                            evidence=f"{question_id}: {value!r}",
                            source=row.source_reference,
                        )
                    )
            inputs.append(
                ScenarioInput(
                    question_id=question_id, value=value, option_ids=option_ids
                )
            )

        expectations: list[ScenarioExpectation] = []
        for kind, value in (row.expected_outcome or {}).items():
            targets = [t for t in _labels_in(value)]
            kinds = []
            for target in targets:
                if target in questions_by_id:
                    kinds.append("question")
                elif target in disposition_ids:
                    kinds.append("disposition")
                else:
                    kinds.append("unknown")
                    review.append(
                        _review(
                            "scenario_reference_unresolved",
                            FlagSeverity.WARNING,
                            (
                                f"Scenario {row.id} expects {target!r}, which is "
                                "neither a question nor an ending in this QRE."
                            ),
                            target=FlagTarget(kind="scenario", id=row.id),
                            evidence=f"{kind}: {value!r}",
                            source=row.source_reference,
                        )
                    )
            expectations.append(
                ScenarioExpectation(
                    kind=kind, targets=targets, target_kinds=kinds, value=value
                )
            )

        if row.parse_errors:
            review.append(
                _review(
                    "scenario_parse_errors",
                    FlagSeverity.WARNING,
                    (
                        f"Scenario {row.id} was not fully read out of its row, "
                        "so what it asks for is incomplete."
                    ),
                    target=FlagTarget(kind="scenario", id=row.id),
                    evidence="; ".join(row.parse_errors),
                    source=row.source_reference,
                )
            )

        scenarios.append(
            CanonicalScenario(
                scenario_id=row.id,
                purpose=row.purpose or "",
                inputs=inputs,
                expectations=expectations,
                inputs_raw=row.key_inputs or {},
                expected_raw=row.expected_outcome or {},
                parse_errors=list(row.parse_errors or []),
                source_reference=row.source_reference,
            )
        )
    return scenarios


def _check_inferred_subsets(
    survey: CanonicalSurvey, questions_by_id: dict, review: list[AuditFinding]
) -> None:
    """Say so when a model's reading of a condition leaves answers out.

    A prose condition such as "Q1 contains at least one brand" has to be turned
    into a list of options, and the model decides which ones count. On C01 it
    reads that as three of Q1's four brands, leaving out "Independent provider"
    - which may be right, and may be a respondent wrongly sent down a different
    path. Nothing in the QRE settles it.

    The reading is kept, because the parser accepted it and a refusal here would
    lose a condition that is probably correct. What is added is the fact that it
    is a choice: a set-valued condition that a model proposed, naming only some
    of the answers the question offers, gets the omitted ones named in the
    review queue so a person decides rather than nobody.
    """

    def walk(condition, where: str, target: FlagTarget) -> None:
        if condition is None:
            return
        left, right = condition.left, condition.right
        if (
            condition.origin is Origin.INFERRED
            and condition.op in _SET_OPERATORS
            and left is not None
            and right is not None
            and right.option_ids
        ):
            question = questions_by_id.get(left.question_id or "")
            if question is not None:
                # An exclusive option is excluded by construction - "at least
                # one brand" cannot mean "None of these" - so leaving it out is
                # not a choice anyone needs to review.
                offered = [
                    o.option_id
                    for o in question.options
                    if o.option_id and o.label != question.exclusive_option
                ]
                omitted = [
                    o.label
                    for o in question.options
                    if o.option_id
                    and o.option_id in offered
                    and o.option_id not in right.option_ids
                ]
                if omitted and len(right.option_ids) < len(offered):
                    review.append(
                        _review(
                            "inferred_condition_partial_options",
                            FlagSeverity.WARNING,
                            (
                                f"{where} was read as naming "
                                f"{len(right.option_ids)} of "
                                f"{left.question_id}'s {len(offered)} "
                                f"selectable answers, leaving out {omitted!r}. "
                                "A model chose which ones count and the QRE "
                                "does not say."
                            ),
                            target=target,
                            evidence=condition.source_text,
                        )
                    )
        for child in condition.operands:
            walk(child, where, target)

    for rule in survey.rules:
        walk(
            rule.when,
            f"Rule {rule.rule_id}",
            FlagTarget(kind="rule", id=rule.rule_id),
        )
    for question in survey.questions:
        if question.guard is not None:
            walk(
                question.guard.condition,
                f"{question.question_id}'s display condition",
                FlagTarget(kind="question", id=question.question_id),
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
            source_reference=message.source_reference,
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


def _canonical_options(options, exclusive_label: str | None) -> list:
    """Carry Part 1's options across, marking the exclusive one.

    The QRE names its exclusive option by label. Matching it here means nothing
    downstream has to compare loose text to work out which option cannot be
    combined with the others.
    """
    carried = []
    for option in options:
        carried.append(
            CanonicalOption(
                option_id=option.option_id,
                code=option.code,
                label=option.label,
                numeric_value=option.numeric_value,
                is_exclusive=bool(exclusive_label)
                and option.label == exclusive_label,
            )
        )
    return carried


#: The key Stage 4 uses for a matrix that must be answered on every row. Named
#: here rather than left in the leftovers because it decides whether a
#: part-filled grid is refused, which is a validation rule and a test.
_REQUIRE_EACH_ROW = "require_each_row"


def _canonical_validation(question, semantics: Semantics) -> CanonicalValidation:
    """What counts as an acceptable answer, with the exclusive option resolved.

    Every question gets one. An all-null validation says the QRE stated no
    constraint on this answer; it used to be returned as None, which made
    "nothing was stated" look the same as "this field was never populated" and
    left every consumer handling two shapes for one fact.

    `mandatory` is the part that had to change. It was `not question.optional`,
    which quietly asserted that every question carrying any validation at all
    was required - true for these two documents, but asserted from nothing in
    them. Now: a question the QRE marks optional is not required and says so was
    extracted; otherwise the survey-wide default applies if the document states
    one, and where it states none the answer is null, not true.
    """
    exclusive_id = None
    if question.exclusive_option:
        exclusive_id = next(
            (
                o.option_id
                for o in question.options
                if o.label == question.exclusive_option
            ),
            None,
        )

    if question.optional:
        mandatory, mandatory_origin = False, Origin.EXTRACTED
    elif semantics.default_mandatory is not None:
        mandatory, mandatory_origin = semantics.default_mandatory, Origin.DERIVED
    else:
        mandatory, mandatory_origin = None, Origin.UNKNOWN

    require_each_row = question.other_attributes.get(_REQUIRE_EACH_ROW)

    return CanonicalValidation(
        min_length=question.min_length,
        max_length=question.max_length,
        min_value=question.min_value,
        max_value=question.max_value,
        min_selections=question.min_selections,
        sum_to=question.sum_to,
        require_each_row=(
            bool(require_each_row) if require_each_row is not None else None
        ),
        exclusive_option_id=exclusive_id,
        exclusive_option_label=question.exclusive_option,
        mandatory=mandatory,
        mandatory_origin=mandatory_origin,
    )


def _resolve_option_references(
    survey, questions_by_id: dict, review: list
) -> None:
    """Point every value in a condition at the option it names.

    A condition arrives comparing against text - "No", "None of these" - because
    that is how the QRE writes it. Every option already carries a stable id, and
    this is what joins the two, so a consumer can act on the id and never on the
    label. Text that changes with any rewording is exactly the fragility the ids
    were introduced to remove, and leaving conditions matching on text would
    have kept it in the one place it matters most.

    A value naming no option is reported. It means the condition refers to an
    answer the question does not offer, which is a broken reference in the QRE
    or a misreading of it - either way somebody needs to know.
    """

    def resolve(condition, where: str) -> None:
        if condition is None:
            return
        left, right = condition.left, condition.right
        if left is not None and left.question_id and right is not None:
            question = questions_by_id.get(left.question_id)
            # Only options can be resolved. A numeric comparison such as
            # "S3 < 18", or a comparison against another question, names none.
            if question and right.question_id is None:
                wanted = None
                if right.values:
                    wanted = list(right.values)
                elif right.text is not None:
                    wanted = [right.text]
                if wanted:
                    by_label = {o.label: o.option_id for o in question.options}
                    by_label.update(
                        {o.label: o.option_id for o in question.matrix_rows}
                    )
                    if by_label:
                        found = [by_label.get(value) for value in wanted]
                        if all(found):
                            right.option_ids = [f for f in found if f]
                        else:
                            missing = [
                                value
                                for value, hit in zip(wanted, found)
                                if not hit
                            ]
                            review.append(
                                _review(
                                    "condition_option_unresolved",
                                    FlagSeverity.BLOCKING,
                                    (
                                        f"{where} compares "
                                        f"{left.question_id} against "
                                        f"{missing!r}, which {left.question_id} "
                                        "does not offer as an answer."
                                    ),
                                    target=FlagTarget(
                                        kind="question", id=left.question_id
                                    ),
                                    evidence=condition.source_text,
                                )
                            )
        for child in condition.operands:
            resolve(child, where)

    for rule in survey.rules:
        resolve(rule.when, f"Rule {rule.rule_id}")
    for question in survey.questions:
        if question.guard is not None:
            resolve(question.guard.condition, f"{question.question_id}'s guard")


def run(source: str, parsed: dict) -> CanonicalSurvey:
    review: list[AuditFinding] = []
    question_ids = {q.id for q in parsed.get("questions", []) if q.id}
    codes = {m.code for m in parsed.get("messages", []) if m.code}
    seq_of = {q.id: q.seq for q in parsed.get("questions", []) if q.id}

    # The study section can set whether an unmarked question must be answered,
    # so it is read before any question is built.
    metadata = _build_statements(parsed.get("study", []))
    requirements = _build_statements(parsed.get("programming", []))
    default_mandatory, default_origin, default_source = _read_default_mandatory(
        metadata
    )
    semantics = Semantics(
        default_mandatory=default_mandatory,
        default_mandatory_origin=default_origin,
        default_mandatory_source=default_source,
    )

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

    option_sources = _option_sources(parsed, review)
    questions = [
        CanonicalQuestion(
            question_id=q.id,
            seq=q.seq,
            kind=q.type,
            wording=q.wording,
            options=_canonical_options(q.options, q.exclusive_option),
            matrix_rows=_canonical_options(q.matrix_rows, None),
            validation=_canonical_validation(q, semantics),
            guard=guards.get(q.id),
            option_source=option_sources.get(q.id),
            # Whatever Stage 4 read but no field here names. Q9's answer scale
            # and Q19's note about showing concepts in a random order both land
            # here rather than being dropped.
            extra={
                k: v
                for k, v in q.other_attributes.items()
                if k != _REQUIRE_EACH_ROW
            },
            source_reference=q.source_reference,
        )
        for q in parsed.get("questions", [])
    ]

    quotas, quota_requirements = _build_quotas(parsed, options_by_question, review)
    dispositions = _build_dispositions(parsed, rules, quotas)
    questions_by_id = {q.id: q for q in parsed.get("questions", []) if q.id}

    survey = CanonicalSurvey(
        source=source,
        semantics=semantics,
        metadata=metadata,
        questions=questions,
        dispositions=dispositions,
        rules=rules,
        # Sorted into the order the questions are asked. The model returns its
        # findings in whatever order it found them, and two runs that agree on
        # every link would still write two different files, which makes a real
        # change and a reshuffle look the same in a diff.
        dependencies=sorted(
            _build_dependencies(option_sources) + _build_text_pipes(parsed, review),
            key=lambda d: (
                seq_of.get(d.to_question) or 0,
                seq_of.get(d.from_question) or 0,
                d.kind.value,
            ),
        ),
        randomization=_build_randomization(parsed, review),
        quotas=quotas,
        quota_requirements=quota_requirements,
        scenarios=_build_scenarios(
            parsed,
            questions_by_id,
            {d.disposition_id for d in dispositions},
            review,
        ),
        requirements=requirements,
        review=review,
    )

    # Everything from here on appends to `survey.review`, not to `review`.
    # Pydantic copies a list when it validates one onto a model, so the two stop
    # being the same object the moment the survey above is constructed - and a
    # finding added to the wrong one is discarded without a word. That had
    # already silenced `condition_option_unresolved`, a blocking check, which
    # was reporting nothing on every document because nothing it wrote could
    # reach the artifact.
    _resolve_option_references(survey, questions_by_id, survey.review)
    _check_inferred_subsets(survey, questions_by_id, survey.review)

    unknown_mandatory = [
        q.question_id
        for q in survey.questions
        if q.validation is not None and q.validation.mandatory is None
    ]
    if unknown_mandatory:
        survey.review.append(
            _review(
                "mandatory_unknown",
                FlagSeverity.WARNING,
                (
                    f"{len(unknown_mandatory)} questions say nothing about "
                    "whether an answer is required, and no statement in the "
                    "document sets a default, so it is left unknown rather "
                    "than assumed."
                ),
                target=FlagTarget(kind="survey", id=source),
                evidence=", ".join(unknown_mandatory),
            )
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
