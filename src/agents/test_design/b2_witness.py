"""B2 - Scenario / Witness Generation. "Can it happen, and how?"

For each coverage target, decides whether some respondent answer-set reaches
it, and if so produces the minimal such set (the witness).

INDEPENDENCE - this is the point of the whole block pair, and it erodes easily.

B2 must not share evaluation logic with B3. If the same code both finds the
witness and predicts the outcome, a bug in that code produces a test and an
expected answer that agree with each other and are both wrong. No downstream
check can catch that, which is why the architecture insists on it.

The independence here is structural, not declared:

  B2 SOLVES   - walks a condition tree backwards, deriving what each question's
                answer must be for the condition to hold or fail. Its unit of
                work is a Requirement, and its failure mode is Conflict.
  B3 SIMULATES - takes a complete answer-set and walks the survey forwards,
                evaluating each condition against concrete values.

Different direction, different data structure, different failure mode. Neither
module imports the other, and there is deliberately no shared `conditions.py`
for them to agree through.

Graded search, cheapest first:
  1 direct assignment      condition names a question and admissible values
  2 conjunctive merge      AND branches merged, contradictions detected
  3 disjunctive first-fit  OR branches tried in order, minimal witness kept
  4 reachability closure   earlier terminations forced false
  5 solver (Z3)            arithmetic and large combination spaces

Levels 1 to 4 are implemented. Level 5 is reported as BOUND_REACHED rather than
guessed, so an unfinished search is never recorded as an impossibility.
"""

from __future__ import annotations

from typing import Any

from .models import (
    Witness,
    CoverageTarget,
    INFEASIBLE,
    BOUND_REACHED,
    QUOTA_SIZE_UNDEFINED,
    RANDOMIZATION_ANCHOR_UNDEFINED,
)
from .spec import CanonicalSpec, Cond, Question
from .semantics import Semantics, UNASKED, PRECEDENCE, MULTI_EQ


class Conflict(Exception):
    """Two requirements on the same question cannot both hold. Proven impossible."""


class BoundReached(Exception):
    """Search capped before finishing. Status unknown, not impossible."""


def _by_label(q: Question) -> dict[str, str]:
    return {o.label.strip().lower(): o.option_id for o in q.options}


def _solve_cross_question(spec: CanonicalSpec, cond, want: bool,
                          sem, used: set[str]) -> "Assignment":
    """Solve a condition of the form `Q5 contains Q6`.

    Two questions offering the same choices carry DIFFERENT option ids, so the
    comparison is on what the options mean, not on their ids. The two are
    matched by label, and a witness has to pick options that line up across
    both questions.
    """
    left = spec.question(cond.left_qid)
    right = spec.question(cond.right_qid)
    if left is None or right is None:
        raise BoundReached(f"cross-question comparison names a missing "
                           f"question: {cond.render()}")

    left_by_label = _by_label(left)
    shared = [(lbl, oid) for lbl, oid in _by_label(right).items()
              if lbl in left_by_label]
    if not shared:
        raise BoundReached(f"{left.id} and {right.id} share no comparable "
                           f"options: {cond.render()}")

    op = cond.op
    if op in ("contains", "contains_any", "contains_all", "in"):
        if want:
            # Make them agree: pick one shared option for both sides.
            label, right_oid = shared[0]
            left_oid = left_by_label[label]
            return {
                cond.left_qid: Requirement(must_include={left_oid},
                                           must_answer=True),
                cond.right_qid: Requirement(must_be={right_oid},
                                            must_answer=True),
            }
        # Make them disagree: the right question picks something the left did
        # not. Needs two distinct comparable options.
        if len(shared) < 2:
            raise BoundReached(
                f"{left.id} and {right.id} share only one option, so they "
                f"cannot be made to disagree: {cond.render()}")
        (label_a, _), (label_b, right_b) = shared[0], shared[1]
        return {
            cond.left_qid: Requirement(must_include={left_by_label[label_a]},
                                       must_exclude={left_by_label[label_b]},
                                       must_answer=True),
            cond.right_qid: Requirement(must_be={right_b}, must_answer=True),
        }

    if op in ("eq", "ne"):
        agree = (op == "eq") == want
        label, right_oid = shared[0]
        left_oid = left_by_label[label]
        if agree:
            return {
                cond.left_qid: Requirement(exact_set={left_oid},
                                           must_answer=True)
                if left.is_multi else Requirement(must_be={left_oid},
                                                  must_answer=True),
                cond.right_qid: Requirement(must_be={right_oid},
                                            must_answer=True),
            }
        if len(shared) < 2:
            raise BoundReached(f"cannot make {left.id} and {right.id} differ")
        label_b, right_b = shared[1]
        return {
            cond.left_qid: Requirement(must_be={left_by_label[label]},
                                       must_answer=True),
            cond.right_qid: Requirement(must_be={right_b}, must_answer=True),
        }

    raise BoundReached(f"unsupported cross-question operator `{op}`")


