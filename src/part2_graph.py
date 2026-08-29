"""Part 2 — turning the canonical specification into graphs.

The specification stays the source of truth. These are a view of it, built so
route discovery and test design can ask structural questions without re-reading
the QRE. A fact that exists only in a graph and not in the specification is a
bug in this module.

Two graphs, not one, because they answer different questions and fusing them
gives something that answers neither well:

    RouteGraph        how a respondent moves: questions, endings, transitions
    DependencyGraph   which questions need which earlier answers, as a DAG

Questions form a spine in the order the QRE asks them, and a question's display
condition is an attribute of its node rather than a set of edges. The
alternative - compiling every guard into edge conditions - multiplies edges for
no extra information and buries which rule each one came from. Route discovery
walks the spine and skips nodes whose guard is false.

Three things are deliberately NOT edges:

    show rules      already the target node's guard; an edge as well would
                    state the same fact twice, in two places that can disagree
    reject rules    a gate on progressing, not a change of destination
    randomisation   changes what a question looks like, never where it leads

Wording, option labels and message text stay out of the graphs entirely. Nodes
carry ids and structure; anything needing the text reads the specification.
"""

from __future__ import annotations

import networkx as nx

from models import (
    AuditFinding,
    CanonicalSurvey,
    DestinationKind,
    FlagSeverity,
    FlagTarget,
    GraphReport,
    RouteGraphs,
    RuleKind,
)

#: The synthetic node every route starts from, so "can this be reached" has one
#: place to start rather than depending on which question happens to be first.
START = "__START__"


def _finding(check, severity, finding, *, target=None, evidence=None):
    return AuditFinding(
        check=check,
        severity=severity,
        finding=finding,
        target=target,
        evidence=evidence,
    )


def _condition_summary(condition) -> str | None:
    """A short readable form of a condition, for looking at an edge by eye."""
    if condition is None:
        return None
    import part2_conditions

    return part2_conditions.describe(condition)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def build_route_graph(survey: CanonicalSurvey) -> nx.MultiDiGraph:
    """Questions and endings as nodes, transitions as edges.

    A MultiDiGraph because one pair of nodes can legitimately be joined twice:
    in C02, Q1 leads to Q4 both by falling through when Q2 and Q3 are hidden and
    by rule R5 skipping there outright. Collapsing those into one edge would
    lose which rule produced which, and the rule is the whole point of being
    able to trace a route back to the QRE.
    """
    graph = nx.MultiDiGraph()
    graph.add_node(START, kind="start")

    ordered = sorted(
        [q for q in survey.questions if q.seq is not None], key=lambda q: q.seq
    )
    for question in ordered:
        guard = question.guard
        graph.add_node(
            question.question_id,
            kind="question",
            seq=question.seq,
            # The guard travels with the node, and its readable form travels
            # with it so a person can see why a question was skipped without
            # decoding a condition tree.
            has_guard=guard is not None and guard.condition is not None,
            guard=_condition_summary(guard.condition) if guard else None,
            guard_agreement=guard.agreement.value if guard else None,
        )

    for disposition in survey.dispositions:
        graph.add_node(
            disposition.disposition_id,
            kind="disposition",
            terminal=True,
            disposition_kind=disposition.kind,
            defined_in_source=disposition.defined_in_source,
        )

    # The spine: the order the QRE asks its questions in. A guard on the target
    # node decides whether it is actually shown, so falling through is the
    # default and every other edge is an exception to it.
    if ordered:
        graph.add_edge(START, ordered[0].question_id, kind="advance", rule_id=None)
    for earlier, later in zip(ordered, ordered[1:]):
        graph.add_edge(
            earlier.question_id, later.question_id, kind="advance", rule_id=None
        )

    completions = [d for d in survey.dispositions if d.kind == "complete"]
    if ordered and completions:
        graph.add_edge(
            ordered[-1].question_id,
            completions[0].disposition_id,
            kind="advance",
            rule_id=None,
        )

    for rule in survey.rules:
        if rule.kind is RuleKind.TERMINATE:
            edge_kind = "terminate"
        elif rule.kind is RuleKind.SKIP:
            edge_kind = "jump"
        else:
            # show and reject are not transitions; see the module docstring.
            continue

        source = rule.evaluation_point
        target = rule.destination.id
        if not source or not target:
            continue
        if source not in graph or target not in graph:
            continue
        graph.add_edge(
            source,
            target,
            kind=edge_kind,
            rule_id=rule.rule_id,
            condition=_condition_summary(rule.when),
            precedence=rule.precedence,
        )

    for quota in survey.quotas:
        if not quota.on_full or not quota.evaluation_point:
            continue
        if quota.evaluation_point not in graph or quota.on_full not in graph:
            continue
        graph.add_edge(
            quota.evaluation_point,
            quota.on_full,
            kind="quota_terminate",
            rule_id=quota.quota_id,
            # Depends on how many other people already answered this way, not on
            # anything this respondent did. Route discovery has to leave it out
            # of ordinary path enumeration or every route ends here.
            stateful=True,
        )

    return graph


