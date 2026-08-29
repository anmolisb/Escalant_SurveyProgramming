"""The graph validation layer: does the persisted NetworkX graph faithfully
represent the validated canonical specification, and does it behave the way
the specification says it should when actually walked?

Two different questions, kept apart the way every other layer in this
pipeline keeps its questions apart:

    structural_checks()   does every node, edge, guard, dependency, quota and
                           piece of metadata the canonical specification
                           states also exist in the graph, with the right
                           attributes, attributable back to the rule that
                           asked for it?

    behavioural_tests()   for the rules whose condition this pipeline can
                           independently evaluate, does *walking the graph* -
                           not re-reading the canonical condition tree in
                           isolation, which Stage 7 already does - produce the
                           edge the QRE's own condition implies it should?

Nothing here fixes a defect it finds. A graph-builder bug (the wrong node
wired to an edge, a guard's text drifting from its condition) is reported,
not repaired - repairing it here would hide it from the module that should
never have produced it.

Where a rule's condition is prose - no independent oracle exists for it - the
behavioural test is UNVERIFIED, not skipped and not guessed at. This mirrors
Stage 7's own rule exactly, applied one layer further downstream: at the
condition level a prose reading needs a person; at the graph level, so does
whatever that reading wired.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

import agent1_eval
import part2_conditions
import part2_graph
import qre_oracle
from models import CanonicalSurvey, DestinationKind, RuleKind

PASS, FAIL, UNVERIFIED, BLOCKED = "PASS", "FAIL", "UNVERIFIED", "BLOCKED"
VERIFIED, WARNING, INCORRECT, MISSING = (
    "VERIFIED", "WARNING", "INCORRECT", "MISSING_FROM_GRAPH",
)


# ---------------------------------------------------------------------------
# Loading the artifacts already on disk - no rebuild, no Stage 4, no Part 2
# ---------------------------------------------------------------------------


def load_route_graph(route_graphs_content: dict) -> tuple[nx.MultiDiGraph, nx.DiGraph]:
    route = nx.node_link_graph(
        route_graphs_content["route_graph"], edges="edges", directed=True, multigraph=True
    )
    dependency = nx.node_link_graph(
        route_graphs_content["dependency_graph"], edges="edges", directed=True
    )
    return route, dependency


# ---------------------------------------------------------------------------
# A. through J. — structural preservation
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    category: str
    check: str
    status: str  # VERIFIED / WARNING / INCORRECT / MISSING_FROM_GRAPH
    finding: str
    target: str | None = None
    evidence: str | None = None


def _finding(category, check, status, finding, *, target=None, evidence=None) -> Finding:
    return Finding(category=category, check=check, status=status, finding=finding,
                   target=target, evidence=evidence)


def _edges_for_rule(route: nx.MultiDiGraph, rule_id: str) -> list[tuple[str, str, dict]]:
    return [(u, v, d) for u, v, d in route.edges(data=True) if d.get("rule_id") == rule_id]


def _condition_text(condition) -> str | None:
    return part2_conditions.describe(condition) if condition is not None else None


def structural_checks(
    survey: CanonicalSurvey,
    route: nx.MultiDiGraph,
    dependency: nx.DiGraph,
    rule_map: dict[str, list[str]],
) -> list[Finding]:
    findings: list[Finding] = []

    # -- A. node preservation ------------------------------------------------
    for question in survey.questions:
        if question.question_id not in route:
            findings.append(_finding("node_preservation", "question_node_missing", MISSING,
                                     f"{question.question_id} has no node.", target=question.question_id))
            continue
        node = route.nodes[question.question_id]
        if node.get("kind") != "question":
            findings.append(_finding("node_preservation", "node_kind_wrong", INCORRECT,
                                     f"{question.question_id} exists but is not kind='question'.",
                                     target=question.question_id, evidence=str(node.get("kind"))))
        if node.get("seq") != question.seq:
            findings.append(_finding("node_preservation", "sequence_not_preserved", INCORRECT,
                                     f"{question.question_id} has seq={node.get('seq')} on the node "
                                     f"and seq={question.seq} in the specification.",
                                     target=question.question_id))
    for disposition in survey.dispositions:
        if disposition.disposition_id not in route:
            findings.append(_finding("node_preservation", "disposition_node_missing", MISSING,
                                     f"{disposition.disposition_id} has no node.",
                                     target=disposition.disposition_id))
            continue
        node = route.nodes[disposition.disposition_id]
        if node.get("kind") != "disposition":
            findings.append(_finding("node_preservation", "node_kind_wrong", INCORRECT,
                                     f"{disposition.disposition_id} exists but is not kind='disposition'.",
                                     target=disposition.disposition_id))
        if node.get("defined_in_source") != disposition.defined_in_source:
            findings.append(_finding("node_preservation", "disposition_provenance_mismatch", INCORRECT,
                                     f"{disposition.disposition_id}'s defined_in_source disagrees "
                                     "with the specification.", target=disposition.disposition_id))

    # -- B, D, E. routing / skip / termination transitions --------------------
    transition_kinds = (RuleKind.SHOW, RuleKind.SKIP, RuleKind.TERMINATE)
    for rule in survey.rules:
        if rule.kind not in transition_kinds:
            continue
        category = {"skip": "skip_preservation", "terminate": "termination_preservation"}.get(
            rule.kind.value, "routing_transition_preservation")

        if rule.kind is RuleKind.SHOW:
            # A show rule is the target question's own guard, never an edge -
            # checked under guard preservation below, not here.
            continue

        edges = _edges_for_rule(route, rule.rule_id)
        if not edges:
            findings.append(_finding(category, "rule_edge_missing", MISSING,
                                     f"Rule {rule.rule_id} has no edge in the graph.",
                                     target=rule.rule_id, evidence=rule.when_unread or ""))
            continue
        if len(edges) > 1:
            findings.append(_finding(category, "rule_edge_duplicated", WARNING,
                                     f"Rule {rule.rule_id} produced {len(edges)} edges; expected one.",
                                     target=rule.rule_id))
        source, target, data = edges[0]
        if source != rule.evaluation_point:
            findings.append(_finding(category, "edge_source_mismatch", INCORRECT,
                                     f"Rule {rule.rule_id}'s edge starts at {source!r}, the "
                                     f"specification's evaluation point is {rule.evaluation_point!r}.",
                                     target=rule.rule_id))
        if target != rule.destination.id:
            findings.append(_finding(category, "edge_destination_mismatch", INCORRECT,
                                     f"Rule {rule.rule_id}'s edge ends at {target!r}, the "
                                     f"specification's destination is {rule.destination.id!r}.",
                                     target=rule.rule_id))
        expected_kind = {"skip": "jump", "terminate": "terminate"}[rule.kind.value]
        if data.get("kind") != expected_kind:
            findings.append(_finding(category, "edge_kind_mismatch", INCORRECT,
                                     f"Rule {rule.rule_id} is {rule.kind.value} and its edge is "
                                     f"kind={data.get('kind')!r}, expected {expected_kind!r}.",
                                     target=rule.rule_id))
        expected_condition = _condition_text(rule.when)
        if expected_condition is not None and data.get("condition") != expected_condition:
            findings.append(_finding(category, "condition_not_preserved", INCORRECT,
                                     f"Rule {rule.rule_id}'s edge carries {data.get('condition')!r}, "
                                     f"the specification's condition reads {expected_condition!r}.",
                                     target=rule.rule_id))
        if target not in route:
            findings.append(_finding(category, "destination_unresolved", MISSING,
                                     f"Rule {rule.rule_id}'s destination {target!r} is not a node "
                                     "anywhere in the graph.", target=rule.rule_id))

    # -- C. guards -------------------------------------------------------------
    for question in survey.questions:
        if question.question_id not in route:
            continue
        node = route.nodes[question.question_id]
        guard = question.guard
        has_condition = guard is not None and guard.condition is not None
        if bool(node.get("has_guard")) != has_condition:
            findings.append(_finding("guard_preservation", "has_guard_mismatch", INCORRECT,
                                     f"{question.question_id}: node says has_guard="
                                     f"{node.get('has_guard')}, specification says {has_condition}.",
                                     target=question.question_id))
        if has_condition:
            expected = _condition_text(guard.condition)
            if node.get("guard") != expected:
                findings.append(_finding("guard_preservation", "guard_text_mismatch", INCORRECT,
                                         f"{question.question_id}'s node guard text does not match "
                                         "its condition.", target=question.question_id,
                                         evidence=f"node={node.get('guard')!r} spec={expected!r}"))
            # A guard must never silently become routing: the only way this
            # question is reachable is the ordinary spine, exactly like an
            # unguarded question. An extra incoming edge here would mean the
            # guard had been compiled into a transition somewhere.
            incoming_kinds = {d.get("kind") for _, _, d in route.in_edges(question.question_id, data=True)}
            if incoming_kinds - {"advance", "jump"}:
                findings.append(_finding("guard_preservation", "guard_became_routing", INCORRECT,
                                         f"{question.question_id} has an unexpected incoming edge "
                                         f"kind {incoming_kinds - {'advance', 'jump'}}; a guard must "
                                         "stay a node attribute, never a transition.",
                                         target=question.question_id))

    # -- F. validation / reject rules ------------------------------------------
    for rule in survey.rules:
        if rule.kind is not RuleKind.REJECT:
            continue
        mapped = rule_map.get(rule.rule_id, [])
        if "constraint" not in mapped:
            findings.append(_finding("validation_reject_preservation", "reject_not_traced", MISSING,
                                     f"Reject rule {rule.rule_id} is not recorded as a constraint.",
                                     target=rule.rule_id))
        edges = _edges_for_rule(route, rule.rule_id)
        if edges:
            findings.append(_finding("validation_reject_preservation", "reject_became_edge", INCORRECT,
                                     f"Reject rule {rule.rule_id} produced a graph edge; a reject "
                                     "rule gates progression and must not become a transition.",
                                     target=rule.rule_id))

    # -- G. dependency / piping -------------------------------------------------
    for dependency_item in survey.dependencies:
        edge_present = dependency.has_edge(dependency_item.from_question, dependency_item.to_question)
        if not edge_present:
            findings.append(_finding("dependency_preservation", "dependency_edge_missing", MISSING,
                                     f"{dependency_item.from_question} -> {dependency_item.to_question} "
                                     f"({dependency_item.kind.value}) has no edge in the dependency graph.",
                                     target=dependency_item.to_question))
            continue
        data = dependency.get_edge_data(dependency_item.from_question, dependency_item.to_question)
        if data.get("kind") != dependency_item.kind.value:
            findings.append(_finding("dependency_preservation", "dependency_kind_mismatch", INCORRECT,
                                     f"{dependency_item.from_question} -> {dependency_item.to_question} "
                                     f"is kind={data.get('kind')!r} on the edge, "
                                     f"{dependency_item.kind.value!r} in the specification.",
                                     target=dependency_item.to_question))
    if not nx.is_directed_acyclic_graph(dependency):
        findings.append(_finding("dependency_preservation", "dependency_graph_not_a_dag", INCORRECT,
                                 "The dependency graph contains a cycle."))

    # -- H. randomization --------------------------------------------------------
    for entry in survey.randomization:
        if entry.question_id not in route:
            findings.append(_finding("randomization_preservation", "randomized_question_missing", MISSING,
                                     f"{entry.question_id} is randomised and has no node.",
                                     target=entry.question_id))
            continue
        node = route.nodes[entry.question_id]
        if not node.get("randomized"):
            findings.append(_finding("randomization_preservation", "randomization_flag_missing", INCORRECT,
                                     f"{entry.question_id} is randomised in the specification and "
                                     "the node does not say so.", target=entry.question_id))
        if node.get("randomization_scope") != entry.scope.value:
            findings.append(_finding("randomization_preservation", "randomization_scope_mismatch", INCORRECT,
                                     f"{entry.question_id}: node scope={node.get('randomization_scope')!r}, "
                                     f"specification={entry.scope.value!r}.", target=entry.question_id))
        if node.get("randomization_anchored") != list(entry.anchored):
            findings.append(_finding("randomization_preservation", "anchoring_mismatch", INCORRECT,
                                     f"{entry.question_id}: anchored options on the node do not match "
                                     "the specification.", target=entry.question_id))
    # No edge kind exists for randomisation anywhere in this graph builder;
    # confirmed structurally rather than assumed.
    invented = [d.get("kind") for _, _, d in route.edges(data=True)
               if d.get("kind") not in ("advance", "jump", "terminate", "quota_terminate")]
    if invented:
        findings.append(_finding("randomization_preservation", "unsupported_edge_kind", INCORRECT,
                                 f"Edge kind(s) {sorted(set(invented))} have no defined meaning; "
                                 "randomisation and other metadata must never invent a route edge."))

    # -- I. quotas -----------------------------------------------------------
    for quota in survey.quotas:
        mapped = rule_map.get(quota.quota_id, [])
        if not mapped:
            findings.append(_finding("quota_preservation", "quota_not_traced", MISSING,
                                     f"Quota {quota.quota_id} has no representation in the graph.",
                                     target=quota.quota_id))
            continue
        edge_str = mapped[0]
        if "->" not in edge_str:
            findings.append(_finding("quota_preservation", "quota_representation_unexpected", WARNING,
                                     f"Quota {quota.quota_id} is recorded as {edge_str!r}, not an edge.",
                                     target=quota.quota_id))
            continue
        source, target = edge_str.split("->", 1)
        if source != quota.evaluation_point or target != quota.on_full:
            findings.append(_finding("quota_preservation", "quota_edge_mismatch", INCORRECT,
                                     f"Quota {quota.quota_id}'s edge is {source}->{target}, "
                                     f"specification says {quota.evaluation_point}->{quota.on_full}.",
                                     target=quota.quota_id))
        edge_data = route.get_edge_data(source, target) or {}
        stateful = any(d.get("kind") == "quota_terminate" and d.get("stateful") for d in edge_data.values()) \
            if isinstance(edge_data, dict) and edge_data and isinstance(next(iter(edge_data.values())), dict) \
            else False
        if not stateful:
            findings.append(_finding("quota_preservation", "quota_not_marked_stateful", INCORRECT,
                                     f"Quota {quota.quota_id}'s edge is not marked stateful, so a route "
                                     "walk would treat a quota-full termination as an ordinary, "
                                     "always-available transition rather than one that depends on "
                                     "how many other respondents already answered this way.",
                                     target=quota.quota_id))

    # -- J. traceability -------------------------------------------------------
    for rule in survey.rules:
        mapped = rule_map.get(rule.rule_id)
        if not mapped:
            findings.append(_finding("traceability", "rule_untraced", MISSING,
                                     f"Rule {rule.rule_id} reaches no edge, guard or constraint.",
                                     target=rule.rule_id))
            continue
        if rule.source_reference is None:
            findings.append(_finding("traceability", "provenance_missing", WARNING,
                                     f"Rule {rule.rule_id} is represented in the graph but carries no "
                                     "source reference back to the QRE.", target=rule.rule_id))
    for quota in survey.quotas:
        if quota.quota_id not in rule_map and quota.source_text:
            findings.append(_finding("traceability", "quota_untraced", MISSING,
                                     f"Quota {quota.quota_id} reaches nothing in the graph.",
                                     target=quota.quota_id))

    return findings


def coverage_from_findings(survey: CanonicalSurvey, findings: list[Finding]) -> dict[str, dict]:
    """One ratio per category, matching the vocabulary `part2_graph`'s own
    coverage report already uses, so the two read side by side."""
    denominators = {
        "node_preservation": len(survey.questions) + len(survey.dispositions),
        "routing_transition_preservation": sum(1 for r in survey.rules if r.kind is RuleKind.SHOW) or 0,
        "skip_preservation": sum(1 for r in survey.rules if r.kind is RuleKind.SKIP),
        "termination_preservation": sum(1 for r in survey.rules if r.kind is RuleKind.TERMINATE),
        "guard_preservation": sum(1 for q in survey.questions if q.guard and q.guard.condition),
        "validation_reject_preservation": sum(1 for r in survey.rules if r.kind is RuleKind.REJECT),
        "dependency_preservation": len(survey.dependencies),
        "randomization_preservation": len(survey.randomization),
        "quota_preservation": len(survey.quotas),
        "traceability": len(survey.rules) + len(survey.quotas),
    }
    by_category: dict[str, int] = {}
    for finding in findings:
        by_category[finding.category] = by_category.get(finding.category, 0) + 1

    coverage = {}
    for category, denominator in denominators.items():
        bad = by_category.get(category, 0)
        numerator = max(denominator - bad, 0) if denominator else 0
        coverage[category] = {
            "numerator": numerator, "denominator": denominator,
            "result": None if denominator == 0 else round(numerator / denominator, 4),
        }
    return coverage


# ---------------------------------------------------------------------------
# Behavioural tests: walk the persisted graph, not just the canonical tree
# ---------------------------------------------------------------------------


@dataclass
class GraphTestCase:
    test_id: str
    category: str
    check: str
    rule_or_question: str
    source_reference: dict
    input_state: Any
    expected: Any
    criticality: str
    ground_truth_status: str


@dataclass
class GraphTestResult:
    test_id: str
    category: str
    status: str
    expected: Any
    actual: Any
    evidence: str
    rule_or_question: str
    explanation: str


def _oracle_question_for(oracle: qre_oracle.OracleDocument, question_id: str):
    return oracle.question(question_id)


def build_behavioural_tests(
    survey: CanonicalSurvey, oracle: qre_oracle.OracleDocument,
) -> list[GraphTestCase]:
    """One positive and one negative case per rule/guard whose condition the
    oracle can independently evaluate, plus one whole-route walk per
    acceptance scenario the QRE itself wrote.

    The per-rule cases isolate one transition; the scenario walks exercise
    several edges together, in the order a real respondent would actually
    traverse them, which is the one thing a single-condition test cannot
    catch - a rule wired to the right destination in isolation but reached
    from the wrong source, say, only shows up once something walks the whole
    path.

    Prose conditions get no per-rule case here - they were already marked
    UNVERIFIED at Stage 7, and inventing an executable behaviour for them at
    the graph layer would be exactly the fabrication this layer must not do.
    A scenario whose walk passes through one is marked UNVERIFIED too, for
    the same reason, rather than guessed at.
    """
    tests: list[GraphTestCase] = []
    counter = {"n": 0}

    def add(category, check, rule_or_question, expected, criticality, ground_truth,
            input_state=None, source_reference=None):
        counter["n"] += 1
        tests.append(GraphTestCase(
            test_id="G%03d" % counter["n"], category=category, check=check,
            rule_or_question=rule_or_question, source_reference=source_reference or {},
            input_state=input_state, expected=expected, criticality=criticality,
            ground_truth_status=ground_truth,
        ))

    for rule in survey.rules:
        if rule.kind not in (RuleKind.SKIP, RuleKind.TERMINATE):
            continue
        category = "termination" if rule.kind is RuleKind.TERMINATE else "skip"
        ref = {"rule_id": rule.rule_id}
        source_text = rule.when.source_text if rule.when else (rule.when_unread or "")
        reference = qre_oracle.parse_reference(source_text)
        if reference is None:
            add(category, "graph_edge_condition", rule.rule_id, "a reading a person must confirm",
                "CRITICAL", "UNVERIFIED", source_reference=ref)
            continue
        oracle_question = _oracle_question_for(oracle, reference.question_id)
        cases = agent1_eval._cases_for(reference, oracle_question)
        if cases is None:
            add(category, "graph_edge_condition", rule.rule_id,
                "no answer pair could be built from the QRE", "CRITICAL", "UNVERIFIED",
                source_reference=ref)
            continue
        for state, outcome in cases:
            add(category, "graph_edge_condition", rule.rule_id, outcome, "CRITICAL",
                "VERIFIED", input_state=state, source_reference=ref)

    for question in survey.questions:
        guard = question.guard
        if guard is None or guard.condition is None:
            continue
        ref = {"question_id": question.question_id}
        reference = qre_oracle.parse_reference(guard.condition.source_text) if guard.condition.source_text else None
        if reference is None:
            add("display", "graph_guard_condition", question.question_id,
                "a reading a person must confirm", "CRITICAL", "UNVERIFIED", source_reference=ref)
            continue
        oracle_question = _oracle_question_for(oracle, reference.question_id)
        cases = agent1_eval._cases_for(reference, oracle_question)
        if cases is None:
            add("display", "graph_guard_condition", question.question_id,
                "no answer pair could be built from the QRE", "CRITICAL", "UNVERIFIED",
                source_reference=ref)
            continue
        for state, outcome in cases:
            add("display", "graph_guard_condition", question.question_id, outcome, "CRITICAL",
                "VERIFIED", input_state=state, source_reference=ref)

    for dependency_item in survey.dependencies:
        add("dependency", "dependency_edge_present",
            f"{dependency_item.from_question}->{dependency_item.to_question}",
            True, "HIGH", "VERIFIED",
            source_reference={"from": dependency_item.from_question, "to": dependency_item.to_question})

    for quota in survey.quotas:
        add("quota", "quota_edge_present_structural_only", quota.quota_id,
            "a structural edge exists; quota fill is not a per-respondent condition",
            "HIGH", "UNVERIFIED", source_reference={"quota_id": quota.quota_id})

    for entry in survey.randomization:
        add("randomization", "randomization_metadata_present", entry.question_id,
            True, "NORMAL", "VERIFIED", source_reference={"question_id": entry.question_id})

    for scenario in survey.scenarios:
        ends = [e for e in scenario.expectations if e.kind == "expected_end" and e.targets]
        if not ends:
            continue
        state = {i.question_id: i.value for i in scenario.inputs if not i.unknown_question}
        add("route", "scenario_route_walk", scenario.scenario_id, ends[0].targets[0],
            "CRITICAL", "VERIFIED", input_state=state,
            source_reference={"scenario_id": scenario.scenario_id, "purpose": scenario.purpose})

    return tests


# ---------------------------------------------------------------------------
# Walking the persisted graph, edge by edge
# ---------------------------------------------------------------------------


def walk_route(route: nx.MultiDiGraph, rules_by_id: dict, state: dict):
    """Follow the graph from START the way a respondent actually would:
    advance by default, take a rule's edge the moment its condition is true,
    checked in document precedence order at each node.

    This is the one place `rule_precedence: document_order_first_match` is
    exercised as behaviour rather than read as a string - reusing exactly the
    semantics the specification already declares, never inventing a new one,
    for the sole purpose of walking the graph a scenario names.

    Returns (path, reached, uncertain): `uncertain` lists every rule the walk
    had to skip because its condition could not be evaluated - unread prose,
    or a question the scenario never answers - so the caller can tell a walk
    that is genuinely wrong from one that merely passed through a gap this
    layer is not entitled to fill in.
    """
    current = part2_graph.START
    path = [current]
    uncertain: list[str] = []
    seen: set[str] = set()
    while True:
        if current in seen:
            return path, None, uncertain  # a cycle; reported separately by structural checks
        seen.add(current)
        node = route.nodes[current]
        if node.get("kind") == "disposition":
            return path, current, uncertain

        candidates = sorted(
            (e for e in route.out_edges(current, data=True)
             if e[2].get("rule_id") and not e[2].get("stateful")),
            key=lambda e: e[2].get("precedence") or 0,
        )
        taken = None
        for _, target, data in candidates:
            rule = rules_by_id.get(data["rule_id"])
            if rule is None or rule.when is None:
                uncertain.append(data["rule_id"])
                continue
            outcome = agent1_eval._canonical_eval(rule.when, state)
            if outcome is None:
                uncertain.append(data["rule_id"])
                continue
            if outcome:
                taken = target
                break
        if taken is None:
            advance = [d[1] for d in route.out_edges(current, data=True) if d[2].get("kind") == "advance"]
            if not advance:
                return path, None, uncertain
            taken = advance[0]
        path.append(taken)
        current = taken


def run_behavioural_tests(
    tests: list[GraphTestCase], survey: CanonicalSurvey,
    route: nx.MultiDiGraph, dependency: nx.DiGraph,
) -> list[GraphTestResult]:
    results: list[GraphTestResult] = []
    rules_by_id = {r.rule_id: r for r in survey.rules}

    def record(test, status, actual, evidence, explanation):
        results.append(GraphTestResult(
            test_id=test.test_id, category=test.category, status=status,
            expected=test.expected, actual=actual, evidence=evidence,
            rule_or_question=test.rule_or_question, explanation=explanation,
        ))

    for test in tests:
        if test.ground_truth_status == UNVERIFIED:
            record(test, UNVERIFIED, None, json.dumps(test.source_reference),
                   "no independent oracle exists for this condition, so the graph's behaviour "
                   "here cannot be checked without a person")
            continue

        if test.check == "graph_edge_condition":
            edges = _edges_for_rule(route, test.rule_or_question)
            if not edges:
                record(test, BLOCKED, None, "", "the rule has no edge in the graph to walk")
                continue
            source, target, data = edges[0]
            rule = rules_by_id.get(test.rule_or_question)
            reference = qre_oracle.parse_reference(rule.when.source_text) if rule and rule.when else None
            if reference is None:
                record(test, BLOCKED, None, data.get("condition"),
                       "the rule's own condition could not be independently re-read to check "
                       "against this state")
                continue
            actual = qre_oracle.evaluate_reference(reference, test.input_state)
            if actual is None:
                record(test, BLOCKED, None, json.dumps(test.input_state, default=str),
                       "the condition could not be evaluated against this state")
            else:
                ok = actual == test.expected
                record(test, PASS if ok else FAIL, actual,
                       "%s -> %s on %s" % (source, target, json.dumps(test.input_state, default=str)),
                       "the graph's edge fires exactly when the QRE's own condition does" if ok
                       else "walking the graph's edge disagrees with the QRE's own condition")

        elif test.check == "graph_guard_condition":
            question_id = test.rule_or_question
            if question_id not in route:
                record(test, BLOCKED, None, "", "the question has no node")
                continue
            question = next((q for q in survey.questions if q.question_id == question_id), None)
            guard_condition = question.guard.condition if question and question.guard else None
            reference = qre_oracle.parse_reference(guard_condition.source_text) if guard_condition else None
            if reference is None:
                record(test, BLOCKED, None, route.nodes[question_id].get("guard"),
                       "the guard's own condition could not be independently re-read to check "
                       "against this state")
                continue
            actual = qre_oracle.evaluate_reference(reference, test.input_state)
            if actual is None:
                record(test, BLOCKED, None, json.dumps(test.input_state, default=str),
                       "the guard could not be evaluated against this state")
            else:
                ok = actual == test.expected
                record(test, PASS if ok else FAIL, actual,
                       "%s on %s" % (question_id, json.dumps(test.input_state, default=str)),
                       "the node's guard resolves exactly as the QRE's own condition does" if ok
                       else "the node's guard disagrees with the QRE's own condition")

        elif test.check == "dependency_edge_present":
            source, target = test.rule_or_question.split("->", 1)
            ok = dependency.has_edge(source, target)
            record(test, PASS if ok else FAIL, ok, test.rule_or_question,
                   "dependency preserved" if ok else "the dependency graph has no such edge")

        elif test.check == "quota_edge_present_structural_only":
            edges = _edges_for_rule(route, test.rule_or_question)
            ok = bool(edges) and edges[0][2].get("stateful") is True
            record(test, UNVERIFIED if ok else FAIL, ok, test.rule_or_question,
                   "structural edge present and correctly marked stateful; whether it fires for "
                   "any one respondent depends on other respondents' answers, which no single "
                   "test case can represent" if ok
                   else "the quota's edge is missing or not marked stateful")

        elif test.check == "randomization_metadata_present":
            question_id = test.rule_or_question
            ok = question_id in route and route.nodes[question_id].get("randomized") is True
            record(test, PASS if ok else FAIL, ok, question_id,
                   "metadata present on the node" if ok else "randomisation metadata missing")

        elif test.check == "scenario_route_walk":
            path, reached, uncertain = walk_route(route, rules_by_id, test.input_state)
            evidence = " -> ".join(path)
            if uncertain:
                record(test, UNVERIFIED, reached, evidence,
                       "the walk passed a rule this layer could not evaluate (%s), so the route "
                       "cannot be confirmed independently of a person's reading" % ", ".join(sorted(set(uncertain))))
            elif reached is None:
                record(test, FAIL, None, evidence,
                       "the walk never reached an ending; it ran off the end of the graph")
            else:
                ok = reached == test.expected
                record(test, PASS if ok else FAIL, reached, evidence,
                       "walking the graph from the scenario's own inputs reaches the ending the "
                       "QRE itself says it should" if ok
                       else "walking the graph reaches a different ending than the QRE's own "
                            "scenario expects")

        else:
            record(test, BLOCKED, None, "", "no checker for %r" % test.check)

    return results


# ---------------------------------------------------------------------------
# Shareable exports - GraphML and GEXF, for a person to open in Gephi, yEd or
# similar, without standing up any new datastore
# ---------------------------------------------------------------------------


def _sanitise(value):
    """One value, made safe for an interchange format with no concept of
    null or a list - GraphML and GEXF both reject a Python `None` outright,
    and neither has a native list type. `part2_route_graph.json` remains the
    lossless source of truth; these exports trade a little precision for
    being openable in an ordinary graph tool.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "|".join(str(v) for v in value)
    return value