# --------------------------------------------------------------------------
# Requirement algebra
# --------------------------------------------------------------------------

class Requirement:
    """What one question's answer must look like."""

    __slots__ = ("must_be", "must_not_be", "must_include", "must_exclude",
                 "exact_set", "must_answer", "number")

    def __init__(self, must_be=None, must_not_be=None, must_include=None,
                 must_exclude=None, exact_set=None, must_answer=None, number=None):
        self.must_be: set[str] = set(must_be or ())
        self.must_not_be: set[str] = set(must_not_be or ())
        self.must_include: set[str] = set(must_include or ())
        self.must_exclude: set[str] = set(must_exclude or ())
        self.exact_set: set[str] | None = (set(exact_set)
                                           if exact_set is not None else None)
        self.must_answer: bool | None = must_answer
        self.number = number

    def merge(self, other: "Requirement") -> "Requirement":
        must_be = set(self.must_be)
        if self.must_be and other.must_be:
            must_be = self.must_be & other.must_be
            if not must_be:
                raise Conflict("two disjoint single-choice values required")
        elif other.must_be:
            must_be = set(other.must_be)

        if (self.exact_set is not None and other.exact_set is not None
                and self.exact_set != other.exact_set):
            raise Conflict("two different exact answer sets required")

        answer = None
        if False in (self.must_answer, other.must_answer):
            answer = False
        elif True in (self.must_answer, other.must_answer):
            answer = True

        out = Requirement(
            must_be=must_be,
            must_not_be=self.must_not_be | other.must_not_be,
            must_include=self.must_include | other.must_include,
            must_exclude=self.must_exclude | other.must_exclude,
            exact_set=(self.exact_set if self.exact_set is not None
                       else other.exact_set),
            must_answer=answer,
            number=(self.number if self.number is not None else other.number),
        )

        if out.must_be and out.must_be <= out.must_not_be:
            raise Conflict("required value is also forbidden")
        if out.must_include & out.must_exclude:
            raise Conflict("option required and forbidden at once")
        if out.exact_set is not None and (out.exact_set & out.must_exclude):
            raise Conflict("exact set contains a forbidden option")
        if out.must_answer is False and (out.must_be or out.must_include
                                         or out.exact_set):
            raise Conflict("question must be blank and must hold a value")
        return out


Assignment = dict[str, Requirement]


def _merge(a: Assignment, b: Assignment) -> Assignment:
    out = dict(a)
    for qid, req in b.items():
        out[qid] = out[qid].merge(req) if qid in out else req
    return out


# --------------------------------------------------------------------------
# Backward solve
# --------------------------------------------------------------------------

def _rhs_ids(spec: CanonicalSpec, cond: Cond) -> set[str]:
    """Prefer resolved option ids; fall back to resolving labels."""
    if cond.right_option_ids:
        return set(cond.right_option_ids)
    q = spec.question(cond.left_qid) if cond.left_qid else None
    out = set()
    for v in cond.right_values:
        rid = q.resolve(v) if q else None
        out.add(rid or str(v))
    return out