def build_dependency_graph(survey: CanonicalSurvey) -> nx.DiGraph:
    """Which questions need an earlier answer before they can be asked or shown.

    Must be acyclic: a cycle would mean a question needing its own answer, which
    is a contradiction rather than an unusual survey. Two kinds of edge, because
    they constrain different things - piping decides what a question displays,
    a guard decides whether it is displayed at all.
    """
    graph = nx.DiGraph()
    for question in survey.questions:
        graph.add_node(question.question_id, kind="question", seq=question.seq)

    for dependency in survey.dependencies:
        if dependency.from_question in graph and dependency.to_question in graph:
            graph.add_edge(
                dependency.from_question,
                dependency.to_question,
                kind=dependency.kind.value,
                origin=dependency.origin.value,
            )

    for question in survey.questions:
        guard = question.guard
        if guard is None or guard.condition is None:
            continue
        for needed in _questions_in(guard.condition):
            if needed in graph and needed != question.question_id:
                if not graph.has_edge(needed, question.question_id):
                    graph.add_edge(needed, question.question_id, kind="guard")

    return graph


def _questions_in(condition) -> list[str]:
    found: list[str] = []

    def walk(node) -> None:
        for side in (node.left, node.right):
            if side is not None and side.question_id and side.question_id not in found:
                found.append(side.question_id)
        for child in node.operands:
            walk(child)

    walk(condition)
    return found


def build_rule_edge_map(
    survey: CanonicalSurvey, route: nx.MultiDiGraph
) -> dict[str, list[str]]:
    """Where each rule ended up in the graph.

    The traceability spine: it is what lets a failing test point back at the
    sentence in the QRE that asked for the behaviour. A rule mapping to nothing
    is reported by the checks below rather than passed over.
    """
    mapping: dict[str, list[str]] = {}
    for source, target, data in route.edges(data=True):
        rule_id = data.get("rule_id")
        if rule_id:
            mapping.setdefault(rule_id, []).append(f"{source}->{target}")

    for question in survey.questions:
        guard = question.guard
        if guard is None:
            continue
        for origin in guard.sources:
            if origin != "questionnaire":
                mapping.setdefault(origin, []).append(f"guard:{question.question_id}")

    for rule in survey.rules:
        if rule.kind is RuleKind.REJECT:
            # Real, and deliberately not an edge. Recorded so the coverage check
            # can tell "represented as a constraint" from "lost".
            mapping.setdefault(rule.rule_id, []).append("constraint")

    return mapping


# ---------------------------------------------------------------------------
# Checking the graph against the specification it came from
# ---------------------------------------------------------------------------


