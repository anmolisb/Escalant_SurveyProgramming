"""Agent 1 evaluation — derive tests from the QRE, then run them on the canonical output.

The tests come from `qre_oracle`, which reads the document independently. None
of them is derived from `part2_canonical.json`, because a test written from the
answer proves only that the answer equals itself.

Where the document does not independently establish what the right answer is —
a prose condition a model had to interpret, an evaluation point the QRE never
states, whether a shuffled exclusive option stays anchored — the test is
emitted with `ground_truth_status: UNVERIFIED` and its result is UNVERIFIED.
That is not a soft pass. It marks the places where only a person can say
whether the pipeline was right, and those are collected into the confirmation
gate rather than averaged away.

Executable logic is tested by running it. A routing condition the QRE wrote
formally is parsed by the oracle's own reference parser, evaluated against a
made-up answer state, and compared with what the canonical condition tree does
with the same state — once where the rule should fire and once where it should
not. A condition that is merely transcribed correctly but means the wrong thing
fails that test and passes a string comparison, which is the whole reason for
doing it this way.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import qre_oracle
from models import CanonicalSurvey, ConditionOp, RuleKind

CRITICAL = "CRITICAL"
HIGH = "HIGH"
NORMAL = "NORMAL"

VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

#: Categories whose failure changes what a respondent is asked or where they go.
#: Kept as data so the recall metric and the verdict agree on what "critical"
#: means instead of each deciding separately.
EXECUTABLE_CATEGORIES = {
    "display_logic", "skip_logic", "routing_logic", "termination_logic",
    "validation_rules", "dependencies_piping", "quotas", "randomization",
}

#: `Validate: {...}` keys, as documents write them, against the canonical field
#: that holds each. A key with no entry here is not an error - it is carried in
#: the question's `extra` and checked there.
_VALIDATION_ALIASES = {
    "min_length": "min_length", "max_length": "max_length",
    "min_value": "min_value", "max_value": "max_value",
    "min_selections": "min_selections",
    "sum": "sum_to", "sum_to": "sum_to",
    "require_each_row": "require_each_row",
}


@dataclass
class TestCase:
    test_id: str
    category: str
    check: str
    source_reference: dict
    source_text: str
    target: str
    input_state: Any
    expected: Any
    criticality: str
    ground_truth_status: str
    params: dict = field(default_factory=dict)


@dataclass
class TestResult:
    test_id: str
    category: str
    criticality: str
    status: str
    expected: Any
    actual: Any
    evidence: str
    canonical_reference: str
    explanation: str
    severity: str


# ---------------------------------------------------------------------------
# Building the tests
# ---------------------------------------------------------------------------


def _ref(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


def _cases_for(condition, question) -> list[tuple[dict, bool]] | None:
    """A pair of answer states and what the QRE's own condition does with each.

    The expected outcome is computed by running the reference condition, never
    assumed from the position of the state in the pair. Assuming it was wrong
    for every `!=` rule in the corpus: the state built from the literal makes
    an equality true and an inequality false, and pairing it with True either
    way reported a correct reading as a defect.

    Returns None where no pair can be built, or where both states give the same
    answer - a pair that does not separate the two outcomes tests nothing.
    """
    states = _candidate_states(condition, question)
    if states is None:
        return None
    cases = []
    for state in states:
        outcome = qre_oracle.evaluate_reference(condition, state)
        if outcome is None:
            return None
        cases.append((state, outcome))
    if len({outcome for _, outcome in cases}) < 2:
        return None
    return cases


def _candidate_states(condition, question) -> tuple[dict, dict] | None:
    """Two answers a respondent could really give, drawn from the QRE's options.

    Returns None where no such pair can be made - a numeric comparison on a
    question with no options, say - and the caller reports UNVERIFIED rather
    than inventing an answer.
    """
    labels = [o.label for o in question.options] if question else []
    literal = condition.literal
    if condition.aggregate:
        if not isinstance(literal, (int, float)):
            return None
        # A constant sum: one allocation that meets the total and one that misses.
        return ({condition.question_id: {"a": literal}},
                {condition.question_id: {"a": literal - 10}})

    if isinstance(literal, list):
        if not all(v in labels for v in literal) if labels else True:
            if not labels:
                return None
        others = [l for l in labels if l not in literal]
        if not others:
            return None
        if condition.op in ("eq", "ne"):
            return ({condition.question_id: list(literal)},
                    {condition.question_id: list(literal) + [others[0]]})
        return ({condition.question_id: literal[0]}, {condition.question_id: others[0]})

    if isinstance(literal, str):
        if labels and literal not in labels:
            return None
        others = [l for l in labels if l != literal]
        if not others:
            return None
        return ({condition.question_id: literal}, {condition.question_id: others[0]})
    return None


def build_tests(oracle: qre_oracle.OracleDocument) -> list[TestCase]:
    tests: list[TestCase] = []
    counter = {"n": 0}

    def add(category, check, *, source_text, target, expected, criticality,
            ground_truth=VERIFIED, source_reference=None, input_state=None, **params):
        counter["n"] += 1
        tests.append(TestCase(
            test_id="T%03d" % counter["n"],
            category=category, check=check,
            source_reference=source_reference or {},
            source_text=source_text, target=target,
            input_state=input_state, expected=expected,
            criticality=criticality, ground_truth_status=ground_truth,
            params=params,
        ))

    # -- questions, types, options ------------------------------------------
    for q in oracle.questions:
        ref = _ref(section="questionnaire", block_order=q.block_order, row_index=q.row_index)
        add("question_extraction", "question_present", source_text=q.wording,
            target=q.question_id, expected=q.question_id, criticality=HIGH, source_reference=ref)
        add("question_extraction", "question_seq", source_text="row %d" % q.row_index,
            target=q.question_id, expected=q.seq, criticality=HIGH, source_reference=ref)
        add("question_type", "question_type", source_text=q.type,
            target=q.question_id, expected=q.type, criticality=HIGH, source_reference=ref)
        if q.options:
            add("options", "option_labels", source_text="; ".join(o.label for o in q.options),
                target=q.question_id, expected=[o.label for o in q.options],
                criticality=HIGH, source_reference=ref)
            coded = {o.label: o.code for o in q.options if o.code is not None}
            if coded:
                add("options", "option_codes", source_text="; ".join(
                        "%s=%s" % (c, l) for l, c in coded.items()),
                    target=q.question_id, expected=coded, criticality=HIGH, source_reference=ref)
        if q.matrix_rows:
            add("options", "matrix_rows", source_text="; ".join(o.label for o in q.matrix_rows),
                target=q.question_id, expected=[o.label for o in q.matrix_rows],
                criticality=HIGH, source_reference=ref)

        # -- display logic --------------------------------------------------
        if q.display_condition:
            add("display_logic", "guard_present", source_text=q.display_condition,
                target=q.question_id, expected=q.display_condition,
                criticality=CRITICAL, source_reference=ref)
            reference = qre_oracle.parse_reference(q.display_condition)
            if reference is None:
                add("display_logic", "guard_reading_unverifiable",
                    source_text=q.display_condition, target=q.question_id,
                    expected="a reading a person must confirm", criticality=CRITICAL,
                    ground_truth=UNVERIFIED, source_reference=ref)
            else:
                source_q = oracle.question(reference.question_id)
                cases = _cases_for(reference, source_q)
                if cases is None:
                    add("display_logic", "guard_reading_unverifiable",
                        source_text=q.display_condition, target=q.question_id,
                        expected="no answer pair could be built from the QRE",
                        criticality=CRITICAL, ground_truth=UNVERIFIED, source_reference=ref)
                else:
                    for state, outcome in cases:
                        add("display_logic", "condition_eval", source_text=q.display_condition,
                            target=q.question_id, expected=outcome, criticality=CRITICAL,
                            source_reference=ref, input_state=state, subject="question")
        elif q.always_shown:
            add("display_logic", "guard_absent", source_text="Always show",
                target=q.question_id, expected=None, criticality=CRITICAL, source_reference=ref)

        # -- validation -----------------------------------------------------
        for key, value in q.validate.items():
            if key in _VALIDATION_ALIASES:
                add("validation_rules", "validation_field",
                    source_text="%s: %s" % (key, value), target=q.question_id,
                    expected=value, criticality=CRITICAL, source_reference=ref,
                    field=_VALIDATION_ALIASES[key])
            elif key == "exclusive_option":
                add("validation_rules", "exclusive_option",
                    source_text="%s: %s" % (key, value), target=q.question_id,
                    expected=value, criticality=CRITICAL, source_reference=ref)
            else:
                add("validation_rules", "validation_extra",
                    source_text="%s: %s" % (key, value), target=q.question_id,
                    expected=value, criticality=NORMAL, source_reference=ref, field=key)
        add("validation_rules", "mandatory", source_text=("Optional" if q.optional else "not marked optional"),
            target=q.question_id, expected=(False if q.optional else True),
            criticality=CRITICAL, source_reference=ref)

        # -- dependencies / randomization ------------------------------------
        if q.option_source_text:
            named = [i for i in qre_oracle.QID.findall(q.option_source_text) if i != q.question_id]
            add("dependencies_piping", "option_source", source_text=q.option_source_text,
                target=q.question_id, expected=(named[0] if named else None),
                criticality=CRITICAL, source_reference=ref)
        if q.randomize:
            add("randomization", "randomization_present", source_text="Randomize",
                target=q.question_id, expected=True, criticality=CRITICAL, source_reference=ref)
            add("randomization", "randomization_anchoring", source_text="Randomize",
                target=q.question_id, expected="the QRE does not say what is anchored",
                criticality=CRITICAL, ground_truth=UNVERIFIED, source_reference=ref)
        for instruction in q.other_instructions:
            add("question_extraction", "instruction_preserved", source_text=instruction,
                target=q.question_id, expected=instruction, criticality=NORMAL, source_reference=ref)

    add("question_extraction", "question_count", source_text="questionnaire table",
        target="survey", expected=len(oracle.questions), criticality=HIGH)

    # -- routing -------------------------------------------------------------
    known_ids = {q.question_id for q in oracle.questions}
    message_codes = {m.code for m in oracle.messages if m.code}
    for rule in oracle.rules:
        ref = _ref(section="routing", block_order=rule.block_order, row_index=rule.row_index)
        action = rule.action.strip().lower()
        category = {"terminate": "termination_logic", "skip": "skip_logic"}.get(action, "routing_logic")
        add(category, "rule_present", source_text=rule.condition, target=rule.rule_id,
            expected=rule.rule_id, criticality=CRITICAL, source_reference=ref)
        add(category, "rule_action", source_text=rule.action, target=rule.rule_id,
            expected=action, criticality=CRITICAL, source_reference=ref)
        add(category, "rule_destination", source_text=rule.destination, target=rule.rule_id,
            expected=rule.destination, criticality=CRITICAL, source_reference=ref)
        add(category, "rule_condition_text", source_text=rule.condition, target=rule.rule_id,
            expected=rule.condition, criticality=CRITICAL, source_reference=ref)
        if action == "terminate" and rule.destination not in known_ids:
            add("termination_logic", "termination_defined", source_text=rule.destination,
                target=rule.rule_id,
                expected=("defined" if rule.destination in message_codes else "referenced but undefined"),
                criticality=CRITICAL, source_reference=ref, disposition=rule.destination)

        reference = qre_oracle.parse_reference(rule.condition)
        if reference is None:
            add(category, "rule_reading_unverifiable", source_text=rule.condition,
                target=rule.rule_id, expected="a reading a person must confirm",
                criticality=CRITICAL, ground_truth=UNVERIFIED, source_reference=ref)
        else:
            cases = _cases_for(reference, oracle.question(reference.question_id))
            if cases is None:
                add(category, "rule_reading_unverifiable", source_text=rule.condition,
                    target=rule.rule_id, expected="no answer pair could be built from the QRE",
                    criticality=CRITICAL, ground_truth=UNVERIFIED, source_reference=ref)
            else:
                for state, outcome in cases:
                    add(category, "condition_eval", source_text=rule.condition,
                        target=rule.rule_id, expected=outcome, criticality=CRITICAL,
                        source_reference=ref, input_state=state, subject="rule")
        add(category, "rule_provenance", source_text="row %d" % rule.row_index,
            target=rule.rule_id, expected=rule.row_index, criticality=NORMAL, source_reference=ref)
        add(category, "rule_evaluation_point", source_text=rule.condition, target=rule.rule_id,
            expected="the QRE states no evaluation point", criticality=CRITICAL,
            ground_truth=UNVERIFIED, source_reference=ref)

    add("routing_logic", "rule_count", source_text="routing table", target="survey",
        expected=len(oracle.rules), criticality=CRITICAL)

    # -- dispositions --------------------------------------------------------
    for message in oracle.messages:
        if not message.code:
            continue
        ref = _ref(section="messages", block_order=message.block_order)
        add("dispositions_messages", "disposition_message", source_text=message.text,
            target=message.code, expected=message.text, criticality=HIGH, source_reference=ref)

    # -- quotas --------------------------------------------------------------
    for statement in oracle.quotas:
        ref = _ref(section="quotas", block_order=statement.block_order)
        if statement.code:
            named = qre_oracle.QID.findall(statement.text)
            cells = dict(_percentages(statement.text))
            add("quotas", "quota_present", source_text=statement.text, target=statement.code,
                expected=statement.code, criticality=CRITICAL, source_reference=ref)
            add("quotas", "quota_variable", source_text=statement.text, target=statement.code,
                expected=(named[0] if named else None), criticality=CRITICAL, source_reference=ref)
            add("quotas", "quota_enforcement", source_text=statement.text, target=statement.code,
                expected=_enforcement(statement.text), criticality=CRITICAL, source_reference=ref)
            if cells:
                add("quotas", "quota_cells", source_text=statement.text, target=statement.code,
                    expected=cells, criticality=CRITICAL, source_reference=ref)
        else:
            add("quotas", "quota_statement_preserved", source_text=statement.text,
                target="quota-prose", expected=statement.text, criticality=CRITICAL,
                source_reference=ref)

    # -- scenarios, requirements, study --------------------------------------
    for scenario in oracle.scenarios:
        ref = _ref(section="scenarios", row_index=scenario.row_index)
        add("acceptance_scenarios", "scenario_present", source_text=scenario.purpose,
            target=scenario.scenario_id, expected=scenario.scenario_id,
            criticality=HIGH, source_reference=ref)
        add("acceptance_scenarios", "scenario_inputs", source_text=scenario.inputs_text,
            target=scenario.scenario_id, expected=scenario.inputs_raw,
            criticality=HIGH, source_reference=ref)
        add("acceptance_scenarios", "scenario_expected", source_text=scenario.expected_text,
            target=scenario.scenario_id, expected=scenario.expected_raw,
            criticality=HIGH, source_reference=ref)
    for statement in oracle.programming:
        add("programming_qa", "requirement_present", source_text=statement.text,
            target="requirements", expected=statement.text, criticality=NORMAL,
            source_reference=_ref(section="programming", block_order=statement.block_order))
    for statement in oracle.study:
        add("study_metadata", "metadata_present", source_text=statement.text,
            target=(statement.label or "study"), expected=statement.text, criticality=NORMAL,
            source_reference=_ref(section="study", block_order=statement.block_order))

    # -- provenance and stated assumptions -----------------------------------
    for kind in ("questions", "rules", "dispositions", "scenarios"):
        add("provenance", "provenance_complete", source_text="CLAUDE.md §15",
            target=kind, expected="every element carries a source reference",
            criticality=NORMAL, collection=kind)
    for name in ("unasked_reference", "rule_precedence", "multi_equality"):
        add("semantic_assumptions", "assumption_not_claimed_as_extracted",
            source_text="the QRE states nothing about this", target=name,
            expected="marked inferred or derived, never extracted", criticality=CRITICAL,
            ground_truth=UNVERIFIED, name=name)
    add("semantic_assumptions", "default_mandatory_traceable",
        source_text="a general instruction in the study section, if there is one",
        target="default_mandatory", expected="traceable to a statement in the document",
        criticality=CRITICAL)
    return tests


def _enforcement(text: str) -> str | None:
    lowered = text.lower()
    for word in ("hard", "soft"):
        if word in lowered:
            return word
    return None


def _percentages(text: str) -> list[tuple[str, float]]:
    """`North=20%, South=20%` read straight out of the sentence."""
    import re
    return [(m.group(1).strip(), float(m.group(2)))
            for m in re.finditer(r"([^,:;=]+?)\s*=\s*([\d.]+)\s*%", text)]


# ---------------------------------------------------------------------------
# Running the tests
# ---------------------------------------------------------------------------


def _canonical_eval(condition, state: dict) -> bool | None:
    """Evaluate a canonical condition tree against an answer state.

    Written here rather than imported because the pipeline has no evaluator and
    this is the checker, not the product. It follows the semantics the
    specification declares: `==` against a multi-select compares the whole
    answer set, and a condition naming a question that was never answered is
    false.
    """
    if condition is None:
        return None
    op = condition.op
    if op is ConditionOp.AND:
        parts = [_canonical_eval(c, state) for c in condition.operands]
        return None if any(p is None for p in parts) else all(parts)
    if op is ConditionOp.OR:
        parts = [_canonical_eval(c, state) for c in condition.operands]
        return None if any(p is None for p in parts) else any(parts)
    if op is ConditionOp.NOT:
        inner = _canonical_eval(condition.operands[0], state) if condition.operands else None
        return None if inner is None else not inner

    left, right = condition.left, condition.right
    if left is None or left.question_id is None:
        return None
    if left.question_id not in state:
        return False if op in (ConditionOp.ANSWERED,) else (
            True if op is ConditionOp.UNANSWERED else False)
    answer = state[left.question_id]
    if op is ConditionOp.ANSWERED:
        return True
    if op is ConditionOp.UNANSWERED:
        return False

    if left.aggregate is not None:
        values = answer.values() if isinstance(answer, dict) else (
            answer if isinstance(answer, (list, tuple)) else [answer])
        numbers = [v for v in values if isinstance(v, (int, float))]
        actual = sum(numbers) if left.aggregate.value == "sum" else len(list(values))
        target = right.number if right is not None else None
        if target is None:
            return None
        return {ConditionOp.EQ: actual == target, ConditionOp.NE: actual != target,
                ConditionOp.LT: actual < target, ConditionOp.LE: actual <= target,
                ConditionOp.GT: actual > target, ConditionOp.GE: actual >= target}.get(op)

    if right is None:
        return None
    wanted = right.values if right.values else ([right.text] if right.text is not None else None)
    answers = answer if isinstance(answer, list) else [answer]
    if wanted is None:
        if right.number is None:
            return None
        try:
            numeric = float(answer)
        except (TypeError, ValueError):
            return None
        return {ConditionOp.EQ: numeric == right.number, ConditionOp.NE: numeric != right.number,
                ConditionOp.LT: numeric < right.number, ConditionOp.LE: numeric <= right.number,
                ConditionOp.GT: numeric > right.number, ConditionOp.GE: numeric >= right.number}.get(op)

    if op in (ConditionOp.EQ, ConditionOp.SET_EQ, ConditionOp.NE):
        same = set(answers) == set(wanted)
        return same if op in (ConditionOp.EQ, ConditionOp.SET_EQ) else not same
    if op in (ConditionOp.IN, ConditionOp.CONTAINS_ANY):
        return any(a in wanted for a in answers)
    if op is ConditionOp.NOT_IN:
        return not any(a in wanted for a in answers)
    if op is ConditionOp.CONTAINS:
        return all(w in answers for w in wanted)
    if op is ConditionOp.CONTAINS_ALL:
        return all(w in answers for w in wanted)
    return None


def run_tests(tests: list[TestCase], survey: CanonicalSurvey,
              oracle: qre_oracle.OracleDocument) -> list[TestResult]:
    questions = {q.question_id: q for q in survey.questions}
    rules = {r.rule_id: r for r in survey.rules}
    dispositions = {d.disposition_id: d for d in survey.dispositions}
    quotas = {q.quota_id: q for q in survey.quotas}
    scenarios = {s.scenario_id: s for s in survey.scenarios}
    results: list[TestResult] = []

    def record(test, status, actual, evidence, reference, explanation):
        severity = {PASS: "none", UNVERIFIED: "review"}.get(
            status, "blocking" if test.criticality == CRITICAL else "warning")
        results.append(TestResult(
            test_id=test.test_id, category=test.category, criticality=test.criticality,
            status=status, expected=test.expected, actual=actual, evidence=evidence,
            canonical_reference=reference, explanation=explanation, severity=severity))

    for test in tests:
        check, target, params = test.check, test.target, test.params
        question = questions.get(target)
        rule = rules.get(target)

        if test.ground_truth_status == UNVERIFIED:
            actual, explanation = _describe_unverified(test, survey, questions, rules)
            record(test, UNVERIFIED, actual,
                   test.source_text, _reference_for(test, target),
                   explanation)
            continue

        if check == "question_present":
            ok = question is not None
            record(test, PASS if ok else FAIL, target if ok else None, test.source_text,
                   "questions[%s]" % target,
                   "present" if ok else "the QRE asks this question and the specification does not carry it")
        elif check == "question_count":
            actual = len(survey.questions)
            record(test, PASS if actual == test.expected else FAIL, actual,
                   "%d rows in the questionnaire table" % test.expected, "questions[]",
                   "counts agree" if actual == test.expected else "the specification carries a different number of questions")
        elif check == "question_seq":
            actual = question.seq if question else None
            record(test, PASS if actual == test.expected else FAIL, actual, test.source_text,
                   "questions[%s].seq" % target,
                   "asked in document order" if actual == test.expected else "position disagrees with the document")
        elif check == "question_type":
            actual = question.kind if question else None
            record(test, PASS if actual == test.expected else FAIL, actual, test.source_text,
                   "questions[%s].kind" % target,
                   "type carried as written" if actual == test.expected else "type differs from the QRE")
        elif check == "option_labels":
            actual = [o.label for o in question.options] if question else None
            record(test, PASS if actual == test.expected else FAIL, actual, test.source_text,
                   "questions[%s].options" % target,
                   "every option carried in order" if actual == test.expected else "option list differs from the QRE")
        elif check == "option_codes":
            actual = {o.label: o.code for o in question.options if o.code is not None} if question else None
            record(test, PASS if actual == test.expected else FAIL, actual, test.source_text,
                   "questions[%s].options[].code" % target,
                   "codes match" if actual == test.expected else "codes differ from the QRE")
        elif check == "matrix_rows":
            actual = [o.label for o in question.matrix_rows] if question else None
            record(test, PASS if actual == test.expected else FAIL, actual, test.source_text,
                   "questions[%s].matrix_rows" % target,
                   "rows carried" if actual == test.expected else "matrix rows differ from the QRE")
        elif check == "instruction_preserved":
            blob = json.dumps(question.extra, default=str) if question else ""
            ok = bool(question) and (test.expected in blob or any(
                test.expected in (r.detail or "") for r in survey.dependencies))
            record(test, PASS if ok else FAIL, blob[:160], test.source_text,
                   "questions[%s].extra" % target,
                   "instruction preserved" if ok else "an instruction the QRE states is not carried anywhere")

        elif check == "guard_present":
            guard = question.guard if question else None
            texts = " | ".join(guard.raw_texts) if guard else ""
            ok = guard is not None and test.expected in texts
            record(test, PASS if ok else FAIL, texts or None, test.source_text,
                   "questions[%s].guard" % target,
                   "display condition carried verbatim" if ok else "the QRE gives this question a display condition the specification does not carry")
        elif check == "guard_absent":
            guard = question.guard if question else None
            ok = guard is None or guard.condition is None
            record(test, PASS if ok else FAIL,
                   None if ok else "guard present", test.source_text,
                   "questions[%s].guard" % target,
                   "always shown, and unguarded" if ok else "the QRE says always show and the specification guards it")
        elif check == "condition_eval":
            subject = params.get("subject")
            condition = (question.guard.condition if subject == "question" and question and question.guard
                         else rule.when if rule else None)
            actual = _canonical_eval(condition, test.input_state)
            if condition is None:
                record(test, FAIL, None, test.source_text, _reference_for(test, target),
                       "no condition to evaluate: the rule was not read as a tree")
            elif actual is None:
                record(test, BLOCKED, None, test.source_text, _reference_for(test, target),
                       "the canonical condition could not be evaluated against this answer")
            else:
                ok = actual == test.expected
                record(test, PASS if ok else FAIL, actual,
                       "%s with %s" % (test.source_text, json.dumps(test.input_state, default=str)),
                       _reference_for(test, target),
                       "fires exactly when the QRE's own condition does" if ok
                       else "the reading disagrees with the QRE's condition on a real answer")

        elif check == "rule_present":
            record(test, PASS if rule else FAIL, target if rule else None, test.source_text,
                   "rules[%s]" % target,
                   "present" if rule else "a routing rule in the QRE reached nothing")
        elif check == "rule_count":
            actual = len(survey.rules)
            record(test, PASS if actual == test.expected else FAIL, actual,
                   "%d rows in the routing table" % test.expected, "rules[]",
                   "counts agree" if actual == test.expected else "rule counts disagree")
        elif check == "rule_action":
            actual = rule.kind.value if rule else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text, "rules[%s].kind" % target,
                   "action carried" if ok else "the action differs from the QRE")
        elif check == "rule_destination":
            actual = rule.destination.id if rule else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "rules[%s].destination" % target,
                   "destination carried" if ok else "the destination differs from the QRE")
        elif check == "rule_condition_text":
            actual = (rule.when.source_text if rule and rule.when else
                      rule.when_unread if rule else None)
            ok = actual is not None and test.expected.strip() in actual
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "rules[%s].when.source_text" % target,
                   "condition kept verbatim" if ok else "the condition text was not preserved")
        elif check == "rule_provenance":
            actual = rule.source_reference.row_index if rule and rule.source_reference else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "rules[%s].source_reference" % target,
                   "points at the row it came from" if ok else "provenance missing or pointing elsewhere")
        elif check == "termination_defined":
            code = params["disposition"]
            disposition = dispositions.get(code)
            if disposition is None:
                record(test, FAIL, None, test.source_text, "dispositions[%s]" % code,
                       "a rule terminates here and no ending exists for it")
            else:
                stated = bool(disposition.message)
                expected_defined = test.expected == "defined"
                ok = stated == expected_defined
                record(test, PASS if ok else FAIL,
                       "defined" if stated else "referenced but undefined",
                       test.source_text, "dispositions[%s]" % code,
                       "matches what the document defines" if ok
                       else "the specification disagrees with the document about whether this ending is defined")

        elif check == "validation_field":
            value = getattr(question.validation, params["field"], None) if question and question.validation else None
            ok = value == test.expected
            record(test, PASS if ok else FAIL, value, test.source_text,
                   "questions[%s].validation.%s" % (target, params["field"]),
                   "validation rule carried" if ok else "a validation rule the QRE states is missing or different")
        elif check == "validation_extra":
            value = (question.extra or {}).get(params["field"]) if question else None
            if value is None and question and question.validation:
                value = getattr(question.validation, params["field"], None)
            ok = value == test.expected
            record(test, PASS if ok else FAIL, value, test.source_text,
                   "questions[%s].extra.%s" % (target, params["field"]),
                   "setting preserved" if ok else "a setting the QRE states was dropped")
        elif check == "exclusive_option":
            validation = question.validation if question else None
            label = validation.exclusive_option_label if validation else None
            resolved = validation.exclusive_option_id if validation else None
            ok = label == test.expected and bool(resolved)
            record(test, PASS if ok else FAIL, {"label": label, "option_id": resolved},
                   test.source_text, "questions[%s].validation.exclusive_option_id" % target,
                   "exclusive option carried and resolved to an id" if ok
                   else "the exclusive option is missing, wrong, or not resolved to an option")
        elif check == "mandatory":
            validation = question.validation if question else None
            actual = validation.mandatory if validation else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "questions[%s].validation.mandatory" % target,
                   "matches what the document says" if ok
                   else "whether an answer is required disagrees with the document")

        elif check == "option_source":
            source = question.option_source if question else None
            actual = source.from_question if source else None
            ok = actual == test.expected
            linked = any(d.from_question == test.expected and d.to_question == target
                         for d in survey.dependencies)
            record(test, PASS if (ok and linked) else FAIL,
                   {"option_source": actual, "dependency": linked}, test.source_text,
                   "questions[%s].option_source" % target,
                   "the narrowing is recorded on the question and as a dependency" if (ok and linked)
                   else "a piped option list is not recorded where a consumer would look for it")
        elif check == "randomization_present":
            ok = any(r.question_id == target for r in survey.randomization)
            record(test, PASS if ok else FAIL, ok, test.source_text,
                   "randomization[%s]" % target,
                   "recorded" if ok else "the QRE randomises this question and the specification does not say so")

        elif check == "quota_present":
            record(test, PASS if target in quotas else FAIL, target if target in quotas else None,
                   test.source_text, "quotas[%s]" % target,
                   "present" if target in quotas else "a quota the QRE states is missing")
        elif check == "quota_variable":
            actual = quotas[target].variable_question_id if target in quotas else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "quotas[%s].variable_question_id" % target,
                   "counts the question the sentence names" if ok else "the quota counts a different question")
        elif check == "quota_enforcement":
            actual = quotas[target].enforcement if target in quotas else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "quotas[%s].enforcement" % target,
                   "hard or soft as written" if ok else "enforcement differs from the sentence")
        elif check == "quota_cells":
            actual = ({c.option_label: c.target_percent for c in quotas[target].cells}
                      if target in quotas else None)
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "quotas[%s].cells" % target,
                   "every group and target carried" if ok else "the cells differ from the sentence")
        elif check == "quota_statement_preserved":
            blob = (" ".join(q.source_text for q in survey.quotas)
                    + " ".join(r.text + " " + r.raw_text for r in survey.quota_requirements)
                    + " ".join(f.evidence or "" for f in survey.review))
            key = test.expected.split(".")[0][:40]
            ok = key in blob
            record(test, PASS if ok else FAIL, blob[:160], test.source_text,
                   "quotas[].source_text | quota_requirements[]",
                   "the sentence survives somewhere addressable" if ok
                   else "a quota sentence the QRE states is not carried anywhere")

        elif check == "disposition_message":
            disposition = dispositions.get(target)
            actual = disposition.message if disposition else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "dispositions[%s].message" % target,
                   "message carried verbatim" if ok else "the ending's message is missing or altered")

        elif check == "scenario_present":
            record(test, PASS if target in scenarios else FAIL,
                   target if target in scenarios else None, test.source_text,
                   "scenarios[%s]" % target,
                   "present" if target in scenarios else "an acceptance test the QRE wrote is not carried")
        elif check == "scenario_inputs":
            actual = scenarios[target].inputs_raw if target in scenarios else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "scenarios[%s].inputs_raw" % target,
                   "inputs carried exactly" if ok else "the scenario's inputs differ from the document")
        elif check == "scenario_expected":
            actual = scenarios[target].expected_raw if target in scenarios else None
            ok = actual == test.expected
            record(test, PASS if ok else FAIL, actual, test.source_text,
                   "scenarios[%s].expected_raw" % target,
                   "expected outcome carried exactly" if ok else "the scenario's expected outcome differs")

        elif check == "requirement_present":
            ok = any(r.text.strip() == test.expected.strip() for r in survey.requirements)
            record(test, PASS if ok else FAIL, ok, test.source_text, "requirements[]",
                   "carried" if ok else "a requirement the document makes is not carried")
        elif check == "metadata_present":
            ok = any(test.expected.strip() in (m.text or "") for m in survey.metadata)
            record(test, PASS if ok else FAIL, ok, test.source_text, "metadata[]",
                   "carried" if ok else "a study statement is not carried")

        elif check == "provenance_complete":
            collection = getattr(survey, params["collection"])
            if params["collection"] == "dispositions":
                collection = [d for d in collection if d.defined_in_source]
            missing = [getattr(x, "question_id", None) or getattr(x, "rule_id", None)
                       or getattr(x, "disposition_id", None) or getattr(x, "scenario_id", None)
                       for x in collection if x.source_reference is None]
            ok = not missing
            record(test, PASS if ok else FAIL, missing or "all present", test.source_text,
                   "%s[].source_reference" % params["collection"],
                   "every element points back at the document" if ok
                   else "elements carry no provenance, so a failure cannot be traced to a line")
        elif check == "default_mandatory_traceable":
            semantics = survey.semantics
            if semantics.default_mandatory is None:
                record(test, UNVERIFIED, None, test.source_text, "semantics.default_mandatory",
                       "no statement in the document sets a default, and none was assumed")
            else:
                traceable = any(semantics.default_mandatory_source.strip() in (m.text or "")
                                for m in survey.metadata)
                record(test, PASS if traceable else FAIL,
                       {"value": semantics.default_mandatory,
                        "origin": semantics.default_mandatory_origin.value},
                       semantics.default_mandatory_source, "semantics.default_mandatory",
                       "read from a statement the document makes" if traceable
                       else "a default is asserted that no statement in the document supports")
        else:
            record(test, BLOCKED, None, test.source_text, "-", "no checker for %r" % check)
    return results


def _reference_for(test: TestCase, target: str) -> str:
    if test.category in ("routing_logic", "skip_logic", "termination_logic"):
        return "rules[%s]" % target
    if test.category == "semantic_assumptions":
        return "semantics"
    return "questions[%s]" % target


def _describe_unverified(test, survey, questions, rules):
    """What the specification says, where the document does not say what is right."""
    check = test.check
    if check == "assumption_not_claimed_as_extracted":
        name = test.params["name"]
        value = getattr(survey.semantics, name, None)
        origin = getattr(survey.semantics, name + "_origin", None)
        return ({"value": value, "origin": getattr(origin, "value", None)},
                "the QRE states nothing here; the specification records a decision, "
                "marked %s, which a person has to confirm" % getattr(origin, "value", "?"))
    if check == "rule_evaluation_point":
        rule = rules.get(test.target)
        return (rule.evaluation_point if rule else None,
                "derived from the questions the condition names; the QRE never states when a rule is checked")
    if check in ("rule_reading_unverifiable", "guard_reading_unverifiable"):
        holder = rules.get(test.target) or questions.get(test.target)
        condition = getattr(holder, "when", None) or getattr(getattr(holder, "guard", None), "condition", None)
        return ({"read": condition is not None,
                 "origin": condition.origin.value if condition is not None else None},
                "the QRE states this in prose, so no independent expected answer exists; "
                "the reading is a model's and needs a human eye")
    if check == "randomization_anchoring":
        entry = next((r for r in survey.randomization if r.question_id == test.target), None)
        return ({"anchored": entry.anchored if entry else None,
                 "origin": entry.anchored_origin.value if entry else None},
                "the QRE says to randomise and never says what stays put")
    return (None, "the QRE does not independently establish an expected result")


# ---------------------------------------------------------------------------
# Coverage, per kind of logic
# ---------------------------------------------------------------------------

#: Every metric reported, and which test categories feed it. Targets are the
#: bar each has to clear; executable logic is held to 100% because one missed
#: routing rule is a wrong survey, not a rounding error.
_METRICS = [
    ("question_coverage", ("question_extraction",), 1.0),
    ("question_type_coverage", ("question_type",), 1.0),
    ("option_coverage", ("options",), 1.0),
    ("display_rule_coverage", ("display_logic",), 1.0),
    ("skip_rule_coverage", ("skip_logic",), 1.0),
    ("routing_rule_coverage", ("routing_logic",), 1.0),
    ("termination_coverage", ("termination_logic",), 1.0),
    ("validation_coverage", ("validation_rules",), 1.0),
    ("dependency_piping_coverage", ("dependencies_piping",), 1.0),
    ("randomization_coverage", ("randomization",), 1.0),
    ("quota_coverage", ("quotas",), 1.0),
    ("disposition_coverage", ("dispositions_messages",), 1.0),
    ("acceptance_scenario_coverage", ("acceptance_scenarios",), 1.0),
    ("programming_requirement_coverage", ("programming_qa",), 1.0),
    ("study_metadata_coverage", ("study_metadata",), 1.0),
    ("provenance_coverage", ("provenance",), 1.0),
]

_DEFINITIONS = {
    "question_coverage": "questions the QRE asks that the specification carries, in the right order",
    "question_type_coverage": "questions whose type is carried as the QRE wrote it",
    "option_coverage": "answer lists, codes and matrix rows carried exactly",
    "display_rule_coverage": "display conditions carried, and behaving as the QRE's own condition does",
    "skip_rule_coverage": "skip rules carried with their condition, action and destination",
    "routing_rule_coverage": "routing rules carried with their condition, action and destination",
    "termination_coverage": "terminate rules carried, and their endings accounted for",
    "validation_coverage": "validation instructions carried, including whether an answer is required",
    "dependency_piping_coverage": "piped option lists recorded on the question and as a dependency",
    "randomization_coverage": "questions the QRE randomises that the specification records",
    "quota_coverage": "quotas carried with their question, enforcement and cells",
    "disposition_coverage": "endings carried with the message the document gives them",
    "acceptance_scenario_coverage": "the QRE's own tests carried with inputs and expected outcome intact",
    "programming_requirement_coverage": "programming and QA requirements carried",
    "study_metadata_coverage": "study statements carried",
    "provenance_coverage": "element kinds where every member points back at the document",
    "critical_rule_recall": "executable logic - display, skip, routing, termination, validation, "
                            "dependencies, quotas, randomization - carried correctly",
}


def coverage(results: list[TestResult]) -> dict:
    report = {}
    for name, categories, target in _METRICS:
        subset = [r for r in results if r.category in categories]
        verifiable = [r for r in subset if r.status != UNVERIFIED]
        passed = [r for r in verifiable if r.status == PASS]
        report[name] = _metric(name, len(passed), len(verifiable), target,
                               unverified=len(subset) - len(verifiable))

    critical = [r for r in results if r.criticality == CRITICAL and r.status != UNVERIFIED]
    passed = [r for r in critical if r.status == PASS]
    report["critical_rule_recall"] = _metric(
        "critical_rule_recall", len(passed), len(critical), 1.0,
        unverified=len([r for r in results if r.criticality == CRITICAL and r.status == UNVERIFIED]))
    return report


def _metric(name, numerator, denominator, target, unverified=0) -> dict:
    result = (numerator / denominator) if denominator else None
    return {
        "definition": _DEFINITIONS.get(name, ""),
        "numerator": numerator,
        "denominator": denominator,
        "unverified_excluded": unverified,
        "result": None if result is None else round(result, 4),
        "target": target,
        "meets_target": None if result is None else result >= target,
    }


def to_json(items) -> list[dict]:
    return [asdict(i) for i in items]