def _solve_comparison(spec: CanonicalSpec, cond: Cond, want: bool,
                      sem: Semantics, used: set[str]) -> Assignment:
    qid = cond.left_qid
    if not qid:
        raise BoundReached(f"comparison has no left question: {cond.render()}")

    q = spec.question(qid)
    op = cond.op
    ids = _rhs_ids(spec, cond)
    multi = bool(q and q.is_multi)

    # ---- level 5: arithmetic over a question's own numeric items ----
    if cond.left_aggregate == "sum" or op.startswith("sum"):
        if cond.right_number is None:
            raise BoundReached(f"aggregate with no target number: {cond.render()}")
        bound = cond.right_number
        if op in ("eq", "sum_eq"):
            target_total = bound if want else bound + 1
        elif op in ("ne", "sum_ne"):
            target_total = (bound + 1) if want else bound
        elif op in ("gt", "gte"):
            target_total = (bound + 1) if want else max(0, bound - 1)
        elif op in ("lt", "lte"):
            target_total = max(0, bound - 1) if want else bound + 1
        else:
            raise BoundReached(f"unsupported aggregate operator `{op}`")
        return {qid: Requirement(must_answer=True, number=target_total)}

    # ---- level 5: one question's answer compared against another's ----
    if cond.right_qid:
        return _solve_cross_question(spec, cond, want, sem, used)

    def R(**kw) -> Assignment:
        return {qid: Requirement(**kw)}

    if op == "answered":
        return R(must_answer=want)
    if op == "not_answered":
        return R(must_answer=not want)

    if op in ("eq", "set_eq"):
        if multi:
            used.add(MULTI_EQ)
            exact = (op == "set_eq") or sem.multi_eq_is_exact_set
            if exact:
                if want:
                    return R(exact_set=ids, must_answer=True)
                # Falsifying "the answer set is exactly these" has two routes:
                # drop a member, or add a non-member. Adding is strictly the
                # better choice, because dropping a member contradicts any
                # `contains` requirement on the same question elsewhere in the
                # condition. C02's R19 is precisely that shape -
                # `Q1 contains X and not (Q1 == [X])` - and the drop strategy
                # reported it impossible when the obvious witness is X plus
                # anything else.
                spare = [o.option_id for o in (q.options if q else [])
                         if o.option_id not in ids]
                if spare:
                    return R(must_include={spare[0]}, must_answer=True)
                if ids:
                    return R(must_exclude={sorted(ids)[0]}, must_answer=True)
                return R(must_answer=True)
            if want:
                return R(must_include=ids, must_answer=True)
            return R(must_exclude=ids, must_answer=True)
        if want:
            return R(must_be=ids, must_answer=True)
        return R(must_not_be=ids, must_answer=True)

    if op == "ne":
        flipped = Cond(op="eq", left_qid=qid, right_option_ids=list(ids),
                       right_values=cond.right_values, source_text=cond.source_text)
        return _solve_comparison(spec, flipped, not want, sem, used)

    if op == "in":
        if want:
            return R(must_be=ids, must_answer=True)
        return R(must_not_be=ids, must_answer=True)

    if op == "not_in":
        flipped = Cond(op="in", left_qid=qid, right_option_ids=list(ids),
                       right_values=cond.right_values, source_text=cond.source_text)
        return _solve_comparison(spec, flipped, not want, sem, used)

    if op in ("contains", "contains_all"):
        if want:
            return R(must_include=ids, must_answer=True)
        return R(must_exclude={sorted(ids)[0]} if ids else set(), must_answer=True)

    if op == "contains_any":
        if want:
            # Minimal witness: include exactly one, first in spec option order.
            if not ids:
                raise BoundReached("contains_any with no values")
            ordered = [o.option_id for o in (q.options if q else [])
                       if o.option_id in ids] or sorted(ids)
            return R(must_include={ordered[0]}, must_answer=True)
        return R(must_exclude=ids, must_answer=True)

    raise BoundReached(f"unsupported operator `{op}`")