def check(
    survey: CanonicalSurvey,
    route: nx.MultiDiGraph,
    dependency: nx.DiGraph,
    rule_map: dict[str, list[str]],
) -> list[AuditFinding]:
    """Does the graph faithfully represent the specification?

    Deterministic, and comparing against the specification rather than against
    the QRE: this asks whether the view is faithful to what it was built from,
    which is a different question from whether the specification is right.
    """
    findings: list[AuditFinding] = []

    for question in survey.questions:
        if question.question_id not in route:
            findings.append(
                _finding(
                    "node_coverage",
                    FlagSeverity.BLOCKING,
                    f"{question.question_id} is in the specification but has no node.",
                    target=FlagTarget(kind="question", id=question.question_id),
                )
            )
    for disposition in survey.dispositions:
        if disposition.disposition_id not in route:
            findings.append(
                _finding(
                    "node_coverage",
                    FlagSeverity.BLOCKING,
                    f"Ending {disposition.disposition_id} has no node.",
                    target=FlagTarget(kind="disposition", id=disposition.disposition_id),
                )
            )

    for rule in survey.rules:
        if rule.rule_id not in rule_map:
            findings.append(
                _finding(
                    "rule_coverage",
                    FlagSeverity.BLOCKING,
                    (
                        f"Rule {rule.rule_id} reached neither an edge nor a guard "
                        "nor a constraint, so nothing in the graph represents it."
                    ),
                    target=FlagTarget(kind="rule", id=rule.rule_id),
                    evidence=rule.when_unread or "",
                )
            )

    for node, data in route.nodes(data=True):
        if data.get("kind") == "disposition" and route.out_degree(node):
            findings.append(
                _finding(
                    "termination",
                    FlagSeverity.BLOCKING,
                    f"Ending {node} has a way out of it, so it does not end anything.",
                    target=FlagTarget(kind="disposition", id=node),
                )
            )
        if data.get("kind") == "disposition" and not route.in_degree(node):
            findings.append(
                _finding(
                    "reachability",
                    FlagSeverity.WARNING,
                    f"Ending {node} cannot be reached from anywhere.",
                    target=FlagTarget(kind="disposition", id=node),
                )
            )
        if data.get("kind") == "disposition" and not data.get("defined_in_source", True):
            findings.append(
                _finding(
                    "termination",
                    FlagSeverity.WARNING,
                    (
                        f"Ending {node} is reachable but the QRE never says what "
                        "it shows the respondent."
                    ),
                    target=FlagTarget(kind="disposition", id=node),
                )
            )

    reachable = nx.descendants(route, START) | {START} if START in route else set()
    for node, data in route.nodes(data=True):
        if node not in reachable and data.get("kind") != "start":
            findings.append(
                _finding(
                    "reachability",
                    FlagSeverity.BLOCKING,
                    f"{node} cannot be reached from the start of the survey.",
                    target=FlagTarget(kind=data.get("kind", "node"), id=node),
                )
            )

    # A cycle in the route graph would mean a respondent going round forever.
    # Reported rather than raised, since a genuine loop construct would show up
    # the same way and needs a person to tell the two apart.
    simple = nx.DiGraph()
    simple.add_nodes_from(route.nodes())
    simple.add_edges_from((u, v) for u, v, _ in route.edges(keys=True))
    try:
        cycle = nx.find_cycle(simple, orientation="original")
        findings.append(
            _finding(
                "cycle",
                FlagSeverity.BLOCKING,
                "The route graph loops, so a respondent could go round forever.",
                evidence=" -> ".join(str(step[0]) for step in cycle),
            )
        )
    except nx.NetworkXNoCycle:
        pass

    if not nx.is_directed_acyclic_graph(dependency):
        try:
            cycle = nx.find_cycle(dependency, orientation="original")
            evidence = " -> ".join(str(step[0]) for step in cycle)
        except nx.NetworkXNoCycle:
            evidence = ""
        findings.append(
            _finding(
                "dependency_cycle",
                FlagSeverity.BLOCKING,
                (
                    "Questions depend on each other in a circle, so no order "
                    "exists in which they can all be asked."
                ),
                evidence=evidence,
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(survey: CanonicalSurvey) -> tuple[RouteGraphs, GraphReport]:
    route = build_route_graph(survey)
    dependency = build_dependency_graph(survey)
    rule_map = build_rule_edge_map(survey, route)
    findings = check(survey, route, dependency, rule_map)

    graphs = RouteGraphs(
        source=survey.source,
        route_graph=nx.node_link_data(route, edges="edges"),
        dependency_graph=nx.node_link_data(dependency, edges="edges"),
        rule_edge_map=rule_map,
    )
    report = GraphReport(
        source=survey.source,
        nodes=route.number_of_nodes(),
        edges=route.number_of_edges(),
        questions=sum(
            1 for _, d in route.nodes(data=True) if d.get("kind") == "question"
        ),
        dispositions=sum(
            1 for _, d in route.nodes(data=True) if d.get("kind") == "disposition"
        ),
        # Rules only. The map also holds quota ids, which produce edges but are
        # not rules, and counting those made it read as though more rules were
        # mapped than exist.
        rules_mapped=sum(1 for r in survey.rules if r.rule_id in rule_map),
        rules_total=len(survey.rules),
        quotas_mapped=sum(1 for q in survey.quotas if q.quota_id in rule_map),
        quotas_total=len(survey.quotas),
        dependency_edges=dependency.number_of_edges(),
        findings=findings,
        blocking=sum(1 for f in findings if f.severity is FlagSeverity.BLOCKING),
        passed=not any(f.severity is FlagSeverity.BLOCKING for f in findings),
    )
    return graphs, report