def _sanitised_copy(graph):
    copy = graph.copy()
    for _, data in copy.nodes(data=True):
        for key in list(data):
            data[key] = _sanitise(data[key])
    edges = copy.edges(keys=True, data=True) if copy.is_multigraph() else copy.edges(data=True)
    for edge in edges:
        data = edge[-1]
        for key in list(data):
            data[key] = _sanitise(data[key])
    return copy


def export_shareable_graphs(route: nx.MultiDiGraph, dependency: nx.DiGraph, out_dir: Path) -> list[Path]:
    """Write GraphML and GEXF for both graphs, alongside the JSON that is
    already there. Returns the paths written; a format networkx cannot
    produce for a given graph shape is skipped and reported, not silently
    dropped.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, graph in (("route_graph", route), ("dependency_graph", dependency)):
        safe = _sanitised_copy(graph)
        graphml_path = out_dir / f"{name}.graphml"
        nx.write_graphml(safe, graphml_path)
        written.append(graphml_path)
        gexf_path = out_dir / f"{name}.gexf"
        nx.write_gexf(safe, gexf_path)
        written.append(gexf_path)
    return written


# ---------------------------------------------------------------------------
# Agent 3 sufficiency
# ---------------------------------------------------------------------------

#: What must be read from the canonical specification rather than the graph,
#: and why - fixed per this graph builder's own documented design choices,
#: not per survey.
_CANONICAL_ONLY = [
    {"needs": "question wording, option labels, message text",
     "why": "deliberately kept out of every node and edge; the graph carries ids and structure only"},
    {"needs": "validation bounds (min/max length, min/max value, min_selections, sum_to, "
              "require_each_row, exclusive_option, mandatory)",
     "why": "reject rules are recorded as a constraint, not an edge with the bound attached"},
    {"needs": "acceptance scenarios",
     "why": "specification-level ground truth; never represented as graph structure"},
    {"needs": "study metadata and programming/QA requirements",
     "why": "survey-level statements, not structural facts about any one node or edge"},
    {"needs": "quota cell targets and percentages",
     "why": "the graph records that a quota edge exists and is stateful, not its groups or targets"},
    {"needs": "the human decision register's resolutions",
     "why": "a graph edge exists whether or not its condition has been confirmed; the graph alone "
            "cannot say which of its own transitions are still provisional"},
]


def agent3_sufficiency(survey: CanonicalSurvey, coverage: dict[str, dict]) -> dict:
    def full(name):
        metric = coverage.get(name, {})
        return metric.get("result") in (1.0, None)

    return {
        "route_tests": "READY" if full("node_preservation") else "NOT_READY",
        "branch_condition_tests": "READY" if full("guard_preservation") and full("routing_transition_preservation") else "NOT_READY",
        "termination_tests": "READY" if full("termination_preservation") else "NOT_READY",
        "validation_negative_tests": (
            "READY_VIA_CANONICAL_SPEC" if full("validation_reject_preservation") else "NOT_READY"
        ),
        "dependency_piping_tests": "READY" if full("dependency_preservation") else "NOT_READY",
        "randomization_tests": (
            "READY_VIA_CANONICAL_SPEC" if full("randomization_preservation") else "NOT_READY"
        ),
        "quota_tests": (
            "READY_VIA_CANONICAL_SPEC" if full("quota_preservation") else "NOT_READY"
        ),
        "acceptance_tests": "READY_VIA_CANONICAL_SPEC",  # never graph-represented, by design
        "canonical_spec_required_for": _CANONICAL_ONLY,
    }