def solve(spec: CanonicalSpec, cond: Cond | None, want: bool,
          sem: Semantics, used: set[str]) -> Assignment:
    if cond is None:
        if want:
            return {}
        raise Conflict("cannot falsify an absent condition")

    if cond.op == "not":
        if not cond.operands:
            raise BoundReached("`not` with no operand")
        return solve(spec, cond.operands[0], not want, sem, used)

    if cond.op in ("and", "or"):
        if not cond.operands:
            raise BoundReached(f"`{cond.op}` with no operands")
        effective = cond.op if want else ("or" if cond.op == "and" else "and")

        if effective == "and":
            acc: Assignment = {}
            for child in cond.operands:
                acc = _merge(acc, solve(spec, child, want, sem, used))
            return acc

        last: Exception | None = None
        for child in cond.operands:
            try:
                return solve(spec, child, want, sem, used)
            except (Conflict, BoundReached) as exc:
                last = exc
        raise (last or Conflict("no satisfiable branch"))

    return _solve_comparison(spec, cond, want, sem, used)


# --------------------------------------------------------------------------
# Reachability: a witness must survive earlier terminations
# --------------------------------------------------------------------------

def _reachable(spec: CanonicalSpec, assignment: Assignment, upto_seq: int,
               sem: Semantics, used: set[str],
               except_rule: str | None = None) -> Assignment:
    """Force every terminating rule evaluated before `upto_seq` to be false.

    Reaching Q11 proves nothing if the respondent was screened out at S1. This
    is the step that turns a locally-correct answer into a genuinely walkable
    one, and it is where most false-feasible verdicts would otherwise come from.
    """
    acc = assignment
    for rule in sorted(spec.rules, key=lambda r: (r.precedence, r.id)):
        if rule.kind != "terminate" or rule.when is None:
            continue
        if except_rule and rule.id == except_rule:
            continue
        point = spec.question(rule.evaluation_point) if rule.evaluation_point else None
        if point is not None and point.seq > upto_seq:
            continue
        if point is None:
            mentioned = [spec.question(q) for q in rule.when.mentioned()]
            seqs = [m.seq for m in mentioned if m]
            if seqs and min(seqs) > upto_seq:
                continue
        acc = _merge(acc, solve(spec, rule.when, False, sem, used))
        if rule.precedence:
            used.add(PRECEDENCE)
    return acc


# --------------------------------------------------------------------------
# Requirements to concrete answers
# --------------------------------------------------------------------------

def _concretise(spec: CanonicalSpec, assignment: Assignment) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for qid, req in sorted(assignment.items()):
        q = spec.question(qid)

        if req.must_answer is False:
            answers[qid] = None
            continue

        if q is None:
            answers[qid] = sorted(req.must_be)[0] if req.must_be else None
            continue

        if q.kind == "multi":
            if req.exact_set is not None:
                chosen = [o.option_id for o in q.options
                          if o.option_id in req.exact_set]
            else:
                chosen = [o.option_id for o in q.options
                          if o.option_id in req.must_include]
                if not chosen:
                    pool = q.usable_options(exclude=req.must_exclude)
                    if not pool:
                        # Every non-exclusive option is forbidden. An exclusive
                        # option ("None of these") is still a legitimate answer
                        # and is often the ONLY way to falsify a contains_any
                        # guard. Without this fallback B2 reports a
                        # false-infeasible, which the design requires to be 0.
                        pool = [o for o in q.options
                                if o.option_id not in req.must_exclude]
                    if not pool:
                        raise Conflict(f"{qid}: no admissible option remains")
                    chosen = [pool[0].option_id]
            if set(chosen) & req.must_exclude:
                raise Conflict(f"{qid}: witness would include a forbidden option")
            answers[qid] = chosen

        elif q.kind in ("single",):
            if req.must_be:
                chosen = next((o.option_id for o in q.options
                               if o.option_id in req.must_be), None)
                if chosen is None:
                    chosen = sorted(req.must_be)[0]
            else:
                pool = [o for o in q.options if o.option_id not in req.must_not_be]
                if not pool:
                    raise Conflict(f"{qid}: no admissible option remains")
                chosen = pool[0].option_id
            if chosen in req.must_not_be:
                raise Conflict(f"{qid}: witness would use a forbidden value")
            answers[qid] = chosen

        elif q.kind == "text":
            lo = q.validation.get("min_length", 1)
            answers[qid] = "x" * max(int(lo or 1), 1)

        elif q.kind == "matrix":
            scale = [o.option_id for o in q.options]
            rows = q.matrix_rows or []
            answers[qid] = {r: scale[0] for r in rows} if scale and rows else {}

        elif q.kind == "constant_sum":
            # The solver may have set the total it needs; otherwise use the
            # QRE's own required total.
            total = req.number if req.number is not None else q.validation.get("sum_to")
            rows = q.matrix_rows or [o.option_id for o in q.options]
            if total is not None and rows:
                total = int(total)
                share = total // len(rows)
                alloc = {r: share for r in rows}
                alloc[rows[0]] = total - share * (len(rows) - 1)
                answers[qid] = alloc
            else:
                answers[qid] = {}
        else:
            answers[qid] = None
    return answers


