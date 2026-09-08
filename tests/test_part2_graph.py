"""Deterministic tests for the graph builder (`src/part2_graph.py`).

No model calls, no fixtures named by id. Every test builds a small
`CanonicalSurvey` in code and asserts what the graph builder does with it, so
a passing suite says something about the builder's logic rather than about
S01 or C01 in particular - those two are exercised separately, by running the
real pipeline (`src/run_validation.py`) against their committed canonical
artifacts, which this file does not duplicate.

Runnable two ways:

    python -m pytest tests/test_part2_graph.py
    python tests/test_part2_graph.py

No pytest fixtures are used, so the second form works with nothing beyond
this repository's own dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path


import networkx as nx

from src.agents.qre_interpretation import part2_graph
from src.agents.qre_interpretation.models import (
    CanonicalDisposition,
    CanonicalQuestion,
    CanonicalRule,
    CanonicalSurvey,
    CanonicalValidation,
    Condition,
    ConditionOp,
    Dependency,
    DependencyKind,
    Destination,
    DestinationKind,
    Guard,
    GuardAgreement,
    Operand,
    Quota,
    QuotaCell,
    Randomization,
    RandomizationScope,
    RuleKind,
)


# ---------------------------------------------------------------------------
# Builders - small, generic, no survey-specific ids beyond what a test needs
# ---------------------------------------------------------------------------


def q(qid, seq, *, kind="single", guard=None, validation=None) -> CanonicalQuestion:
    return CanonicalQuestion(question_id=qid, seq=seq, kind=kind, wording=f"wording for {qid}",
                             guard=guard, validation=validation)


def eq_condition(qid, value) -> Condition:
    return Condition(op=ConditionOp.EQ, left=Operand(question_id=qid),
                     right=Operand(text=value), source_text=f"{qid} == {value!r}")


def rule(rule_id, kind, destination_id, destination_kind=DestinationKind.QUESTION,
        when=None, evaluation_point=None, precedence=1) -> CanonicalRule:
    return CanonicalRule(rule_id=rule_id, kind=kind,
                         destination=Destination(kind=destination_kind, id=destination_id),
                         when=when, evaluation_point=evaluation_point, precedence=precedence)


def disposition(did, *, kind="complete", message="ok", defined=True) -> CanonicalDisposition:
    return CanonicalDisposition(disposition_id=did, kind=kind,
                                message=message if defined else None, defined_in_source=defined)


# ---------------------------------------------------------------------------
# A minimal, linear survey: two questions, one ending, no branching at all.
# The floor every survey should clear.
# ---------------------------------------------------------------------------


def _linear_survey() -> CanonicalSurvey:
    return CanonicalSurvey(
        source="test.docx",
        questions=[q("Q1", 1), q("Q2", 2)],
        dispositions=[disposition("COMPLETE")],
    )


def test_linear_survey_builds_a_clean_spine():
    survey = _linear_survey()
    graphs, report = part2_graph.run(survey)
    assert report.passed
    assert report.structurally_buildable
    assert report.nodes == 4  # START, Q1, Q2, COMPLETE
    assert report.edges == 3  # START->Q1, Q1->Q2, Q2->COMPLETE
    assert report.blocking == 0
    assert report.coverage["node_coverage"]["result"] == 1.0
    # Nothing to cover: every optional category reports None, not a
    # misleading 100%.
    for empty in ("validation_reject_representation", "quota_coverage", "randomization_coverage"):
        assert report.coverage[empty]["result"] is None


def test_behaviorally_approved_is_null_when_no_verdict_is_supplied():
    survey = _linear_survey()
    _graphs, report = part2_graph.run(survey)
    assert report.behaviorally_approved is None
    assert report.approval_blocked_by == []


def test_behaviorally_approved_true_when_everything_clears():
    survey = _linear_survey()
    _graphs, report = part2_graph.run(
        survey, canonical_status="PASSED", human_decision_gate="CLEAR")
    assert report.behaviorally_approved is True
    assert report.approval_blocked_by == []


def test_behaviorally_approved_false_on_pending_blocking_decisions():
    survey = _linear_survey()
    _graphs, report = part2_graph.run(
        survey, canonical_status="PASSED_WITH_WARNINGS",
        human_decision_gate="PENDING_BLOCKING_DECISIONS")
    assert report.structurally_buildable is True  # the graph itself is still fine
    assert report.behaviorally_approved is False
    assert "human_decision_gate=PENDING_BLOCKING_DECISIONS" in report.approval_blocked_by


def test_behaviorally_approved_false_on_failed_canonical_status():
    survey = _linear_survey()
    _graphs, report = part2_graph.run(
        survey, canonical_status="FAILED", human_decision_gate="CLEAR")
    assert report.behaviorally_approved is False
    assert "canonical_status=FAILED" in report.approval_blocked_by


# ---------------------------------------------------------------------------
# Routing, skip, termination
# ---------------------------------------------------------------------------


def _branching_survey() -> CanonicalSurvey:
    guard = Guard(condition=eq_condition("S1", "Yes"), agreement=GuardAgreement.SINGLE_SOURCE)
    return CanonicalSurvey(
        source="test.docx",
        questions=[q("S1", 1), q("Q1", 2, guard=guard), q("Q2", 3)],
        dispositions=[disposition("COMPLETE"), disposition("TERM_SCREEN", kind="screenout")],
        rules=[
            rule("R1", RuleKind.TERMINATE, "TERM_SCREEN", DestinationKind.DISPOSITION,
                 when=eq_condition("S1", "No"), evaluation_point="S1", precedence=1),
            rule("R2", RuleKind.SKIP, "Q2", DestinationKind.QUESTION,
                 when=eq_condition("S1", "No"), evaluation_point="S1", precedence=2),
        ],
    )


def test_terminate_and_skip_rules_become_edges():
    survey = _branching_survey()
    graphs, report = part2_graph.run(survey)
    route = nx.node_link_graph(graphs.route_graph, edges="edges", directed=True, multigraph=True)
    kinds = {(u, v, d["kind"]) for u, v, d in route.edges(data=True) if d.get("rule_id")}
    assert ("S1", "TERM_SCREEN", "terminate") in kinds
    assert ("S1", "Q2", "jump") in kinds
    assert report.coverage["termination_coverage"]["result"] == 1.0
    assert report.coverage["routing_rule_coverage"]["numerator"] == 2


def test_show_rule_is_a_guard_not_an_edge():
    survey = _branching_survey()
    graphs, report = part2_graph.run(survey)
    route = nx.node_link_graph(graphs.route_graph, edges="edges", directed=True, multigraph=True)
    assert route.nodes["Q1"]["has_guard"] is True
    # No edge should carry a rule_id for a SHOW rule - none exists to carry
    # in this fixture, but the node itself is the only representation.
    assert all(d.get("kind") != "show" for _, _, d in route.edges(data=True))
    assert report.coverage["skip_display_representation"]["denominator"] >= 1


def test_terminate_rule_with_missing_evaluation_point_is_reported_not_silently_dropped():
    survey = CanonicalSurvey(
        source="test.docx",
        questions=[q("Q1", 1)],
        dispositions=[disposition("COMPLETE")],
        rules=[rule("R1", RuleKind.TERMINATE, "COMPLETE", DestinationKind.DISPOSITION,
                    when=None, evaluation_point=None)],
    )
    _graphs, report = part2_graph.run(survey)
    assert report.blocking >= 1
    assert not report.passed
    assert not report.structurally_buildable
    assert report.coverage["termination_coverage"]["result"] == 0.0


# ---------------------------------------------------------------------------
# Reject / validation rules -> constraint, never an edge
# ---------------------------------------------------------------------------


def test_reject_rule_is_a_constraint_not_an_edge():
    survey = CanonicalSurvey(
        source="test.docx",
        questions=[q("Q1", 1, validation=CanonicalValidation(sum_to=100))],
        dispositions=[disposition("COMPLETE")],
        rules=[rule("R1", RuleKind.REJECT, "Q1", DestinationKind.QUESTION)],
    )
    graphs, report = part2_graph.run(survey)
    assert graphs.rule_edge_map["R1"] == ["constraint"]
    route = nx.node_link_graph(graphs.route_graph, edges="edges", directed=True, multigraph=True)
    assert route.number_of_edges() == 2  # only the spine; the reject added no edge
    assert report.coverage["validation_reject_representation"]["result"] == 1.0


# ---------------------------------------------------------------------------
# Dependencies / piping
# ---------------------------------------------------------------------------


def test_dependency_becomes_a_dependency_graph_edge_and_stays_a_dag():
    survey = CanonicalSurvey(
        source="test.docx",
        questions=[q("Q1", 1), q("Q2", 2)],
        dependencies=[Dependency(from_question="Q1", to_question="Q2",
                                 kind=DependencyKind.OPTION_SOURCE)],
    )
    graphs, report = part2_graph.run(survey)
    dependency = nx.node_link_graph(graphs.dependency_graph, edges="edges", directed=True)
    assert dependency.has_edge("Q1", "Q2")
    assert nx.is_directed_acyclic_graph(dependency)
    assert report.coverage["dependency_coverage"]["result"] == 1.0


def test_dependency_cycle_is_reported_not_silently_broken():
    survey = CanonicalSurvey(
        source="test.docx",
        questions=[q("Q1", 1), q("Q2", 2)],
        dependencies=[
            Dependency(from_question="Q1", to_question="Q2", kind=DependencyKind.TEXT_PIPE),
            Dependency(from_question="Q2", to_question="Q1", kind=DependencyKind.TEXT_PIPE),
        ],
    )
    _graphs, report = part2_graph.run(survey)
    assert any(f.check == "dependency_cycle" for f in report.findings)
    assert not report.passed


# ---------------------------------------------------------------------------
# Quotas -> stateful edges, and a quota-full ending with no message is a
# warning, not an invented one
# ---------------------------------------------------------------------------


def test_quota_becomes_a_stateful_edge_and_is_traced():
    survey = CanonicalSurvey(
        source="test.docx",
        questions=[q("D1", 1)],
        dispositions=[disposition("COMPLETE"), disposition("TERM_FULL", kind="quota_full", defined=False)],
        quotas=[Quota(quota_id="QUOTA_X", enforcement="hard", variable_question_id="D1",
                      cells=[QuotaCell(option_label="A", target_percent=50.0)],
                      on_full="TERM_FULL", evaluation_point="D1")],
    )
    graphs, report = part2_graph.run(survey)
    route = nx.node_link_graph(graphs.route_graph, edges="edges", directed=True, multigraph=True)
    quota_edges = [(u, v) for u, v, d in route.edges(data=True) if d.get("kind") == "quota_terminate"]
    assert ("D1", "TERM_FULL") in quota_edges
    assert graphs.rule_edge_map["QUOTA_X"] == ["D1->TERM_FULL"]
    assert report.coverage["quota_coverage"]["result"] == 1.0
    assert any(f.check == "termination" and "TERM_FULL" in f.finding for f in report.findings)


# ---------------------------------------------------------------------------
# Randomization -> node metadata only, never an edge
# ---------------------------------------------------------------------------


def test_randomization_is_node_metadata_not_an_edge():
    survey = CanonicalSurvey(
        source="test.docx",
        questions=[q("Q1", 1)],
        randomization=[Randomization(question_id="Q1", scope=RandomizationScope.OPTIONS,
                                     anchored=["None of these"])],
    )
    graphs, report = part2_graph.run(survey)
    route = nx.node_link_graph(graphs.route_graph, edges="edges", directed=True, multigraph=True)
    assert route.nodes["Q1"]["randomized"] is True
    assert route.nodes["Q1"]["randomization_scope"] == "options"
    assert route.nodes["Q1"]["randomization_anchored"] == ["None of these"]
    # No edge kind exists for randomisation; the spine is untouched by it.
    assert all(d.get("kind") in ("advance",) for _, _, d in route.edges(data=True))
    assert report.coverage["randomization_coverage"]["result"] == 1.0


def test_randomization_coverage_is_none_when_survey_has_none():
    survey = _linear_survey()
    _graphs, report = part2_graph.run(survey)
    assert report.coverage["randomization_coverage"]["result"] is None
    assert report.coverage["randomization_coverage"]["denominator"] == 0


# ---------------------------------------------------------------------------
# Traceability: every rule and quota must map to an edge, a guard, or a
# constraint - never nothing
# ---------------------------------------------------------------------------


def test_unreachable_rule_target_is_reported_and_lowers_traceability():
    survey = CanonicalSurvey(
        source="test.docx",
        questions=[q("Q1", 1)],
        dispositions=[disposition("COMPLETE")],
        rules=[rule("R1", RuleKind.SKIP, "GHOST", DestinationKind.QUESTION,
                    when=eq_condition("Q1", "x"), evaluation_point="Q1")],
    )
    _graphs, report = part2_graph.run(survey)
    assert not report.passed
    assert any(f.check == "rule_coverage" for f in report.findings)
    assert report.coverage["traceability_coverage"]["result"] == 0.0


def test_no_hardcoded_ids_leak_into_a_different_survey_shape():
    """The same builder, run on a survey whose ids share nothing with the
    module's own tests above, must produce the same *kind* of result. This is
    the generalisation check: nothing above should have been secretly reading
    a literal id like "Q1" out of the graph builder itself."""
    survey = CanonicalSurvey(
        source="anything.docx",
        questions=[q("ZZZ_1", 1), q("Weird-Id.2", 2)],
        dispositions=[disposition("THE_END")],
        rules=[rule("RULE-A", RuleKind.SKIP, "Weird-Id.2", DestinationKind.QUESTION,
                    when=eq_condition("ZZZ_1", "v"), evaluation_point="ZZZ_1")],
    )
    graphs, report = part2_graph.run(survey)
    assert report.passed
    route = nx.node_link_graph(graphs.route_graph, edges="edges", directed=True, multigraph=True)
    assert "ZZZ_1" in route.nodes and "Weird-Id.2" in route.nodes
    assert route.has_edge("ZZZ_1", "Weird-Id.2")


# ---------------------------------------------------------------------------
# Runner for `python tests/test_part2_graph.py`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("ok   %s" % name)
        except AssertionError as exc:
            failed += 1
            print("FAIL %s: %s" % (name, exc))
        except Exception as exc:  # noqa: BLE001 - surface anything, this is a test runner
            failed += 1
            print("ERROR %s: %r" % (name, exc))
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    raise SystemExit(1 if failed else 0)
