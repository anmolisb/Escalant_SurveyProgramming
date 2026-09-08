"""The validation layer between the canonical specification and the graph builder.

Four questions, kept apart because they fail differently:

    cross-source     does the specification say only what the document says,
                     and all of it? Raw QRE, Stage 4 and canonical, compared
                     three ways so a disagreement can be attributed
    reproducibility  does the same document read the same way twice?
    confirmation     what is still a person's decision, and what does each one
                     change downstream?
    verdict          may this go to the graph builder, and to a test designer?

Nothing here fixes anything. A validator that repaired what it found would hide
the defect and leave the pipeline that produced it unchanged, and the next
document would arrive with the same problem. It reports, and it refuses to call
a specification ready while an open question can still change survey behaviour.

Deterministic throughout. Regenerating the specification to compare two runs
goes through the existing decision record, so a repeat run costs no model calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import agent1_eval
from . import qre_oracle
from .models import CanonicalSurvey, FlagSeverity, Origin, RuleKind

PASSED, PASSED_WITH_WARNINGS, FAILED = "PASSED", "PASSED_WITH_WARNINGS", "FAILED"


# ---------------------------------------------------------------------------
# Raw QRE <-> Stage 4 <-> canonical
# ---------------------------------------------------------------------------


def cross_source(oracle: qre_oracle.OracleDocument, stage4: dict,
                 survey: CanonicalSurvey) -> list[dict]:
    """Compare the three records of the same document.

    The three-way comparison is what makes a finding attributable. A fact
    missing from the canonical but present in Stage 4 was lost by Part 2; one
    missing from both was lost earlier; one present in the canonical and in
    neither of the others was invented.
    """
    findings: list[dict] = []

    def report(kind, severity, detail, **extra):
        findings.append(dict(check=kind, severity=severity, finding=detail, **extra))

    raw_questions = {q.question_id for q in oracle.questions}
    s4_questions = {q.id for q in stage4.get("questions", []) if q.id}
    canon_questions = {q.question_id for q in survey.questions}

    for missing in sorted(raw_questions - canon_questions):
        where = "Stage 4 as well" if missing not in s4_questions else "Part 2"
        report("missing_question", "BLOCKING",
               "%s is asked by the QRE and is not in the specification; lost by %s." % (missing, where),
               target=missing)
    for invented in sorted(canon_questions - raw_questions):
        report("invented_question", "BLOCKING",
               "%s is in the specification and the QRE does not ask it." % invented, target=invented)

    # Options: every option the specification offers must be one the QRE wrote.
    for question in survey.questions:
        source = oracle.question(question.question_id)
        if source is None:
            continue
        raw_labels = {o.label for o in source.options} | {o.label for o in source.matrix_rows}
        if not raw_labels:
            continue
        for option in list(question.options) + list(question.matrix_rows):
            if option.label not in raw_labels:
                report("invented_option", "BLOCKING",
                       "%s offers %r, which the QRE does not list for it."
                       % (question.question_id, option.label), target=question.question_id)
        for label in sorted(raw_labels - {o.label for o in question.options}
                            - {o.label for o in question.matrix_rows}):
            report("missing_option", "BLOCKING",
                   "%s is offered %r by the QRE and not by the specification."
                   % (question.question_id, label), target=question.question_id)

    raw_rules = {r.rule_id: r for r in oracle.rules}
    canon_rules = {r.rule_id: r for r in survey.rules}
    for missing in sorted(set(raw_rules) - set(canon_rules)):
        report("missing_rule", "BLOCKING",
               "Rule %s is in the routing table and not in the specification." % missing, target=missing)
    for invented in sorted(set(canon_rules) - set(raw_rules)):
        report("unsupported_rule", "BLOCKING",
               "Rule %s is in the specification and not in the routing table." % invented, target=invented)

    for rule_id in sorted(set(raw_rules) & set(canon_rules)):
        raw, canon = raw_rules[rule_id], canon_rules[rule_id]
        if canon.destination.id != raw.destination:
            report("contradictory_destination", "BLOCKING",
                   "Rule %s goes to %r in the QRE and %r in the specification."
                   % (rule_id, raw.destination, canon.destination.id), target=rule_id)
        carried = (canon.when.source_text if canon.when else canon.when_unread) or ""
        if raw.condition and raw.condition.strip() not in carried:
            report("contradictory_condition", "BLOCKING",
                   "Rule %s reads %r in the QRE; the specification kept %r."
                   % (rule_id, raw.condition, carried), target=rule_id)

    # Destinations must name something that exists.
    known = canon_questions | {d.disposition_id for d in survey.dispositions}
    for rule in survey.rules:
        if rule.destination.kind.value in ("question", "disposition") and rule.destination.id not in known:
            report("broken_reference", "BLOCKING",
                   "Rule %s points at %r, which is neither a question nor an ending."
                   % (rule.rule_id, rule.destination.id), target=rule.rule_id)

    # Endings: invented ones, and ones given words nobody wrote.
    raw_codes = {m.code for m in oracle.messages if m.code}
    referenced = {r.destination.id for r in survey.rules
                  if r.destination.kind.value == "disposition"}
    referenced |= {q.on_full for q in survey.quotas if q.on_full}
    for disposition in survey.dispositions:
        if disposition.disposition_id not in raw_codes | referenced:
            report("invented_disposition", "BLOCKING",
                   "%s is an ending nothing in the QRE names." % disposition.disposition_id,
                   target=disposition.disposition_id)
        if disposition.message and disposition.disposition_id not in raw_codes:
            report("invented_message", "BLOCKING",
                   "%s carries a message the QRE never gives it." % disposition.disposition_id,
                   target=disposition.disposition_id)

    # Validation must not appear from nowhere.
    for question in survey.questions:
        source = oracle.question(question.question_id)
        validation = question.validation
        if source is None or validation is None:
            continue
        stated = {agent1_eval._VALIDATION_ALIASES.get(k, k) for k in source.validate}
        for name in ("min_length", "max_length", "min_value", "max_value",
                     "min_selections", "sum_to", "require_each_row"):
            if getattr(validation, name) is not None and name not in stated:
                report("invented_validation", "BLOCKING",
                       "%s carries %s, which the QRE does not state for it."
                       % (question.question_id, name), target=question.question_id)
        if validation.mandatory is True and not source.optional:
            if survey.semantics.default_mandatory is None:
                report("unsupported_mandatory", "BLOCKING",
                       "%s is marked as requiring an answer with nothing in the document saying so."
                       % question.question_id, target=question.question_id)

    # Quotas must not invent groups.
    for quota in survey.quotas:
        sentence = next((s for s in oracle.quotas if s.code == quota.quota_id), None)
        if sentence is None:
            report("unsupported_quota", "BLOCKING",
                   "Quota %s is not stated anywhere in the QRE." % quota.quota_id, target=quota.quota_id)
            continue
        stated = dict(agent1_eval._percentages(sentence.text))
        for cell in quota.cells:
            if cell.option_label not in stated:
                report("invented_quota_cell", "BLOCKING",
                       "Quota %s counts %r, which its sentence does not name."
                       % (quota.quota_id, cell.option_label), target=quota.quota_id)
            elif cell.target_percent != stated[cell.option_label]:
                report("contradictory_quota_cell", "BLOCKING",
                       "Quota %s gives %r %s%% where the sentence says %s%%."
                       % (quota.quota_id, cell.option_label, cell.target_percent,
                          stated[cell.option_label]), target=quota.quota_id)

    # Randomization must be asked for.
    raw_random = {q.question_id for q in oracle.questions if q.randomize}
    for entry in survey.randomization:
        if entry.question_id not in raw_random:
            report("unsupported_randomization", "BLOCKING",
                   "%s is randomised in the specification and not in the QRE." % entry.question_id,
                   target=entry.question_id)

    # Dependencies: an option source must come from a sentence; a text pipe is
    # a reading, and is reported as such rather than as unsupported.
    for dependency in survey.dependencies:
        if dependency.kind.value != "option_source":
            continue
        source = oracle.question(dependency.to_question)
        if source is None or not source.option_source_text:
            report("unsupported_dependency", "BLOCKING",
                   "%s is said to take its options from %s, which no instruction states."
                   % (dependency.to_question, dependency.from_question),
                   target=dependency.to_question)

    return findings


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

#: The parts of a specification whose change is a change of behaviour. Ordering
#: and formatting are excluded on purpose: two runs that agree on all of this
#: describe the same survey however they lay it out.
def _behaviour(survey: CanonicalSurvey) -> dict:
    def condition(node):
        if node is None:
            return None
        return {
            "op": node.op.value,
            "left": None if node.left is None else
                {"q": node.left.question_id, "agg": getattr(node.left.aggregate, "value", None),
                 "text": node.left.text, "num": node.left.number,
                 "values": node.left.values, "ids": node.left.option_ids},
            "right": None if node.right is None else
                {"q": node.right.question_id, "agg": getattr(node.right.aggregate, "value", None),
                 "text": node.right.text, "num": node.right.number,
                 "values": node.right.values, "ids": node.right.option_ids},
            "operands": [condition(c) for c in node.operands],
        }

    return {
        "questions": sorted(
            ({"id": q.question_id, "seq": q.seq, "kind": q.kind,
              "options": [(o.option_id, o.label, o.code) for o in q.options],
              "rows": [(o.option_id, o.label) for o in q.matrix_rows],
              "validation": None if q.validation is None else q.validation.model_dump(mode="json"),
              "guard": None if q.guard is None else condition(q.guard.condition),
              "option_source": None if q.option_source is None else q.option_source.from_question}
             for q in survey.questions), key=lambda x: str(x["id"])),
        "rules": sorted(
            ({"id": r.rule_id, "kind": r.kind.value, "when": condition(r.when),
              "unread": r.when_unread, "destination": [r.destination.kind.value, r.destination.id],
              "evaluation_point": r.evaluation_point, "precedence": r.precedence}
             for r in survey.rules), key=lambda x: str(x["id"])),
        "dispositions": sorted(
            ({"id": d.disposition_id, "kind": d.kind, "message": d.message,
              "defined": d.defined_in_source} for d in survey.dispositions),
            key=lambda x: str(x["id"])),
        "dependencies": sorted(
            ([d.from_question, d.to_question, d.kind.value] for d in survey.dependencies)),
        "randomization": sorted(
            ([r.question_id, r.scope.value, sorted(r.anchored)] for r in survey.randomization)),
        "quotas": sorted(
            ({"id": q.quota_id, "enforcement": q.enforcement, "variable": q.variable_question_id,
              "cells": sorted([c.option_label, c.option_id, c.target_percent] for c in q.cells),
              "on_full": q.on_full, "evaluation_point": q.evaluation_point}
             for q in survey.quotas), key=lambda x: str(x["id"])),
        "semantics": {k: v for k, v in survey.semantics.model_dump(mode="json").items()
                      if not k.endswith("_source")},
    }


def reproducibility(rebuild, runs: int = 2) -> dict:
    """Build the specification again and compare what matters.

    `rebuild` is a callable returning a fresh CanonicalSurvey from the same
    inputs. Every model answer it needs is already in the decision record, so
    repeating costs nothing.
    """
    surveys = [rebuild() for _ in range(runs)]
    exact = [s.model_dump(mode="json") for s in surveys]
    semantic = [_behaviour(s) for s in surveys]

    exact_same = all(json.dumps(e, sort_keys=True, default=str)
                     == json.dumps(exact[0], sort_keys=True, default=str) for e in exact)
    semantic_same = all(json.dumps(s, sort_keys=True, default=str)
                        == json.dumps(semantic[0], sort_keys=True, default=str) for s in semantic)

    differences = []
    if not semantic_same:
        first = semantic[0]
        for other in semantic[1:]:
            for key in first:
                if json.dumps(first[key], sort_keys=True, default=str) != json.dumps(
                        other[key], sort_keys=True, default=str):
                    differences.append(key)
    return {
        "runs": runs,
        "exact_reproducible": exact_same,
        "semantic_reproducible": semantic_same,
        "meaningful_differences": sorted(set(differences)),
        "note": ("Formatting and ordering are excluded from the semantic comparison; "
                 "routing, destinations, conditions, validation, termination, dependencies, "
                 "quotas and randomization are not."),
    }


# ---------------------------------------------------------------------------
# What still needs a person
# ---------------------------------------------------------------------------

#: What each unresolved class actually changes downstream. Written out rather
#: than summarised, because "needs review" tells a reader nothing about whether
#: they can proceed.
_CONSEQUENCE = {
    "semantics_unconfirmed":
        ("Which questions appear on many routes, which rule wins when two apply, and "
         "whether an 'is exactly' test passes on a multi-select answer."),
    "condition_inferred":
        ("Whether this rule fires for a given respondent, so which questions they see "
         "and which ending they reach."),
    "condition_unread":
        ("The rule has no machine-readable form, so nothing downstream can evaluate it."),
    "guard_unread":
        ("The question's display condition cannot be evaluated, so no test can decide "
         "whether it should have appeared."),
    "inferred_condition_partial_options":
        ("Which answers satisfy the rule. Respondents choosing an omitted answer take a "
         "different path than they should."),
    "text_pipe_inferred":
        ("Whether this question's wording depends on an earlier answer, which decides "
         "the order a bot must answer in and what text it should expect on screen."),
    "randomization_anchoring":
        ("Where an exclusive option appears when the list is shuffled, which decides "
         "whether a displayed-order assertion is right."),
    "quota_inferred":
        ("Which respondents are counted against which quota, and when they are turned away."),
    "quota_ending_missing":
        ("Nothing can be asserted about what a quota-full respondent is shown."),
    "guard_single_source":
        ("A display condition stated in only one place. Anyone reading the other place "
         "builds a survey without it."),
    "partial_option_codes":
        ("A bot told to answer by code cannot resolve the uncoded options."),
    "mandatory_unknown":
        ("Whether an answer is required, so whether a skip-without-answering test should "
         "expect a validation error."),
    "scenario_option_unresolved":
        ("The scenario names an answer the question does not offer, so it cannot be run "
         "as written."),
}


def _plain_id(reference: str) -> str:
    """`questions[Q16]` -> `Q16`, so one issue does not list the same thing twice.

    Findings arrive from two places - the specification's own review list, which
    names bare ids, and the test results, which name where in the specification
    they looked. Left alone they read as different items.
    """
    if reference and "[" in reference and reference.endswith("]"):
        return reference[reference.index("[") + 1 : -1]
    return reference


def confirmation_gate(survey: CanonicalSurvey, results) -> list[dict]:
    items: dict[str, dict] = {}

    def add(issue, why, target, consequence):
        entry = items.setdefault(issue, {
            "status": "CONFIRMATION_REQUIRED", "issue": issue, "why_it_matters": why,
            "affected": [], "changes_downstream": consequence,
        })
        if target and target not in entry["affected"]:
            entry["affected"].append(target)

    for finding in survey.review:
        consequence = _CONSEQUENCE.get(finding.check)
        if consequence is None:
            continue
        target = finding.target.id if finding.target else None
        add(finding.check, finding.finding, target, consequence)

    for result in results:
        if result.status != agent1_eval.UNVERIFIED:
            continue
        if result.category == "semantic_assumptions":
            add("semantics_unconfirmed", result.explanation, _plain_id(result.canonical_reference),
                _CONSEQUENCE["semantics_unconfirmed"])
        elif result.category == "randomization":
            add("randomization_anchoring", result.explanation, _plain_id(result.canonical_reference),
                _CONSEQUENCE["randomization_anchoring"])

    ordered = sorted(items.values(), key=lambda x: (-len(x["affected"]), x["issue"]))
    for entry in ordered:
        entry["affected"] = sorted(entry["affected"])
    return ordered


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def attach_decision_ids(gate: list[dict], decisions: dict[str, dict]) -> list[dict]:
    """Point each confirmation-gate entry at the persisted decisions behind it.

    `gate` groups by issue name for the prose summary; the register groups by
    exact evidence, which can split one issue into more than one persisted
    decision (C01's `ambiguous_piping` is four decisions, one per distinct
    wording). Naming them here is what "the validation output must reference
    relevant decision IDs" means in practice: a reader goes from one line of
    prose to the exact register entries carrying its resolution.
    """
    by_issue: dict[str, list[str]] = {}
    for did, entry in decisions.items():
        by_issue.setdefault(entry["issue"], []).append(did)
    for item in gate:
        item["decision_ids"] = sorted(by_issue.get(item["issue"], []))
    return gate


def verdict(results, coverage_report: dict, cross: list[dict],
            repro: dict, gate: list[dict], graph: dict | None = None,
            decisions: dict[str, dict] | None = None) -> dict:
    critical_failures = [r for r in results
                         if r.status == agent1_eval.FAIL and r.criticality == agent1_eval.CRITICAL]
    other_failures = [r for r in results
                      if r.status == agent1_eval.FAIL and r.criticality != agent1_eval.CRITICAL]
    blocked = [r for r in results if r.status == agent1_eval.BLOCKED]
    blocking_cross = [f for f in cross if f["severity"] == "BLOCKING"]

    incorrect, missing, ambiguous, must_change, affected = [], [], [], [], []
    for failure in critical_failures + other_failures:
        incorrect.append("%s [%s] %s — expected %r, found %r"
                         % (failure.test_id, failure.category, failure.explanation,
                            failure.expected, failure.actual))
    for finding in blocking_cross:
        bucket = missing if finding["check"].startswith("missing") else incorrect
        bucket.append("%s: %s" % (finding["check"], finding["finding"]))
        if finding.get("target"):
            affected.append(finding["target"])
    for entry in gate:
        ambiguous.append("%s — %s" % (entry["issue"], entry["changes_downstream"]))
        affected.extend(entry["affected"])

    if critical_failures or blocking_cross or not repro["semantic_reproducible"]:
        status = FAILED
        if not repro["semantic_reproducible"]:
            must_change.append("Make the specification reproducible: %s differ between runs."
                               % ", ".join(repro["meaningful_differences"]))
        if critical_failures:
            must_change.append("Correct the %d critical test failures listed above."
                               % len(critical_failures))
        if blocking_cross:
            must_change.append("Resolve the %d cross-source findings: the specification and the "
                               "document disagree." % len(blocking_cross))
    elif other_failures or gate or blocked:
        status = PASSED_WITH_WARNINGS
    else:
        status = PASSED

    # Three different questions, so three different answers.
    #
    # `graph_ready` asks whether the next stage can run: does the graph build,
    # does it faithfully represent the specification, and does the specification
    # agree with the document about the things the graph is made of? It is
    # measured by building the graph, not inferred from the verdict - a
    # specification can be incomplete in a way that never reaches the graph, and
    # saying otherwise would send someone looking for a structural fault that
    # is not there.
    #
    # `human_decision_gate` asks whether every BLOCKING decision the survey has
    # raised has actually been resolved by a person - not inferred from any
    # issue's name (a hardcoded list of "these four issues count" would silently
    # miss the next kind of ambiguity a future document raises), but read
    # straight off the severity a decision was persisted with. `agent1_decisions`
    # decides severity once, per kind of issue; this only asks whether it is
    # still pending.
    #
    # `agent3_ready` needs both: the graph must build, and nothing blocking may
    # still be waiting on a person.
    graph_built = graph is None or (graph.get("passed") and not graph.get("blocking"))
    graph_ready = bool(graph_built) and not blocking_cross and repro["semantic_reproducible"]

    decisions = decisions or {}
    pending_blocking = sorted(
        e["decision_id"] for e in decisions.values()
        if e.get("status") == "PENDING_CONFIRMATION" and e.get("severity") == "BLOCKING"
    )
    decision_gate = "PENDING_BLOCKING_DECISIONS" if pending_blocking else "CLEAR"
    blocked_by_issues = sorted({
        decisions[did]["issue"] for did in pending_blocking
    })
    agent3_ready = graph_ready and status != FAILED and decision_gate == "CLEAR"

    return {
        "canonical_status": status,
        "graph_ready": "YES" if graph_ready else "NO",
        "graph_evidence": graph,
        "human_decision_gate": decision_gate,
        "pending_blocking_decisions": pending_blocking,
        "agent3_ready": "YES" if agent3_ready else "NO",
        "agent3_blocked_by": blocked_by_issues,
        "what_is_incorrect": incorrect,
        "what_is_missing": missing,
        "what_is_ambiguous": ambiguous,
        "what_must_change": must_change,
        "affected_ids": sorted(set(affected)),
        "counts": {
            "critical_failures": len(critical_failures),
            "other_failures": len(other_failures),
            "blocked": len(blocked),
            "cross_source_blocking": len(blocking_cross),
            "confirmation_required": len(gate),
            "decisions_pending_blocking": len(pending_blocking),
        },
    }