def _fill_journey(spec: CanonicalSpec, answers: dict[str, Any]) -> dict[str, Any]:
    """Complete the answer-set into a full respondent journey.

    Agent 4 runs a real respondent, not a fragment. An answer-set that names
    only the questions a condition mentions leaves every other mandatory
    question blank, and B3 then correctly predicts a mandatory-field error on
    each one. Those errors are artifacts of a partial witness, not expectations,
    and they would drown the real assertion in noise.

    So every question gets a benign valid answer unless the solver already
    decided it. Guarded questions are filled too: if the guard turns out false
    B3 marks the question hidden and never validates it, and if it turns out
    true an answer is required.
    """
    out = dict(answers)
    for q in spec.in_order():
        if q.id in out:
            continue
        if not q.mandatory:
            continue
        if q.kind == "single" and q.options:
            out[q.id] = q.options[0].option_id
        elif q.kind == "multi":
            pool = q.usable_options()
            if pool:
                out[q.id] = [pool[0].option_id]
        elif q.kind == "text":
            lo = q.validation.get("min_length", 1)
            out[q.id] = "x" * max(int(lo or 1), 1)
        elif q.kind == "matrix":
            scale = [o.option_id for o in q.options]
            if scale and q.matrix_rows:
                out[q.id] = {r: scale[0] for r in q.matrix_rows}
        elif q.kind == "constant_sum":
            total = q.validation.get("sum_to")
            rows = q.matrix_rows or [o.option_id for o in q.options]
            if total and rows:
                share = int(total) // len(rows)
                alloc = {r: share for r in rows}
                alloc[rows[0]] = int(total) - share * (len(rows) - 1)
                out[q.id] = alloc
    return out


# --------------------------------------------------------------------------
# Validation probes
# --------------------------------------------------------------------------

def _validation_probe(q: Question, polarity: str) -> tuple[Any, str]:
    v = q.validation
    cons = v.constraints

    if "min_length" in cons or "max_length" in cons:
        lo = v.get("min_length", 0) or 0
        hi = v.get("max_length")
        if polarity == "satisfied":
            n = int(lo) if lo else 1
            return "x" * max(n, 1), f"length {max(n,1)} meets [{lo}, {hi}]"
        if hi is not None:
            return "x" * (int(hi) + 1), f"length {int(hi)+1}, one over max {hi}"
        return "", f"empty string, under min {lo}"

    if "min_selections" in cons:
        lo = int(v.get("min_selections", 1))
        pool = [o.option_id for o in q.usable_options()]
        if polarity == "satisfied":
            if len(pool) < lo:
                raise BoundReached(f"only {len(pool)} options, need {lo}")
            return pool[:lo], f"exactly {lo} selections, the stated minimum"
        if lo <= 1:
            return [], "no selection, under the stated minimum"
        return pool[: lo - 1], f"{lo-1} selections, one under the minimum {lo}"

    if "require_each_row" in cons:
        scale = [o.option_id for o in q.options]
        rows = q.matrix_rows or []
        if not scale or not rows:
            raise BoundReached("matrix rows or scale points absent from spec")
        if polarity == "satisfied":
            return {r: scale[0] for r in rows}, "every row answered"
        return {r: scale[0] for r in rows[:-1]}, f"row `{rows[-1]}` left blank"

    if "exclusive_option_id" in cons:
        excl = v.get("exclusive_option_id")
        others = [o.option_id for o in q.options if o.option_id != excl]
        if polarity == "satisfied":
            return [excl], "exclusive option chosen alone"
        if not others:
            raise BoundReached("no other option to pair with the exclusive one")
        return [excl, others[0]], "exclusive option chosen alongside another"

    if "sum_to" in cons:
        total = int(v.get("sum_to"))
        rows = q.matrix_rows or [o.option_id for o in q.options]
        if not rows:
            raise BoundReached("constant-sum question has no items to allocate")
        target = total if polarity == "satisfied" else total - 1
        share = target // len(rows)
        alloc = {r: share for r in rows}
        alloc[rows[0]] = target - share * (len(rows) - 1)
        note = (f"the {len(rows)} numbers add up to exactly {total}"
                if polarity == "satisfied"
                else f"the numbers add up to {target}, one short of the "
                     f"required {total}")
        return alloc, note

    raise BoundReached(f"no probe strategy for {cons}")


