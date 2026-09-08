"""The human decision / confirmation layer.

Part 2 already marks the places where it inferred, derived or could not read
something (CLAUDE.md §14, §31). What did not exist until now is a *record* of
those places that survives from one run to the next: a project owner who
confirms "the first matching rule wins" on Monday should not be asked the same
question again on Tuesday, and a confirmation given against one version of a
QRE must not silently answer for a different version.

This module does three things:

    detect()     read a CanonicalSurvey and find every place a person's
                 judgement, not the document's, decided the current reading -
                 generic across any survey, built from structure and origin
                 markers, never from a question id or option label
    reconcile()  compare what was just detected against a persisted register,
                 carrying a resolution forward only when the thing it resolved
                 has not changed, and demoting it back to pending, loudly,
                 the moment it might have
    register     the persisted file itself: `agent1_decisions.json`, one entry
                 per decision, editable by hand - a project owner resolves a
                 decision by setting `status`, `decision` and
                 `decision_provenance` on its entry and re-running the pipeline

Nothing here resolves anything on its own. A decision arrives PENDING_CONFIRMATION
and stays there until a person writes to the register; the pipeline's job is to
notice it, persist it, and refuse to call the specification behaviourally
approved while it stands.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import part2_conditions
from .models import (
    CanonicalSurvey, Condition, ConditionOp, Origin, RuleKind, SourceDocument,
)

#: Bumped only when the vocabulary or severity table below changes in a way
#: that could change a past resolution's meaning. Part of the reuse key
#: alongside the source document and the model - the three things capable of
#: making an old decision stop applying.
DECISION_SCHEMA_VERSION = "1.0.0"

RESOLVED = "RESOLVED"
PENDING = "PENDING_CONFIRMATION"
NOT_REQUIRED = "NOT_REQUIRED"

BLOCKING = "BLOCKING"
NON_BLOCKING = "NON_BLOCKING"

REGISTER_ARTIFACT = "agent1_decisions.json"
REGISTER_MARKDOWN = "agent1_decision_register.md"


# ---------------------------------------------------------------------------
# The fixed vocabulary
# ---------------------------------------------------------------------------
#
# One row per kind of decision this pipeline can raise. Categories and
# severities are properties of the *kind* of ambiguity, decided once for every
# survey this pipeline will ever read - never of one survey's content. Adding
# a QRE with a structure never seen before extends what `detect()` finds, not
# this table.
#
# Severity follows one rule: BLOCKING when the reading changes whether a
# question is asked, which way a respondent routes, which ending they reach,
# whether an answer is accepted, or which quota counts them. NON_BLOCKING
# when it changes only what a test asserts about ordering or wording, or
# leaves a gap in explanatory text without changing where anyone goes.

@dataclass(frozen=True)
class _IssueInfo:
    category: str
    severity: str
    current_interpretation: str
    alternatives: tuple[str, ...]
    downstream_impact: str
    recommendation: str


_ISSUES: dict[str, _IssueInfo] = {
    "unasked_question_semantics": _IssueInfo(
        category="semantic_assumption", severity=BLOCKING,
        current_interpretation=(
            "A condition naming a question the respondent was never asked is "
            "treated as false, so the rule or guard does not fire."
        ),
        alternatives=(
            "Treat it as true instead, so the rule fires.",
            "Treat it as an error state needing its own handling.",
        ),
        downstream_impact=(
            "Changes which questions are shown and which ending is reached "
            "whenever a condition names a question that was skipped."
        ),
        recommendation=(
            "Confirm the intended reading with the project owner. Once "
            "recorded here it applies to every rule in this survey and does "
            "not need asking again unless the document changes."
        ),
    ),
    "rule_precedence": _IssueInfo(
        category="semantic_assumption", severity=BLOCKING,
        current_interpretation=(
            "The first rule in document order whose condition is true is the "
            "one that applies."
        ),
        alternatives=(
            "The most specific matching condition wins.",
            "Every matching rule applies, and a later one can override an "
            "earlier one.",
        ),
        downstream_impact=(
            "Changes which destination is used whenever more than one rule's "
            "condition can be true for the same respondent."
        ),
        recommendation="Confirm the intended precedence with the project owner.",
    ),
    "multi_select_equality": _IssueInfo(
        category="semantic_assumption", severity=BLOCKING,
        current_interpretation=(
            "'==' against a multi-select question's answer means the whole "
            "answer set is exactly that value - chosen, and nothing else."
        ),
        alternatives=(
            "'==' means the value is among those chosen, alongside others.",
            "'==' against a multi-select is a document error and should be "
            "read as a different operator.",
        ),
        downstream_impact=(
            "Changes the outcome of every equality condition written against "
            "a multi-select question."
        ),
        recommendation="Confirm the intended reading with the project owner.",
    ),
    "termination_precedence": _IssueInfo(
        category="routing", severity=BLOCKING,
        current_interpretation=(
            "Two or more termination rules name overlapping conditions on the "
            "same question; the first one in document order applies."
        ),
        alternatives=(
            "The more restrictive screenout applies regardless of order.",
            "Both are meant to be mutually exclusive and one is a document "
            "error.",
        ),
        downstream_impact=(
            "Changes which disposition and message a respondent who matches "
            "more than one termination condition actually receives."
        ),
        recommendation="Confirm with the project owner which ending is correct.",
    ),
    "skip_show_precedence": _IssueInfo(
        category="routing", severity=BLOCKING,
        current_interpretation=(
            "A skip rule and a show rule name the same destination; the skip "
            "is treated as unconditional and the show guard is not re-checked."
        ),
        alternatives=(
            "The destination's own guard still applies even after a skip "
            "lands on it.",
        ),
        downstream_impact=(
            "Changes whether the destination question is shown when the skip "
            "rule fires but the destination's own guard would say otherwise."
        ),
        recommendation="Confirm with the project owner which rule takes priority.",
    ),
    "ambiguous_routing_condition": _IssueInfo(
        category="routing", severity=BLOCKING,
        current_interpretation=(
            "A prose condition was rewritten into a formal one by a model, "
            "and the parser accepted the rewrite."
        ),
        alternatives=(
            "A different formal reading of the same sentence is possible.",
        ),
        downstream_impact=(
            "Whether this rule or guard fires for a given respondent, so "
            "which questions they see and which ending they reach."
        ),
        recommendation=(
            "A person familiar with the survey should confirm the reading "
            "recorded here matches what the sentence intends."
        ),
    ),
    "inferred_condition_partial_options": _IssueInfo(
        category="routing", severity=BLOCKING,
        current_interpretation=(
            "A model reading a set-valued condition named only some of a "
            "question's selectable answers as satisfying it."
        ),
        alternatives=(
            "The omitted answer(s) should also satisfy the condition.",
        ),
        downstream_impact=(
            "Which answers satisfy the rule; a respondent choosing an "
            "omitted answer takes a different path than intended."
        ),
        recommendation="Confirm whether the omitted answer(s) should count.",
    ),
    "ambiguous_piping": _IssueInfo(
        category="dependency", severity=BLOCKING,
        current_interpretation=(
            "A question's wording was read as quoting an earlier answer, from "
            "the phrasing alone; no table states the link."
        ),
        alternatives=(
            "The wording is generic and does not actually depend on the "
            "earlier answer.",
        ),
        downstream_impact=(
            "Whether this question's wording depends on an earlier answer, "
            "which decides the order a respondent bot must answer in and "
            "what text it should expect on screen."
        ),
        recommendation="Confirm the dependency with the project owner.",
    ),
    "randomization_anchoring": _IssueInfo(
        category="randomization", severity=NON_BLOCKING,
        current_interpretation=(
            "No option is anchored; every option in the list is free to move."
        ),
        alternatives=(
            "An exclusive option (such as \"None of these\") stays anchored "
            "at the bottom, by convention.",
        ),
        downstream_impact=(
            "Where an exclusive option appears when the list is shuffled, "
            "which decides whether a displayed-order assertion is correct. "
            "Does not change which questions are asked or how they route."
        ),
        recommendation="Confirm anchoring convention with the project owner.",
    ),
    "quota_behaviour": _IssueInfo(
        category="quota", severity=BLOCKING,
        current_interpretation=(
            "A quota's variable, groups and targets were read out of a prose "
            "sentence by a model and passed the structural checks."
        ),
        alternatives=(
            "The sentence intends a different variable, grouping, or split.",
        ),
        downstream_impact=(
            "Which respondents are counted against which quota, and when "
            "they are turned away."
        ),
        recommendation="Confirm the quota reading with the project owner.",
    ),
    "missing_disposition_message": _IssueInfo(
        category="disposition", severity=NON_BLOCKING,
        current_interpretation=(
            "This ending is reachable and the document never states what it "
            "shows the respondent who reaches it."
        ),
        alternatives=(),
        downstream_impact=(
            "Nothing can be asserted about what this respondent is shown. "
            "Does not change routing: the destination itself is correct."
        ),
        recommendation="Ask the project owner for the missing message text.",
    ),
    "guard_single_source": _IssueInfo(
        category="routing", severity=NON_BLOCKING,
        current_interpretation=(
            "The display condition is stated only in the questionnaire "
            "table, not in the routing table, and is carried from the one "
            "place that states it."
        ),
        alternatives=(),
        downstream_impact=(
            "None to this specification, which already combines both "
            "sources. Worth flagging back to whoever maintains the QRE, "
            "since a reader of only the routing table would miss it."
        ),
        recommendation="No action needed here; consider noting the asymmetry to the QRE author.",
    ),
    "missing_option_codes": _IssueInfo(
        category="validation", severity=BLOCKING,
        current_interpretation=(
            "Some but not all of this question's options carry an answer "
            "code; the rest are left null rather than invented."
        ),
        alternatives=(),
        downstream_impact=(
            "A respondent bot told to answer by code cannot resolve the "
            "uncoded options."
        ),
        recommendation="Ask the project owner for the missing codes.",
    ),
    "mandatory_unknown": _IssueInfo(
        category="validation", severity=BLOCKING,
        current_interpretation=(
            "Whether an answer is required is left unknown: the question "
            "carries no explicit marking and the document states no default."
        ),
        alternatives=("Assume required.", "Assume optional."),
        downstream_impact=(
            "Whether a skip-without-answering test should expect a "
            "validation error."
        ),
        recommendation="Confirm the default with the project owner.",
    ),
    "scenario_input_unresolved": _IssueInfo(
        category="acceptance_scenario", severity=NON_BLOCKING,
        current_interpretation=(
            "A scenario supplies an answer this question does not offer as "
            "written."
        ),
        alternatives=(),
        downstream_impact=(
            "That one scenario cannot be run as written. Does not change "
            "the specification's own routing or validation."
        ),
        recommendation="Ask the project owner to correct the scenario's input.",
    ),
}

#: `AuditFinding.check` values already produced by Part 2, mapped to the issue
#: they represent. Anything not in this table is a defect signal (something
#: to fix in code) rather than a decision (something only a person can
#: settle), and is deliberately left out - see `part2_validate.cross_source`
#: for that half.
_FROM_REVIEW_CHECK = {
    "condition_inferred": "ambiguous_routing_condition",
    "condition_unread": "ambiguous_routing_condition",
    "guard_unread": "ambiguous_routing_condition",
    "inferred_condition_partial_options": "inferred_condition_partial_options",
    "text_pipe_inferred": "ambiguous_piping",
    "randomization_anchoring": "randomization_anchoring",
    "quota_inferred": "quota_behaviour",
    # quota_ending_missing is deliberately not mapped here: it is the quota
    # section's special case of a disposition with no message, and
    # `_missing_disposition_messages` below already covers every such
    # disposition from its own definition rather than from who referenced it.
    # Mapping both would raise the same missing message as two decisions.
    "guard_single_source": "guard_single_source",
    "partial_option_codes": "missing_option_codes",
    "mandatory_unknown": "mandatory_unknown",
    "scenario_option_unresolved": "scenario_input_unresolved",
}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@dataclass
class RawDecision:
    """One decision point as detected this run, before it meets the register."""

    issue: str
    affected: list[str]
    source_evidence: str
    current_interpretation: str
    alternative_interpretations: list[str]
    downstream_impact: str
    recommendation: str
    category: str
    severity: str


def _walk(condition: Condition | None):
    if condition is None:
        return
    yield condition
    for child in condition.operands:
        yield from _walk(child)


def _referenced_questions(condition: Condition | None) -> set[str]:
    found: set[str] = set()
    for node in _walk(condition):
        for side in (node.left, node.right):
            if side is not None and side.question_id:
                found.add(side.question_id)
    return found


def _all_conditions(survey: CanonicalSurvey):
    for rule in survey.rules:
        if rule.when is not None:
            yield ("rule", rule.rule_id, rule.when)
    for question in survey.questions:
        if question.guard is not None and question.guard.condition is not None:
            yield ("question", question.question_id, question.guard.condition)


def _from_semantics(survey: CanonicalSurvey) -> list[RawDecision]:
    """The three whole-survey assumptions CLAUDE.md §20 names, raised only
    when the survey actually has the shape that makes each one matter."""
    decisions: list[RawDecision] = []
    semantics = survey.semantics

    has_guard = any(
        q.guard is not None and q.guard.condition is not None for q in survey.questions
    )
    has_skip = any(r.kind is RuleKind.SKIP for r in survey.rules)
    if (has_guard or has_skip) and semantics.unasked_reference_origin is not Origin.EXTRACTED:
        info = _ISSUES["unasked_question_semantics"]
        decisions.append(RawDecision(
            issue="unasked_question_semantics", affected=["semantics"],
            source_evidence=(
                f"unasked_reference={semantics.unasked_reference!r}, "
                f"origin={semantics.unasked_reference_origin.value}"
            ),
            current_interpretation=info.current_interpretation,
            alternative_interpretations=list(info.alternatives),
            downstream_impact=info.downstream_impact, recommendation=info.recommendation,
            category=info.category, severity=info.severity,
        ))

    if len(survey.rules) > 1 and semantics.rule_precedence_origin is not Origin.EXTRACTED:
        info = _ISSUES["rule_precedence"]
        decisions.append(RawDecision(
            issue="rule_precedence", affected=["semantics"],
            source_evidence=(
                f"rule_precedence={semantics.rule_precedence!r}, "
                f"origin={semantics.rule_precedence_origin.value}"
            ),
            current_interpretation=info.current_interpretation,
            alternative_interpretations=list(info.alternatives),
            downstream_impact=info.downstream_impact, recommendation=info.recommendation,
            category=info.category, severity=info.severity,
        ))

    multi_questions = {q.question_id for q in survey.questions if "multi" in (q.kind or "").lower()}
    uses_equality_on_multi = False
    for _, _, condition in _all_conditions(survey):
        for node in _walk(condition):
            if node.op in (ConditionOp.EQ, ConditionOp.NE, ConditionOp.SET_EQ):
                left = node.left
                if left is not None and left.question_id in multi_questions:
                    uses_equality_on_multi = True
    if uses_equality_on_multi and semantics.multi_equality_origin is not Origin.EXTRACTED:
        info = _ISSUES["multi_select_equality"]
        decisions.append(RawDecision(
            issue="multi_select_equality", affected=["semantics"],
            source_evidence=(
                f"multi_equality={semantics.multi_equality!r}, "
                f"origin={semantics.multi_equality_origin.value}"
            ),
            current_interpretation=info.current_interpretation,
            alternative_interpretations=list(info.alternatives),
            downstream_impact=info.downstream_impact, recommendation=info.recommendation,
            category=info.category, severity=info.severity,
        ))
    return decisions


def _from_review(survey: CanonicalSurvey) -> list[RawDecision]:
    """Findings Part 2 already raised, carried into the decision vocabulary.

    Deliberately keyed off `AuditFinding.check`, a fixed string this pipeline
    writes today and would write for any future document with the same kind
    of ambiguity - never off which question or rule triggered it.

    Grouped by the exact evidence text, not by which question or rule carried
    the finding. C01's condition "Q1 contains at least one brand" is read once
    and the reading is then shared by rule R6 and question Q2's guard, since
    Part 2 caches a condition by the text it was parsed from - so the same
    reading turns up as two findings, one against each holder, and without
    grouping a person would be asked to confirm the identical sentence twice.
    Two findings with different evidence stay separate even when they share an
    issue type: Q2's and Q6's readings are different sentences and confirming
    one says nothing about the other.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for finding in survey.review:
        issue = _FROM_REVIEW_CHECK.get(finding.check)
        if issue is None:
            continue
        evidence = finding.evidence or finding.finding
        target = finding.target.id if finding.target else finding.check
        groups.setdefault((issue, evidence), []).append(target)

    decisions: list[RawDecision] = []
    for (issue, evidence), targets in groups.items():
        info = _ISSUES[issue]
        decisions.append(RawDecision(
            issue=issue, affected=sorted(set(targets)),
            source_evidence=evidence,
            current_interpretation=info.current_interpretation,
            alternative_interpretations=list(info.alternatives),
            downstream_impact=info.downstream_impact, recommendation=info.recommendation,
            category=info.category, severity=info.severity,
        ))
    return decisions


