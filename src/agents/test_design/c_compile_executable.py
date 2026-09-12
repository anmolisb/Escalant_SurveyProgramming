"""Block C - Executable Test Compiler.

Translates a logically verified scenario into the exact physical instructions
Agent 4 executes: real field names, real answer codes, never a label and never
a screen position.

Two rules the architecture insists on, both enforced here:

  1. **Refuse rather than guess.** If any field or value a scenario needs has
     no binding in the implementation snapshot, no test is produced at all and
     the reason names the missing identifier. A test with one guessed field is
     worse than no test, because it fails for a reason nobody can attribute.

  2. **Never assert something unobservable.** The logical layer predicts more
     than a respondent can see. Only the observable subset survives compilation.

THE TERMINATION REWRITE
-----------------------
The logical layer says `ending_reached == TERM_AGE`. That assertion cannot be
executed, because LimeSurvey has no terminate action and no page named TERM_AGE
exists. The Survey Builder inverts every terminate rule into the main group's
relevance and nests the disposition messages into one end screen.

So Block C rewrites the assertion into what is actually observable:

  - the screening group's questions were shown
  - no main-group question was shown
  - the end screen contains the disposition's message text

This is the single largest logical-to-physical divergence in the pipeline, and
it is why Block C exists as a translation stage rather than a formatting step.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from .a_implementation import ImplementationSnapshot, CHECKED, shared_messages
from .models import VerifiedScenario, CoverageTarget, COVERED, stable_id
from .spec import CanonicalSpec


@dataclass
class ExecutableStep:
    step: int
    action: str                      # set_field | submit_page | observe
    field_name: str | None = None
    sgqa: str | None = None
    value: str | None = None
    value_kind: str | None = None
    canonical: str | None = None     # what this came from, for traceability
    human: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExecutableAssertion:
    kind: str
    expected: Any
    field_name: str | None = None
    sgqa: str | None = None
    canonical: str | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExecutableTest:
    test_id: str
    target_id: str
    dimension: str
    title: str
    sid: int
    steps: list[ExecutableStep] = field(default_factory=list)
    assertions: list[ExecutableAssertion] = field(default_factory=list)
    traces_to: list[str] = field(default_factory=list)
    campaign: dict = field(default_factory=dict)
    executable: bool = True
    refusal_reason: str | None = None
    missing_bindings: list[str] = field(default_factory=list)
    provisional_semantics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["steps"] = [s.to_dict() for s in self.steps]
        d["assertions"] = [a.to_dict() for a in self.assertions]
        return d


# --------------------------------------------------------------------------
# Answer to field/value pairs
# --------------------------------------------------------------------------

def _bind_answer(spec: CanonicalSpec, snap: ImplementationSnapshot,
                 qid: str, value: Any) -> tuple[list[ExecutableStep], list[str]]:
    """Turn one canonical answer into physical field writes.

    Returns the writes and a list of anything that could not be bound. A
    non-empty second value means the whole test must be refused.
    """
    q = spec.question(qid)
    built = snap.questions.get(qid)
    missing: list[str] = []
    steps: list[ExecutableStep] = []

    if q is None or built is None:
        return [], [f"{qid}: question absent from the build"]

    # Blank answer: nothing to write. The test asserts what happens on submit.
    if value is None or value == [] or value == {} or value == "":
        base = snap.binding(qid)
        steps.append(ExecutableStep(
            step=0, action="set_field",
            field_name=(base.field_name if base else qid),
            sgqa=(base.sgqa if base else None),
            value="", value_kind="blank", canonical=qid,
            human=f"leave {qid} blank"))
        return steps, missing

    # Free text.
    if built.type in ("T", "S"):
        b = snap.binding(qid)
        if b is None:
            return [], [f"{qid}: free-text field has no binding"]
        steps.append(ExecutableStep(
            step=0, action="set_field", field_name=b.field_name, sgqa=b.sgqa,
            value=str(value), value_kind="text", canonical=qid,
            human=f"type {str(value)!r} into {qid}"))
        return steps, missing

    # Single choice: one field, value is the answer code.
    if built.type == "L":
        b = snap.binding(qid, str(value))
        if b is None or b.value is None:
            return [], [f"{qid}/{value}: no answer code bound"]
        opt = q.option_by_id(str(value))
        steps.append(ExecutableStep(
            step=0, action="set_field", field_name=b.field_name, sgqa=b.sgqa,
            value=b.value, value_kind="answer_code",
            canonical=f"{qid}/{value}",
            human=f"select {b.value} ({opt.label if opt else value}) on {qid}"))
        return steps, missing

    # Multi select: one field per ticked option, value "Y".
    if built.type == "M":
        chosen = value if isinstance(value, (list, tuple, set)) else [value]
        for oid in chosen:
            b = snap.binding(qid, str(oid))
            if b is None:
                missing.append(f"{qid}/{oid}: no subquestion field bound")
                continue
            opt = q.option_by_id(str(oid))
            steps.append(ExecutableStep(
                step=0, action="set_field", field_name=b.field_name,
                sgqa=b.sgqa, value=CHECKED, value_kind="checkbox",
                canonical=f"{qid}/{oid}",
                human=f"tick {b.field_name} ({opt.label if opt else oid})"))
        return steps, missing

    # Matrix: one field per row, value is the column's answer code.
    if built.type == "F":
        if not isinstance(value, dict):
            return [], [f"{qid}: matrix answer must be a row-to-column mapping"]
        for row_id, col_id in value.items():
            row_b = snap.binding(qid, str(row_id))
            col_b = snap.binding(qid, str(col_id))
            if row_b is None:
                missing.append(f"{qid}/{row_id}: no row subquestion bound")
                continue
            if col_b is None or col_b.value is None:
                missing.append(f"{qid}/{col_id}: no column answer code bound")
                continue
            steps.append(ExecutableStep(
                step=0, action="set_field", field_name=row_b.field_name,
                sgqa=row_b.sgqa, value=col_b.value, value_kind="answer_code",
                canonical=f"{qid}/{row_id}={col_id}",
                human=f"set {row_b.field_name} to {col_b.value}"))
        return steps, missing

    # Constant sum: one numeric field per item.
    if built.type == "K":
        if not isinstance(value, dict):
            return [], [f"{qid}: constant-sum answer must be an item-to-number map"]
        for item_id, number in value.items():
            b = snap.binding(qid, str(item_id))
            if b is None:
                missing.append(f"{qid}/{item_id}: no numeric subquestion bound")
                continue
            steps.append(ExecutableStep(
                step=0, action="set_field", field_name=b.field_name,
                sgqa=b.sgqa, value=str(number), value_kind="number",
                canonical=f"{qid}/{item_id}",
                human=f"enter {number} into {b.field_name}"))
        return steps, missing

    return [], [f"{qid}: unhandled built type {built.type!r}"]


# --------------------------------------------------------------------------
# Assertion rewriting
# --------------------------------------------------------------------------

def _translate_assertions(spec: CanonicalSpec, snap: ImplementationSnapshot,
                          logical: list[dict],
                          target: CoverageTarget) -> tuple[list[ExecutableAssertion],
                                                            list[str]]:
    """Bind each logical assertion to what the bot can physically observe.

    This translates rather than re-derives. The logical layer already decided
    what proves the claim; if this function invented its own assertions the two
    artifacts could disagree, and the reviewable version would stop matching
    the runnable one.
    """
    out: list[ExecutableAssertion] = []
    unobservable: list[str] = []

    def field_of(qid: str) -> tuple[str | None, str | None]:
        b = snap.binding(qid)
        if b is not None:
            return b.field_name, b.sgqa
        for key, binding in snap.bindings.items():
            if key.startswith(f"{qid}/"):
                return binding.field_name, binding.sgqa
        return None, None

    for a in logical:
        kind = a["kind"]
        qid = a.get("target")
        exp = a.get("expected")
        detail = a.get("detail", "")
        fn, sg = field_of(qid) if qid else (None, None)

        if kind in ("question_visible", "question_absent"):
            if fn is None:
                unobservable.append(f"{qid}: no field to look for on the page")
                continue
            out.append(ExecutableAssertion(
                kind="field_present", expected=(kind == "question_visible"),
                field_name=fn, sgqa=sg, canonical=qid, detail=detail))

        elif kind == "respondent_continues":
            out.append(ExecutableAssertion(
                kind="not_on_end_page", expected=True, canonical=qid,
                detail=detail))

        elif kind == "next_question_is":
            if exp is None:
                unobservable.append(
                    f"{target.subject}: cannot tell which question should come next")
                continue
            nfn, nsg = field_of(str(exp))
            out.append(ExecutableAssertion(
                kind="next_field_present", expected=(nfn or exp),
                field_name=nfn, sgqa=nsg, canonical=str(exp), detail=detail))

        elif kind == "answer_accepted":
            out.append(ExecutableAssertion(
                kind="page_advances", expected=True, field_name=fn, sgqa=sg,
                canonical=qid, detail=detail))

        elif kind == "answer_rejected":
            out.append(ExecutableAssertion(
                kind="page_does_not_advance", expected=True, field_name=fn,
                sgqa=sg, canonical=qid, detail=detail))
            out.append(ExecutableAssertion(
                kind="error_shown_on_question", expected=True, field_name=fn,
                sgqa=sg, canonical=qid,
                detail="LimeSurvey redisplays the page with the message against "
                       "the offending question"))

        elif kind == "survey_completed":
            out.append(ExecutableAssertion(
                kind="survey_completed", expected=True, canonical=qid,
                detail=detail))

        elif kind == "ending_reached":
            # LimeSurvey has no terminate action: a screenout is the main group
            # being suppressed plus a message on the end page.
            if snap.main_gid is not None:
                out.append(ExecutableAssertion(
                    kind="group_suppressed", expected=True,
                    field_name=f"gid:{snap.main_gid}", canonical=qid,
                    detail="LimeSurvey has no terminate action, so a screenout "
                           "is the main section being suppressed entirely"))
            message = snap.termination_messages.get(str(exp)) \
                or snap.termination_messages.get(str(qid))
            if message:
                ambiguous = []
                for ids in shared_messages(snap.termination_messages).values():
                    if str(exp) in ids:
                        ambiguous = [i for i in ids if i != str(exp)]
                out.append(ExecutableAssertion(
                    kind=("end_page_message" if not ambiguous
                          else "end_page_message_non_discriminating"),
                    expected=message, canonical=str(exp),
                    detail=(detail + (
                        f" NOTE: {', '.join(ambiguous)} show identical text, so "
                        f"this proves a screenout happened, not which one."
                        if ambiguous else ""))))
            else:
                unobservable.append(
                    f"{exp}: no message text for this ending appears on the "
                    f"built end page, so it cannot be distinguished")

        elif kind == "quota_recorded_over_target":
            out.append(ExecutableAssertion(
                kind="quota_counter_over_target", expected=exp, canonical=qid,
                detail=detail))

        elif kind == "cell_count_unchanged":
            out.append(ExecutableAssertion(
                kind="quota_counter_unchanged", expected=exp, canonical=qid,
                detail=detail))

        elif kind == "respondent_accepted":
            out.append(ExecutableAssertion(
                kind="not_sent_to_quota_full", expected=True, canonical=qid,
                detail=detail))

        elif kind == "options_shown_are":
            built = snap.questions.get(str(qid))
            if built is None:
                unobservable.append(f"{qid}: not in the built survey")
                continue
            if "array_filter" not in built.attributes:
                unobservable.append(
                    f"{qid}: the QRE narrows this option list but the built "
                    f"question has no carry-forward setting, so no narrowing "
                    f"will happen")
                continue
            codes = []
            q = spec.question(str(qid))
            for label in (exp or []):
                opt = q.option_by_label(label) if q else None
                b = snap.binding(str(qid), opt.option_id) if opt else None
                if b is not None:
                    codes.append(b.field_name if built.type == "M" else b.value)
            out.append(ExecutableAssertion(
                kind="options_rendered_equals", expected=codes, field_name=fn,
                sgqa=sg, canonical=qid, detail=detail))

        elif kind in ("wording_contains", "reflects_dependency"):
            if exp is None:
                unobservable.append(f"{qid}: nothing predicted to be carried forward")
                continue
            out.append(ExecutableAssertion(
                kind="question_text_contains",
                expected=(exp if isinstance(exp, str) else ", ".join(map(str, exp))),
                field_name=fn, sgqa=sg, canonical=qid, detail=detail))

        elif kind == "option_count_is":
            out.append(ExecutableAssertion(
                kind="rendered_option_count", expected=exp, field_name=fn,
                sgqa=sg, canonical=qid, detail=detail))

        elif kind == "option_set_is":
            out.append(ExecutableAssertion(
                kind="rendered_option_labels", expected=exp, field_name=fn,
                sgqa=sg, canonical=qid, detail=detail))

        elif kind == "display_order_differs_across_runs":
            built = snap.questions.get(str(qid))
            attrs = built.attributes if built else {}
            if not any(k.startswith("random") for k in attrs):
                out.append(ExecutableAssertion(
                    kind="rendered_order_varies", expected=True, field_name=fn,
                    sgqa=sg, canonical=qid,
                    detail=(detail + " EXPECTED TO FAIL on this build: the QRE "
                            "asks for shuffling but the built question carries "
                            "no randomisation setting, so the order will be "
                            "identical every run.")))
            else:
                out.append(ExecutableAssertion(
                    kind="rendered_order_varies", expected=True, field_name=fn,
                    sgqa=sg, canonical=qid, detail=detail))

        elif kind == "anchored_options_in_place":
            if not exp:
                unobservable.append(
                    f"{qid}: no anchor list supplied, so there is no position "
                    f"to assert")
                continue
            q = spec.question(str(qid))
            labels = []
            for oid in exp:
                o = q.option_by_id(str(oid)) if q else None
                labels.append(o.label if o else str(oid))
            out.append(ExecutableAssertion(
                kind="anchored_options_hold_position", expected=labels,
                field_name=fn, sgqa=sg, canonical=qid, detail=detail))

        else:
            unobservable.append(f"{qid}: no physical form for check '{kind}'")

    return out, unobservable


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _blocking_question(spec: CanonicalSpec, target: CoverageTarget, obs: dict):
    """Where the survey is expected to stop the respondent, if anywhere."""
    violations = obs.get("validation_messages_expected") or []
    if not violations:
        return None
    relevant = set(target.traces_to) | {target.subject}
    candidates = []
    for v in violations:
        qid = v.get("question_id")
        q = spec.question(qid) if qid else None
        if q is not None and q.id in relevant:
            candidates.append(q)
    return min(candidates, key=lambda q: q.seq) if candidates else None


def compile_all(spec: CanonicalSpec, snap: ImplementationSnapshot,
                targets: list[CoverageTarget],
                scenarios: list[VerifiedScenario],
                logical_tests: list | None = None) -> tuple[list[ExecutableTest],
                                                             dict]:
    by_id = {t.target_id: t for t in targets}
    logical_by = {getattr(t, "target_id", None) or t["target_id"]: t
                  for t in (logical_tests or [])}
    tests: list[ExecutableTest] = []
    refused: list[dict] = []

    for sc in scenarios:
        if sc.status != COVERED:
            continue
        target = by_id[sc.target_id]

        lt = logical_by.get(sc.target_id)
        if lt is None:
            continue

        # The logical test already decided which questions belong to this test
        # and in what order. Re-deriving that here would let the two drift.
        steps: list[ExecutableStep] = []
        missing: list[str] = []
        for st in lt.steps:
            qid = st.get("question_id")
            if not qid:
                continue
            produced, gaps = _bind_answer(spec, snap, qid, st.get("value"))
            steps.extend(produced)
            missing.extend(gaps)

        assertions, unobservable = _translate_assertions(
            spec, snap, lt.assertions, target)
        block_at = spec.question(lt.focus) if lt.blocks and lt.focus else None

        if missing:
            refused.append({
                "target_id": sc.target_id,
                "dimension": sc.dimension,
                "title": target.claim,
                "reason": "MISSING_BINDING",
                "missing": missing,
            })
            continue
        if not assertions:
            refused.append({
                "target_id": sc.target_id,
                "dimension": sc.dimension,
                "title": target.claim,
                "reason": "NOT_OBSERVABLE",
                "missing": unobservable or ["no observable assertion survives "
                                            "compilation"],
            })
            continue

        # Group the writes into pages. The build puts screening in one group and
        # everything else in another, and LimeSurvey submits a page at a time.
        ordered: list[ExecutableStep] = []
        current_gid = None
        n = 0
        for st in steps:
            gid = None
            if st.canonical:
                qid = st.canonical.split("/")[0]
                built = snap.questions.get(qid)
                gid = built.gid if built else None
            if current_gid is not None and gid != current_gid:
                n += 1
                ordered.append(ExecutableStep(
                    step=n, action="submit_page",
                    human=f"submit the {snap.groups.get(current_gid, '')} page"))
            current_gid = gid
            n += 1
            st.step = n
            ordered.append(st)
        n += 1
        if block_at is not None:
            ordered.append(ExecutableStep(
                step=n, action="submit_page",
                human=(f"submit — the survey should REFUSE to move on, because "
                       f"{block_at.id} is not acceptable as answered")))
        else:
            ordered.append(ExecutableStep(
                step=n, action="submit_page",
                human="submit the final page and observe the end screen"))

        tests.append(ExecutableTest(
            test_id=stable_id("EX", {"s": sc.scenario_id, "l": snap.lss_sha256}),
            target_id=sc.target_id,
            dimension=sc.dimension,
            title=target.claim,
            sid=snap.sid,
            steps=ordered,
            assertions=assertions,
            traces_to=target.traces_to,
            executable=True,
            provisional_semantics=sc.provisional_semantics,
        ))
        tests[-1].campaign = sc.campaign

    covered = sum(1 for sc in scenarios if sc.status == COVERED)
    report = {
        "logically_covered": covered,
        "compiled_executable": len(tests),
        "refused": len(refused),
        "executable_coverage_pct": (round(100.0 * len(tests) / len(scenarios), 1)
                                    if scenarios else 0.0),
        "refusals": refused,
        "note": ("Block C refuses rather than guessing a missing identifier. A "
                 "refusal is a specific named gap, not a silent omission."),
    }
    return tests, report
