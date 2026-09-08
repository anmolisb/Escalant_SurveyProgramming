"""Reader for Agent 1's real `part2_canonical.json`.

Matches the schema Agent 1 actually emits (verified against C01, C02, S01):

  envelope: schema_version, artifact, stage, survey_id, source_document, generated_at
  content:  source, semantics, metadata, questions, dispositions, rules,
            dependencies, randomization, quotas, quota_requirements,
            scenarios, requirements, review

Conditions in the real spec are left/right operand trees:

  {"op": "contains_any",
   "left":  {"question_id": "Q1", "aggregate": null, ...},
   "right": {"values": [...], "option_ids": [...], "text": ..., "number": ...},
   "operands": [], "source_text": "...", "origin": "inferred", "confidence": 0.99}

Compound nodes use op in {and, or, not} and carry children in `operands`.

Normalising that into `Cond` happens here, at load time, because it is parsing
rather than evaluation. B2 and B3 then work on the same parsed structure with
entirely different algorithms, which is where their independence lives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SpecError(Exception):
    pass


LOGICAL_OPS = {"and", "or", "not"}
COMPARISON_OPS = {"eq", "ne", "in", "not_in", "contains", "contains_any",
                  "contains_all", "set_eq", "answered", "not_answered",
                  "gt", "gte", "lt", "lte"}


# --------------------------------------------------------------------------
# Normalised condition
# --------------------------------------------------------------------------

@dataclass
class Cond:
    op: str
    left_qid: str | None = None
    left_aggregate: str | None = None
    right_option_ids: list[str] = field(default_factory=list)
    right_values: list[str] = field(default_factory=list)
    right_number: float | None = None
    right_qid: str | None = None
    operands: list["Cond"] = field(default_factory=list)
    source_text: str = ""
    origin: str = "extracted"
    confidence: float | None = None

    @property
    def is_logical(self) -> bool:
        return self.op in LOGICAL_OPS

    def mentioned(self) -> set[str]:
        if self.is_logical:
            out: set[str] = set()
            for child in self.operands:
                out |= child.mentioned()
            return out
        out = set()
        if self.left_qid:
            out.add(self.left_qid)
        if self.right_qid:
            out.add(self.right_qid)
        return out

    def size(self) -> int:
        if self.is_logical:
            return sum(c.size() for c in self.operands)
        return 1

    def render(self) -> str:
        if self.source_text:
            return self.source_text
        if self.is_logical:
            joiner = f" {self.op} "
            return "(" + joiner.join(c.render() for c in self.operands) + ")"
        rhs = (self.right_option_ids or self.right_values
               or ([self.right_number] if self.right_number is not None else [])
               or ([self.right_qid] if self.right_qid else []))
        return f"{self.left_qid} {self.op} {rhs}"


def parse_cond(node: Any) -> Cond | None:
    if not isinstance(node, dict):
        return None
    op = str(node.get("op") or "").lower()
    if not op:
        return None

    operands = [c for c in (parse_cond(o) for o in (node.get("operands") or [])) if c]

    left = node.get("left") or {}
    right = node.get("right") or {}
    if not isinstance(left, dict):
        left = {}
    if not isinstance(right, dict):
        right = {}

    return Cond(
        op=op,
        left_qid=(str(left["question_id"]) if left.get("question_id") else None),
        left_aggregate=(str(left["aggregate"]) if left.get("aggregate") else None),
        right_option_ids=[str(x) for x in (right.get("option_ids") or [])],
        right_values=([str(right["text"])] if right.get("text") is not None
                      else [str(v) for v in (right.get("values") or [])]),
        right_number=(float(right["number"]) if right.get("number") is not None else None),
        right_qid=(str(right["question_id"]) if right.get("question_id") else None),
        operands=operands,
        source_text=str(node.get("source_text") or ""),
        origin=str(node.get("origin") or "extracted"),
        confidence=node.get("confidence"),
    )


# --------------------------------------------------------------------------
# Spec objects
# --------------------------------------------------------------------------

@dataclass
class Option:
    option_id: str
    label: str
    code: str | None = None
    numeric_value: float | None = None
    exclusive: bool = False


@dataclass
class Validation:
    raw: dict = field(default_factory=dict)

    def get(self, key, default=None):
        v = self.raw.get(key, default)
        return default if v is None else v

    @property
    def mandatory(self) -> bool:
        return bool(self.raw.get("mandatory", True))

    @property
    def constraints(self) -> list[str]:
        skip = {"mandatory", "mandatory_origin", "exclusive_option_label"}
        return sorted(k for k, v in self.raw.items()
                      if v is not None and k not in skip)

    @property
    def has_constraint(self) -> bool:
        return bool(self.constraints)


@dataclass
class Question:
    id: str
    seq: int
    kind: str
    wording: str = ""
    options: list[Option] = field(default_factory=list)
    matrix_rows: list[str] = field(default_factory=list)
    validation: Validation = field(default_factory=Validation)
    guard: Cond | None = None
    guard_origin: str | None = None
    guard_agreement: str | None = None
    option_source: dict | None = None
    source_reference: dict = field(default_factory=dict)

    @property
    def is_multi(self) -> bool:
        return self.kind == "multi"

    @property
    def mandatory(self) -> bool:
        return self.validation.mandatory

    def option_by_id(self, oid: str) -> Option | None:
        return next((o for o in self.options if o.option_id == str(oid)), None)

    def option_by_label(self, label: str) -> Option | None:
        t = str(label).strip().lower()
        return next((o for o in self.options if o.label.strip().lower() == t), None)

    def resolve(self, value: Any) -> str | None:
        if value is None:
            return None
        o = self.option_by_id(str(value)) or self.option_by_label(str(value))
        return o.option_id if o else None

    def usable_options(self, exclude: set[str] | None = None) -> list[Option]:
        exclude = exclude or set()
        return [o for o in self.options
                if o.option_id not in exclude and not o.exclusive]


@dataclass
class Rule:
    id: str
    kind: str                       # terminate | skip | show | reject
    when: Cond | None
    destination_id: str | None
    destination_kind: str | None
    evaluation_point: str | None
    precedence: int
    source_reference: dict = field(default_factory=dict)


@dataclass
class Disposition:
    id: str
    kind: str
    message: str | None
    terminal: bool = True
    defined_in_source: bool = True
    source_reference: dict = field(default_factory=dict)


@dataclass
class QuotaCell:
    option_id: str
    option_label: str
    target_percent: float | None
    target_count: int | None


@dataclass
class Quota:
    id: str
    enforcement: str
    variable_question_id: str
    cells: list[QuotaCell]
    on_full: str | None
    evaluation_point: str | None
    origin: str
    source_text: str = ""


@dataclass
class Dependency:
    from_question: str
    to_question: str
    kind: str
    detail: str = ""
    origin: str = "derived"
    source_reference: dict = field(default_factory=dict)


@dataclass
class Randomization:
    question_id: str
    scope: str
    anchored: list[str]
    anchored_origin: str
    capture_display_order: bool = True
    source_reference: dict = field(default_factory=dict)

    @property
    def anchors_stated(self) -> bool:
        return self.anchored_origin not in ("ambiguous", "unknown", None)


@dataclass
class Scenario:
    id: str
    purpose: str
    inputs: dict[str, Any]
    expected_end: str | None
    expected_visible: list[str] = field(default_factory=list)
    expected_hidden: list[str] = field(default_factory=list)
    expected_validation_error: list[str] = field(default_factory=list)


@dataclass
class CanonicalSpec:
    survey_id: str
    source_file: str
    source_sha256: str
    schema_version: str
    generated_at: str
    semantics_raw: dict
    questions: list[Question]
    rules: list[Rule]
    dispositions: list[Disposition]
    quotas: list[Quota]
    dependencies: list[Dependency]
    randomization: list[Randomization]
    scenarios: list[Scenario]
    review: list[dict]
    raw: dict
    # Supplied as a run input, not read from the QRE. Without it a quota stated
    # as a percentage has no countable target.
    sample_size: int | None = None

    def question(self, qid: str) -> Question | None:
        return next((q for q in self.questions if q.id == str(qid)), None)

    def in_order(self) -> list[Question]:
        return sorted(self.questions, key=lambda q: q.seq)

    def disposition(self, did: str) -> Disposition | None:
        return next((d for d in self.dispositions if d.id == str(did)), None)

    def rule(self, rid: str) -> Rule | None:
        return next((r for r in self.rules if r.id == str(rid)), None)


def load(path: str | Path, sample_size: int | None = None,
         anchors: dict[str, list[str]] | None = None) -> CanonicalSpec:
    path = Path(path)
    if not path.exists():
        raise SpecError(f"canonical spec not found: {path}")

    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("artifact") not in (None, "part2_canonical"):
        raise SpecError(f"not a part2_canonical artifact: {doc.get('artifact')}")

    content = doc.get("content")
    if not isinstance(content, dict) or "questions" not in content:
        raise SpecError("canonical spec has no content.questions block")

    src = doc.get("source_document") or {}

    questions = []
    for q in content["questions"]:
        guard_block = q.get("guard") or {}
        guard = parse_cond(guard_block.get("condition")) if guard_block else None
        questions.append(Question(
            id=str(q["question_id"]),
            seq=int(q.get("seq", 0)),
            kind=str(q.get("kind", "single")),
            wording=str(q.get("wording") or ""),
            options=[Option(
                option_id=str(o["option_id"]),
                label=str(o.get("label") or ""),
                code=o.get("code"),
                numeric_value=o.get("numeric_value"),
                exclusive=bool(o.get("is_exclusive")),
            ) for o in (q.get("options") or [])],
            # Matrix rows arrive as option-shaped dicts, not strings. Keeping
            # the row id is what lets an answer be addressed row by row.
            matrix_rows=[str(r.get("option_id") or r.get("label"))
                         if isinstance(r, dict) else str(r)
                         for r in (q.get("matrix_rows") or [])],
            validation=Validation(raw=q.get("validation") or {}),
            guard=guard,
            guard_origin=(guard.origin if guard else None),
            guard_agreement=guard_block.get("agreement"),
            option_source=q.get("option_source"),
            source_reference=q.get("source_reference") or {},
        ))

    rules = []
    for r in content.get("rules") or []:
        dest = r.get("destination") or {}
        rules.append(Rule(
            id=str(r["rule_id"]),
            kind=str(r.get("kind") or ""),
            when=parse_cond(r.get("when")),
            destination_id=(str(dest["id"]) if dest.get("id") else None),
            destination_kind=(str(dest["kind"]) if dest.get("kind") else None),
            evaluation_point=(str(r["evaluation_point"])
                              if r.get("evaluation_point") else None),
            precedence=int(r.get("precedence") or 0),
            source_reference=r.get("source_reference") or {},
        ))

    dispositions = [Disposition(
        id=str(d["disposition_id"]),
        kind=str(d.get("kind") or "complete"),
        message=d.get("message"),
        terminal=bool(d.get("terminal", True)),
        defined_in_source=bool(d.get("defined_in_source", True)),
        source_reference=d.get("source_reference") or {},
    ) for d in (content.get("dispositions") or [])]

    quotas = [Quota(
        id=str(q["quota_id"]),
        enforcement=str(q.get("enforcement") or "hard"),
        variable_question_id=str(q.get("variable_question_id") or ""),
        cells=[QuotaCell(
            option_id=str(c.get("option_id") or c.get("option_label")),
            option_label=str(c.get("option_label") or ""),
            target_percent=c.get("target_percent"),
            target_count=c.get("target_count"),
        ) for c in (q.get("cells") or [])],
        on_full=q.get("on_full"),
        evaluation_point=q.get("evaluation_point"),
        origin=str(q.get("origin") or "extracted"),
        source_text=str(q.get("source_text") or ""),
    ) for q in (content.get("quotas") or [])]

    dependencies = [Dependency(
        from_question=str(d.get("from_question") or ""),
        to_question=str(d.get("to_question") or ""),
        kind=str(d.get("kind") or ""),
        detail=str(d.get("detail") or ""),
        origin=str(d.get("origin") or "derived"),
        source_reference=d.get("source_reference") or {},
    ) for d in (content.get("dependencies") or [])]

    randomization = [Randomization(
        question_id=str(r.get("question_id") or ""),
        scope=str(r.get("scope") or "options"),
        anchored=[str(a) for a in (r.get("anchored") or [])],
        anchored_origin=str(r.get("anchored_origin") or "unknown"),
        capture_display_order=bool(r.get("capture_display_order", True)),
        source_reference=r.get("source_reference") or {},
    ) for r in (content.get("randomization") or [])]

    scenarios = []
    for sc in content.get("scenarios") or []:
        expected_end = None
        visible: list[str] = []
        hidden: list[str] = []
        errors: list[str] = []
        for e in (sc.get("expectations") or []):
            kind = str(e.get("kind") or "")
            targets = [str(t) for t in (e.get("targets") or [])]
            if kind == "expected_end":
                expected_end = targets[0] if targets else (
                    str(e["value"]) if e.get("value") else None)
            elif kind == "expected_visible":
                visible.extend(targets)
            elif kind == "expected_hidden":
                hidden.extend(targets)
            elif kind == "expected_validation_error":
                errors.extend(targets)
        scenarios.append(Scenario(
            id=str(sc["scenario_id"]),
            purpose=str(sc.get("purpose") or ""),
            inputs=dict(sc.get("inputs_raw") or {}),
            expected_end=expected_end,
            expected_visible=visible,
            expected_hidden=hidden,
            expected_validation_error=errors,
        ))

    # Two things the QRE never states but a test needs. Both arrive as run
    # inputs rather than being guessed, and both are recorded so a reviewer can
    # see that the value came from the project rather than from Agent 3.
    #
    # Anchors: which options stay pinned while the rest shuffle. Supplied by
    # label, matched to option ids here.
    if anchors:
        for r in randomization:
            if r.question_id not in anchors:
                continue
            wanted = anchors[r.question_id]
            if not wanted:
                # An explicit empty list is an answer, not a missing one: the
                # project has confirmed this question has no pinned options, so
                # there is no anchor behaviour to test rather than an untested
                # one. Recording the origin is what lets B1 tell the two apart.
                r.anchored = []
                r.anchored_origin = "project_input_none"
                continue
            q = next((x for x in questions if x.id == r.question_id), None)
            resolved = []
            for label in wanted:
                oid = q.resolve(label) if q else None
                resolved.append(oid or label)
            r.anchored = resolved
            r.anchored_origin = "project_input"

    # A quota stated as a percentage becomes a testable count only once the
    # total sample size is known.
    if sample_size:
        for quota in quotas:
            for cell in quota.cells:
                if cell.target_count is None and cell.target_percent is not None:
                    cell.target_count = max(
                        1, round(sample_size * cell.target_percent / 100.0))

    return CanonicalSpec(
        sample_size=sample_size,
        survey_id=str(doc.get("survey_id") or path.parent.name),
        source_file=str(src.get("filename") or content.get("source") or ""),
        source_sha256=str(src.get("sha256") or ""),
        schema_version=str(doc.get("schema_version") or ""),
        generated_at=str(doc.get("generated_at") or ""),
        semantics_raw=content.get("semantics") or {},
        questions=questions,
        rules=rules,
        dispositions=dispositions,
        quotas=quotas,
        dependencies=dependencies,
        randomization=randomization,
        scenarios=scenarios,
        review=list(content.get("review") or []),
        raw=doc,
    )