def _termination_precedence(survey: CanonicalSurvey) -> list[RawDecision]:
    """Two or more termination rules whose conditions can both hold for one
    respondent, because they name at least one question in common.

    Deliberately narrow: two termination rules on two entirely different
    questions asked in sequence are ordinary screening gates, already
    explained by `rule_precedence`, and flagging every one of those as its
    own decision would ask a person to confirm the obvious on every survey
    that screens on more than one question. This fires only where the
    conditions could genuinely collide.
    """
    terminate = [r for r in survey.rules if r.kind is RuleKind.TERMINATE and r.when is not None]
    referenced = {r.rule_id: _referenced_questions(r.when) for r in terminate}
    colliding: set[str] = set()
    for i, a in enumerate(terminate):
        for b in terminate[i + 1:]:
            if referenced[a.rule_id] & referenced[b.rule_id]:
                colliding.add(a.rule_id)
                colliding.add(b.rule_id)
    if not colliding:
        return []
    info = _ISSUES["termination_precedence"]
    return [RawDecision(
        issue="termination_precedence", affected=sorted(colliding),
        source_evidence="; ".join(
            f"{rid}: {r.when.source_text}" for rid, r in
            ((r.rule_id, r) for r in terminate if r.rule_id in colliding)
        ),
        current_interpretation=info.current_interpretation,
        alternative_interpretations=list(info.alternatives),
        downstream_impact=info.downstream_impact, recommendation=info.recommendation,
        category=info.category, severity=info.severity,
    )]