# --------------------------------------------------------------------------
# Per-dimension strategies
# --------------------------------------------------------------------------

def generate(spec: CanonicalSpec, targets: list[CoverageTarget],
             sem: Semantics) -> list[Witness]:
    return [_one(spec, t, sem) for t in targets]


def _one(spec: CanonicalSpec, target: CoverageTarget, sem: Semantics) -> Witness:
    if target.predetermined_reason:
        return Witness(target_id=target.target_id, feasible=False,
                       method="predetermined", reason=target.predetermined_reason,
                       evidence=target.notes or "established at enumeration")

    used: set[str] = set()
    try:
        dispatched = _dispatch(spec, target, sem, used)
        if isinstance(dispatched, Witness):
            return dispatched
        answers, method, evidence = dispatched
    except Conflict as exc:
        return Witness(target_id=target.target_id, feasible=False, method="conflict",
                       reason=INFEASIBLE, evidence=f"proven impossible: {exc}")
    except BoundReached as exc:
        return Witness(target_id=target.target_id, feasible=False, method="bounded",
                       reason=BOUND_REACHED, evidence=str(exc))

    if answers is None:
        return Witness(target_id=target.target_id, feasible=False,
                       method=method, reason=BOUND_REACHED, evidence=evidence)

    if used:
        evidence = f"{evidence} [leaned on provisional semantics: {sorted(used)}]"
    return Witness(target_id=target.target_id, feasible=True, answers=answers,
                   method=method, evidence=evidence)