def _skip_show_precedence(survey: CanonicalSurvey) -> list[RawDecision]:
    """A skip rule and a show rule naming the very same destination.

    The skip rule bypasses everything between its evaluation point and its
    destination unconditionally once it fires; if that destination also
    carries its own display guard, nothing states whether the guard is
    re-checked or the skip simply overrides it.
    """
    skip_targets = {r.destination.id: r.rule_id for r in survey.rules if r.kind is RuleKind.SKIP}
    show_targets = {r.destination.id: r.rule_id for r in survey.rules if r.kind is RuleKind.SHOW}
    shared = sorted(set(skip_targets) & set(show_targets))
    if not shared:
        return []
    info = _ISSUES["skip_show_precedence"]
    affected = sorted({skip_targets[t] for t in shared} | {show_targets[t] for t in shared} | set(shared))
    return [RawDecision(
        issue="skip_show_precedence", affected=affected,
        source_evidence="; ".join(
            f"{skip_targets[t]} skips to {t}, {show_targets[t]} shows {t}" for t in shared
        ),
        current_interpretation=info.current_interpretation,
        alternative_interpretations=list(info.alternatives),
        downstream_impact=info.downstream_impact, recommendation=info.recommendation,
        category=info.category, severity=info.severity,
    )]


def _missing_disposition_messages(survey: CanonicalSurvey) -> list[RawDecision]:
    """Every ending that is reachable and has no message, from whatever
    reached it - not only quotas, which is all the review queue already
    covered."""
    info = _ISSUES["missing_disposition_message"]
    decisions = []
    for disposition in survey.dispositions:
        if disposition.defined_in_source:
            continue
        decisions.append(RawDecision(
            issue="missing_disposition_message", affected=[disposition.disposition_id],
            source_evidence=f"{disposition.disposition_id} is referenced but has no message.",
            current_interpretation=info.current_interpretation,
            alternative_interpretations=list(info.alternatives),
            downstream_impact=info.downstream_impact, recommendation=info.recommendation,
            category=info.category, severity=info.severity,
        ))
    return decisions


def detect(survey: CanonicalSurvey) -> list[RawDecision]:
    """Every decision point this survey's specification currently raises."""
    decisions: list[RawDecision] = []
    decisions += _from_semantics(survey)
    decisions += _from_review(survey)
    decisions += _termination_precedence(survey)
    decisions += _skip_show_precedence(survey)
    decisions += _missing_disposition_messages(survey)
    return decisions


# ---------------------------------------------------------------------------
# Identity and context
# ---------------------------------------------------------------------------


def decision_id(raw: RawDecision, survey_id: str) -> str:
    """A stable id, so the same real ambiguity keeps the same id run to run.

    Built from the survey, the kind of issue, what it affects and the exact
    evidence text - not from a random or sequential number, which would give
    a fresh id (and so a fresh PENDING_CONFIRMATION) to the same unresolved
    question on every single run.
    """
    digest = hashlib.sha256()
    for part in (survey_id, raw.issue, "|".join(sorted(raw.affected)), raw.source_evidence):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


def context_key(model: str) -> str:
    """What else, besides the document, a resolution depends on.

    A resolution recorded against one model's reading, or one version of this
    module's vocabulary, is not automatically valid against a different one -
    the vocabulary changing could mean the severity or the very wording of
    what was asked has changed underneath an answer nobody revisited.
    """
    digest = hashlib.sha256()
    digest.update(DECISION_SCHEMA_VERSION.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(model.encode("utf-8"))
    return digest.hexdigest()[:16]


# ---------------------------------------------------------------------------
# The register: persistence and reconciliation
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_register(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    entries = data.get("entries", data) if isinstance(data, dict) else {}
    return entries if isinstance(entries, dict) else {}


def save_register(path: Path, entries: dict[str, dict], survey_id: str,
                  source: SourceDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "artifact": "agent1_decisions",
        "survey_id": survey_id,
        "source_document": source.model_dump(mode="json"),
        "generated_at": _now(),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def reconcile(existing: dict[str, dict], raw_decisions: list[RawDecision],
             survey_id: str, source: SourceDocument, model: str) -> tuple[dict[str, dict], dict]:
    """Merge freshly detected decisions into the persisted register.

    Three outcomes per decision, and the rule that picks between them:

        not seen before        -> new entry, PENDING_CONFIRMATION
        seen, same context     -> reused as-is: status, decision and
                                   provenance all carry forward untouched
        seen, context changed  -> a RESOLVED entry is demoted back to
                                   PENDING_CONFIRMATION; its old resolution is
                                   kept as `previous_decision` so a person can
                                   re-confirm quickly rather than start over,
                                   but it no longer counts as resolved

    An entry that was in the register but is not detected this run has
    stopped applying - the pattern that raised it is gone from the document.
    It moves to NOT_REQUIRED rather than being deleted, so the register stays
    a full history of every decision this survey has ever raised.
    """
    key = context_key(model)
    now = _now()
    new_register: dict[str, dict] = {}
    seen_ids: set[str] = set()

    raised = reused = context_changed = newly_pending = 0

    for raw in raw_decisions:
        did = decision_id(raw, survey_id)
        seen_ids.add(did)
        prior = existing.get(did)
        base = dict(
            decision_id=did, survey_id=survey_id,
            source_document={"filename": source.filename, "sha256": source.sha256},
            affected=sorted(raw.affected), category=raw.category, issue=raw.issue,
            source_evidence=raw.source_evidence,
            current_interpretation=raw.current_interpretation,
            alternative_interpretations=raw.alternative_interpretations,
            downstream_impact=raw.downstream_impact, recommendation=raw.recommendation,
            severity=raw.severity, context_key=key, last_seen_at=now,
        )

        if prior is None:
            raised += 1
            newly_pending += 1
            new_register[did] = {
                **base, "status": PENDING, "created_at": now, "resolved_at": None,
                "decision": None, "decision_provenance": None,
                "previous_decision": None, "context_changed": False,
            }
            continue

        same_document = prior.get("source_document", {}).get("sha256") == source.sha256
        same_context = prior.get("context_key") == key
        entry = {**prior, **base, "created_at": prior.get("created_at", now)}

        if same_document and same_context:
            # Nothing that would invalidate a resolution has moved. Carry the
            # status, the resolution and who made it forward untouched.
            entry["status"] = prior.get("status", PENDING)
            entry["resolved_at"] = prior.get("resolved_at")
            entry["decision"] = prior.get("decision")
            entry["decision_provenance"] = prior.get("decision_provenance")
            entry["previous_decision"] = prior.get("previous_decision")
            entry["context_changed"] = False
            if prior.get("status") == RESOLVED:
                reused += 1
            else:
                newly_pending += 1 if prior.get("status") != PENDING else 0
        elif prior.get("status") == RESOLVED:
            # The document or the reading it was resolved against has moved.
            # A silent carry-forward here is exactly what "reuse" must not do.
            context_changed += 1
            entry["status"] = PENDING
            entry["resolved_at"] = None
            entry["decision"] = None
            entry["decision_provenance"] = None
            entry["previous_decision"] = {
                "decision": prior.get("decision"), "resolved_at": prior.get("resolved_at"),
                "decision_provenance": prior.get("decision_provenance"),
                "resolved_against_sha256": prior.get("source_document", {}).get("sha256"),
            }
            entry["context_changed"] = True
        else:
            # Was already pending or not-required; nothing to protect.
            entry["status"] = PENDING
            entry["resolved_at"] = None
            entry["decision"] = prior.get("decision")
            entry["decision_provenance"] = prior.get("decision_provenance")
            entry["previous_decision"] = prior.get("previous_decision")
            entry["context_changed"] = not (same_document and same_context)

        new_register[did] = entry

    not_required = 0
    for did, prior in existing.items():
        if did in seen_ids:
            continue
        if prior.get("status") == NOT_REQUIRED:
            new_register[did] = prior
            continue
        not_required += 1
        new_register[did] = {**prior, "status": NOT_REQUIRED, "last_seen_at": now}

    summary = {
        "total": len(new_register),
        "raised_this_run": raised,
        "resolved_reused": reused,
        "pending": sum(1 for e in new_register.values() if e["status"] == PENDING),
        "resolved": sum(1 for e in new_register.values() if e["status"] == RESOLVED),
        "not_required": sum(1 for e in new_register.values() if e["status"] == NOT_REQUIRED),
        "newly_transitioned_not_required": not_required,
        "context_changed": context_changed,
        "blocking_pending": sorted(
            e["decision_id"] for e in new_register.values()
            if e["status"] == PENDING and e["severity"] == BLOCKING
        ),
    }
    return new_register, summary


def human_decision_gate(register: dict[str, dict]) -> str:
    """CLEAR when nothing blocking is still waiting on a person."""
    pending_blocking = any(
        e["status"] == PENDING and e["severity"] == BLOCKING for e in register.values()
    )
    return "PENDING_BLOCKING_DECISIONS" if pending_blocking else "CLEAR"


# ---------------------------------------------------------------------------
# Human-readable register
# ---------------------------------------------------------------------------


def to_markdown(register: dict[str, dict], survey_id: str, source: SourceDocument) -> str:
    entries = sorted(register.values(), key=lambda e: (
        e["status"] != PENDING, e["severity"] != BLOCKING, e["issue"], e["decision_id"]))
    lines = [
        f"# Decision register — {survey_id}",
        "",
        f"Source: `{source.filename}` (sha256 `{(source.sha256 or '')[:16]}…`)",
        "",
        "A decision is resolved by editing its entry in `agent1_decisions.json` -",
        "set `status` to `RESOLVED`, fill `decision` with the ruling and",
        "`decision_provenance` with who made it - then re-run the pipeline. It is",
        "reused from then on unless the source document or this module's",
        "vocabulary changes, in which case it returns here as pending, with the",
        "old ruling kept under `previous_decision` for a quick re-confirmation.",
        "",
    ]
    if not entries:
        lines.append("No decisions raised for this survey.")
        return "\n".join(lines)

    counts: dict[str, int] = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    lines.append("**" + ", ".join(f"{v} {k}" for k, v in counts.items()) + "**")
    lines.append("")

    for e in entries:
        marker = "🔴" if e["severity"] == BLOCKING else "⚪"
        lines.append(f"## {marker} `{e['issue']}` — {e['status']} ({e['severity']})")
        lines.append("")
        lines.append(f"- **id:** `{e['decision_id']}`")
        lines.append(f"- **affects:** {', '.join(e['affected'])}")
        lines.append(f"- **evidence:** {e['source_evidence']}")
        lines.append(f"- **current reading:** {e['current_interpretation']}")
        if e["alternative_interpretations"]:
            lines.append("- **alternatives:** " + "; ".join(e["alternative_interpretations"]))
        lines.append(f"- **downstream impact:** {e['downstream_impact']}")
        lines.append(f"- **recommendation:** {e['recommendation']}")
        if e["status"] == RESOLVED:
            lines.append(f"- **decision:** {e['decision']}")
            lines.append(f"- **decided by:** {e['decision_provenance']} on {e['resolved_at']}")
        if e.get("context_changed"):
            prev = e.get("previous_decision") or {}
            lines.append(
                "- **⚠ context changed since last resolved** — was `%s` by %s on %s; "
                "confirm it still applies."
                % (prev.get("decision"), prev.get("decision_provenance"), prev.get("resolved_at"))
            )
        lines.append("")
    return "\n".join(lines)