def _dispatch(spec, target, sem, used):
    d = target.dimension

    if d == "D1" and target.polarity == "advances":
        q = spec.question(target.subject)
        if q is None:
            raise Conflict("question absent from the spec")
        a = solve(spec, q.guard, True, sem, used) if q.guard is not None else {}
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        return answers, "answered normally, nothing forced to fire", \
            (f"{q.id} is reached and answered validly, so the respondent should "
             f"continue rather than stop here")

    if d == "D1" and target.polarity in ("shown", "hidden"):
        q = spec.question(target.subject)
        if q is None or q.guard is None:
            raise Conflict("question or guard absent from the spec")
        want = target.polarity == "shown"
        a = solve(spec, q.guard, want, sem, used)
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        return answers, "guard solved backwards", \
            f"guard of {q.id} forced {'true' if want else 'false'}: {q.guard.render()}"

    if d == "D1":  # skip_fired / skip_not_fired
        rule = spec.rule(target.subject.split(":")[0])
        if rule is None or rule.when is None:
            raise Conflict("skip rule or its condition absent from the spec")
        want = target.polarity == "skip_fired"
        point = spec.question(rule.evaluation_point) if rule.evaluation_point else None
        seq = point.seq if point else 10 ** 6
        a = solve(spec, rule.when, want, sem, used)
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        return answers, "skip condition solved backwards", \
            f"{rule.id} condition forced {'true' if want else 'false'}: {rule.when.render()}"

    if d == "D2":
        # The subject is either an ending id, or "ENDING<-RULE" naming one
        # specific route to it. A named route is solved through that rule and
        # no other, so a broken route cannot hide behind a working one.
        ending, _, named_rule = target.subject.partition("<-")
        disp = spec.disposition(ending)
        if disp is None:
            raise Conflict("disposition absent from the spec")
        if named_rule:
            rule = spec.rule(named_rule)
            if rule is None:
                raise Conflict(f"rule {named_rule} absent from the spec")
            point = spec.question(rule.evaluation_point) if rule.evaluation_point else None
            seq = point.seq if point else 10 ** 6
            a = solve(spec, rule.when, True, sem, used)
            a = _reachable(spec, a, 10 ** 6, sem, used, except_rule=rule.id)
            answers = _fill_journey(spec, _concretise(spec, a))
            if rule.precedence:
                used.add(PRECEDENCE)
            return answers, f"rule {rule.id} satisfied", \
                (f"{rule.id}, evaluated at {rule.evaluation_point}, routes to "
                 f"{ending}: {rule.when.render() if rule.when else ''}")
        target_subject = ending
        rules = [r for r in spec.rules if r.destination_id == ending]
        quota_sources = [q for q in spec.quotas if q.on_full == target_subject]
        if not rules and quota_sources:
            quota = quota_sources[0]
            cell = next((c for c in quota.cells
                         if c.target_count is not None), None)
            if cell is None:
                raise BoundReached("no sized quota cell routes to this ending")
            dq = spec.question(quota.variable_question_id)
            a = {quota.variable_question_id: Requirement(must_be={cell.option_id},
                                                         must_answer=True)}
            a = _reachable(spec, a, 10 ** 6, sem, used)
            answers = _fill_journey(spec, _concretise(spec, a))
            return Witness(
                target_id=target.target_id, feasible=True, answers=answers,
                method="quota fill campaign",
                evidence=(f"fill {quota.id} cell {cell.option_label!r} with "
                          f"{cell.target_count} respondents, then send one more"),
                preconditions={"quota_cell_full":
                               f"{quota.id}:{cell.option_id}"},
                campaign={"repetitions": cell.target_count,
                          "then_one_more": True,
                          "cell": f"{quota.id}:{cell.option_id}",
                          "label": cell.option_label})
        if not rules:
            if disp.kind == "complete":
                a = _reachable(spec, {}, 10 ** 6, sem, used)
                answers = _fill_journey(spec, _concretise(spec, a))
                return answers, "all terminations forced false", \
                    "respondent answers through without triggering any screenout"
            raise Conflict("no rule and no quota routes to this ending")
        rule = sorted(rules, key=lambda r: (r.precedence, r.id))[0]
        point = spec.question(rule.evaluation_point) if rule.evaluation_point else None
        seq = point.seq if point else 10 ** 6
        a = solve(spec, rule.when, True, sem, used)
        a = _reachable(spec, a, seq, sem, used, except_rule=rule.id)
        answers = _fill_journey(spec, _concretise(spec, a))
        if len(rules) > 1 or rule.precedence:
            used.add(PRECEDENCE)
        return answers, f"rule {rule.id} satisfied", \
            f"{rule.id} routes to {target.subject}: {rule.when.render() if rule.when else ''}"

    if d == "D3":
        q = spec.question(target.subject)
        if q is None:
            rule = spec.rule(target.subject)
            if rule is None:
                raise Conflict("neither question nor rule found")
            want = target.polarity == "violated"
            point = spec.question(rule.evaluation_point) if rule.evaluation_point else None
            seq = point.seq if point else 10 ** 6
            a = solve(spec, rule.when, want, sem, used)
            a = _reachable(spec, a, 10 ** 6, sem, used)
            answers = _fill_journey(spec, _concretise(spec, a))
            return answers, "reject-rule condition solved", \
                f"{rule.id} forced {'true' if want else 'false'}"
        probe, note = _validation_probe(q, target.polarity)
        a = solve(spec, q.guard, True, sem, used) if q.guard is not None else {}
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        answers[q.id] = probe
        return answers, "validation bound probed", f"{q.id}: {note}"

    if d == "D4":
        q = spec.question(target.subject)
        if q is None:
            raise Conflict("question absent from the spec")
        a = solve(spec, q.guard, True, sem, used) if q.guard is not None else {}
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        answers[q.id] = None
        verb = "blocks" if target.polarity == "enforced" else "permits"
        return answers, "blank answer probe", f"{q.id} left blank, expect it {verb} progress"

    if d in ("D5", "D6"):
        source, dest = target.subject.split("->")
        sq, dq = spec.question(source), spec.question(dest)
        if sq is None or dq is None:
            raise Conflict("dependency endpoint absent from the spec")
        a = solve(spec, dq.guard, True, sem, used) if dq.guard is not None else {}
        a = _merge(a, {source: Requirement(must_answer=True)})
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        if not answers.get(source):
            pool = sq.usable_options()
            if not pool:
                raise Conflict("source question has no usable option")
            answers[source] = ([pool[0].option_id] if sq.is_multi
                               else pool[0].option_id)
        what = "option list" if d == "D5" else "wording"
        return answers, "source answered, dependent question shown", \
            f"{source} answered so {dest}'s {what} can reflect it"

    if d == "D7":
        q = spec.question(target.subject)
        if q is None:
            raise Conflict("shuffled question absent from the spec")
        a = solve(spec, q.guard, True, sem, used) if q.guard is not None else {}
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        if target.polarity == "completeness":
            return answers, "reach the question and read its option list", \
                (f"count the options rendered at {q.id} against the "
                 f"{len(q.options)} the QRE lists")
        if target.polarity == "order_varies":
            rnd = next((r for r in spec.randomization
                        if r.question_id == q.id), None)
            return Witness(
                target_id=target.target_id, feasible=True, answers=answers,
                method="repeat-run comparison",
                evidence=(f"run this same path several times and compare the "
                          f"order in which {q.id}'s options appear; if the "
                          f"order never changes, shuffling is not switched on"),
                campaign={"repetitions": 5, "compare": "display_order",
                          "question": q.id})
        rnd = next((r for r in spec.randomization
                    if r.question_id == q.id), None)
        if rnd is None or not rnd.anchored:
            raise BoundReached("no anchor list available, so there is no "
                               "position to assert")
        return answers, "reach the question and read the rendered order", \
            (f"check that {rnd.anchored} hold their position at {q.id} while "
             f"the remaining options vary")

    if d == "D8":
        quota_id, cell_option = target.subject.split(":")
        quota = next((q for q in spec.quotas if q.id == quota_id), None)
        if quota is None:
            raise Conflict("quota absent from the spec")
        if target.polarity == "full":
            cell = next((c for c in quota.cells
                         if c.option_id == cell_option), None)
            if cell is None or cell.target_count is None:
                raise BoundReached("filling a cell needs a stated sample size, "
                                   "which the QRE does not give")
            dq = spec.question(quota.variable_question_id)
            seq = dq.seq if dq else 10 ** 6
            a = {quota.variable_question_id: Requirement(must_be={cell_option},
                                                         must_answer=True)}
            a = _reachable(spec, a, 10 ** 6, sem, used)
            answers = _fill_journey(spec, _concretise(spec, a))
            w = Witness(
                target_id=target.target_id, feasible=True, answers=answers,
                method="quota fill campaign",
                evidence=(f"send {cell.target_count} respondents with "
                          f"{quota.variable_question_id} answered "
                          f"{cell.option_label!r} so the cell reaches its "
                          f"target, then send one more with the same answers"),
                preconditions={"quota_cell_full": f"{quota.id}:{cell_option}"},
                campaign={"repetitions": cell.target_count,
                          "then_one_more": True,
                          "cell": f"{quota.id}:{cell_option}",
                          "label": cell.option_label})
            return w
        dq = spec.question(quota.variable_question_id)
        seq = dq.seq if dq else 10 ** 6
        a = {quota.variable_question_id: Requirement(must_be={cell_option},
                                                     must_answer=True)}
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        return answers, "quota dimension answered into the cell", \
            f"{quota.variable_question_id} answered {cell_option}"

    if d == "D9":
        source, dest = target.subject.split("+")
        dq = spec.question(dest)
        if dq is None:
            raise Conflict("interaction endpoint absent from the spec")
        a = solve(spec, dq.guard, True, sem, used) if dq.guard is not None else {}
        a = _merge(a, {source: Requirement(must_answer=True)})
        a = _reachable(spec, a, 10 ** 6, sem, used)
        answers = _fill_journey(spec, _concretise(spec, a))
        return answers, "guard satisfied with dependency present", \
            f"{dest} shown while dependent on {source}"

    raise BoundReached(f"no strategy for dimension {d}")
