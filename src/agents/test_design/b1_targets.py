"""B1 - Coverage Target Model. "What needs testing?"

Enumerates every behaviour the survey defines that can be proven true or false,
across nine independent dimensions. Deterministic throughout: counting and
structural analysis of already-structured data, no model call anywhere.

Three design points carried from the architecture:

  * Dimensions are never summed. They count different kinds of unit, so a total
    is meaningless and would rise whenever a behaviour happened to be described
    in two places. If one figure is demanded, the answer is the lowest
    dimension score, labelled as a floor.

  * B1 runs in spec-only mode. The architecture lists Block A's output as a B1
    input, but Block A needs Agent 2's build manifest, which does not exist
    yet. Block A's contribution is executability filtering and
    NOT_IN_IMPLEMENTATION marking, which is a separate later pass. Splitting
    that seam is what lets logical coverage be computed today.

  * Where B1 already knows a target cannot be attempted, it records the
    specific reason at enumeration time rather than letting B2 rediscover it.
"""

from __future__ import annotations

from .models import (
    CoverageTarget,
    QUOTA_SIZE_UNDEFINED,
    RANDOMIZATION_ANCHOR_UNDEFINED,
    stable_id,
)
from .spec import CanonicalSpec


def _t(dimension, subject, polarity, claim, traces_to=None,
       reason=None, notes=None) -> CoverageTarget:
    return CoverageTarget(
        target_id=stable_id("T", {"d": dimension, "s": subject, "p": polarity}),
        dimension=dimension,
        subject=subject,
        polarity=polarity,
        claim=claim,
        traces_to=traces_to or [],
        predetermined_reason=reason,
        notes=notes,
    )


# D1 - Visibility -----------------------------------------------------------

def d1_visibility(spec: CanonicalSpec) -> list[CoverageTarget]:
    out = []

    # Basic forward progression, for every question. Answering a question
    # normally must move the respondent on to whatever should come next.
    #
    # This was missing until a reviewer asked for it, and the omission was
    # real: nothing proved that answering S1 correctly takes you to S2. A
    # question can be built with the wrong show-condition, placed in the wrong
    # group, or ordered wrongly, and every one of those breaks the flow while
    # leaving each individual question looking fine.
    for q in spec.in_order():
        out.append(_t("D1", q.id, "advances",
                      f"answering {q.id} normally moves the respondent on to "
                      f"the question that should come next",
                      [q.id]))

    for q in spec.in_order():
        if q.guard is None:
            continue
        rules = [r.id for r in spec.rules
                 if r.kind == "show" and r.destination_id == q.id]
        trace = [q.id] + rules
        note = None
        if q.guard.origin == "inferred":
            note = f"guard origin=inferred, reading is provisional: {q.guard.render()}"
        out.append(_t("D1", q.id, "shown",
                      f"{q.id} is displayed when its guard holds", trace, None, note))
        out.append(_t("D1", q.id, "hidden",
                      f"{q.id} is not displayed when its guard fails", trace, None, note))

    # Skip rules are a route jump, not a guard. The nine-dimension model as
    # frozen has no dimension for a non-terminal jump: D1 covers visibility and
    # D2 covers endings, so a rule that skips forward past questions falls
    # between them. Found on C01 as R5 (Q1 == ['None of these'] -> skip Q4),
    # which was enumerated by nothing. Covered here as a D1 behaviour, because
    # what a jump changes is which questions the respondent sees.
    for r in spec.rules:
        if r.kind != "skip":
            continue
        subject = f"{r.id}:{r.evaluation_point or '?'}->{r.destination_id}"
        out.append(_t("D1", subject, "skip_fired",
                      f"{r.id} jumps to {r.destination_id} when its condition holds",
                      [r.id], None,
                      f"skip rule, bypasses questions between "
                      f"{r.evaluation_point} and {r.destination_id}"))
        out.append(_t("D1", subject, "skip_not_fired",
                      f"{r.id} does not jump when its condition fails, so the "
                      f"respondent continues in sequence", [r.id]))
    return out


# D2 - Terminal outcome ------------------------------------------------------

def d2_endings(spec: CanonicalSpec) -> list[CoverageTarget]:
    """One target per ROUTE to an ending, not one per ending.

    Several rules often lead to the same ending. On a typical screener, a No at
    S1 and a No at S2 both end in the same ineligible message. Emitting one
    target per ending would test only the first route and leave the others
    unproven, and a programmer can easily wire one correctly and the other not.

    So each rule that leads to an ending gets its own target, its own test and
    its own id. If one route breaks, the failing test names the rule and the
    question it fires at.
    """
    out = []
    for d in spec.dispositions:
        rules = [r for r in spec.rules if r.destination_id == d.id]
        quota_sources = [q.id for q in spec.quotas if q.on_full == d.id]

        for rule in sorted(rules, key=lambda r: (r.precedence, r.id)):
            where = rule.evaluation_point or "?"
            out.append(_t("D2", f"{d.id}<-{rule.id}", "reachable",
                          f"ending {d.id} is reached by rule {rule.id}, "
                          f"evaluated at {where}",
                          [rule.id, d.id], None,
                          f"one of {len(rules)} route(s) to {d.id}"
                          if len(rules) > 1 else None))

        if rules:
            continue

        reason, notes = None, None
        rules = [r.id for r in rules]
        if d.kind == "quota_full" or (quota_sources and not rules):
            sized = any(c.target_count is not None
                        for q in spec.quotas if q.on_full == d.id
                        for c in q.cells)
            reason = None if sized else QUOTA_SIZE_UNDEFINED
            notes = ("reached by filling a quota cell first: a run-up of "
                     "earlier respondents is required" if sized else
                     "reached only by filling a quota cell: needs sequential "
                     "respondents and a sample size the QRE never states")
        if not d.defined_in_source:
            notes = ((notes + "; ") if notes else "") + \
                "reachable but the QRE never states what it shows the respondent"
        out.append(_t("D2", d.id, "reachable",
                      f"a respondent can reach ending {d.id}",
                      rules + quota_sources, reason, notes))
    return out


# D3 - Validation (explicit) -------------------------------------------------

def d3_validation_explicit(spec: CanonicalSpec) -> list[CoverageTarget]:
    out = []
    for q in spec.in_order():
        cons = q.validation.constraints
        if not cons:
            continue
        arithmetic = "sum_to" in cons
        notes = ("constant-sum arithmetic: witness search escalates to the solver"
                 if arithmetic else None)
        out.append(_t("D3", q.id, "satisfied",
                      f"{q.id} accepts an answer meeting {cons}", [q.id], None, notes))
        out.append(_t("D3", q.id, "violated",
                      f"{q.id} rejects an answer breaking {cons}", [q.id], None, notes))

    for r in spec.rules:
        if r.kind != "reject":
            continue
        out.append(_t("D3", r.id, "satisfied",
                      f"reject rule {r.id} does not fire when its condition fails", [r.id]))
        out.append(_t("D3", r.id, "violated",
                      f"reject rule {r.id} fires when its condition holds", [r.id]))
    return out


# D4 - Validation (mandatory) ------------------------------------------------

def d3_input_robustness(spec: CanonicalSpec) -> list[CoverageTarget]:
    """Input the questionnaire does not describe, but a respondent can still type.

    The rules a QRE states are tested well. The gap is everything it does not
    state and a respondent can do anyway: a run of spaces, an apostrophe, a
    string sitting exactly on the maximum length. Survey tools break on these
    far more often than on the stated rules, because nobody wrote them down and
    so nobody tested them.

    Every claim here is still derived from what the QRE says, not invented:

      a length rule constrains length and says nothing about content, so a
      string of punctuation within the limit must be accepted;

      a maximum is a limit, so exactly the maximum must be accepted while one
      character more must not.
    """
    out = []
    for q in spec.in_order():
        v = q.validation

        # Exactly at the maximum. One over is already tested; the boundary
        # itself was not, and an off-by-one in the build sits precisely here.
        if v.get("max_length") is not None:
            out.append(_t("D3", q.id, "boundary_max_accepted",
                          f"{q.id} accepts an answer of exactly "
                          f"{v.get('max_length')} characters, its stated maximum",
                          [q.id], None, "boundary case of the stated rule"))
        if v.get("max_selections") is not None:
            out.append(_t("D3", q.id, "boundary_max_accepted",
                          f"{q.id} accepts exactly {v.get('max_selections')} "
                          f"selections, its stated maximum",
                          [q.id], None, "boundary case of the stated rule"))

        # Content the rule never restricted.
        if q.kind in ("text", "open_text") and (
                v.get("max_length") is not None or v.get("min_length") is not None):
            out.append(_t("D3", q.id, "special_characters_accepted",
                          f"{q.id} accepts punctuation and quotation marks, "
                          f"because its rule constrains length and not content",
                          [q.id], None,
                          "quotes and angle brackets are where survey tools "
                          "most often break"))
    return out


def d4_mandatory(spec: CanonicalSpec) -> list[CoverageTarget]:
    """One target per question, not per question type.

    An earlier version emitted one target per question TYPE, on the reasoning
    that whether the survey tool enforces a blank answer is a property of the
    type rather than of the question. That reasoning was wrong in a way that
    mattered.

    Two things can go wrong with a compulsory question. The survey tool might
    not enforce the flag, which IS a per-type behaviour. Or the programmer
    might simply have failed to set the flag on one particular question, which
    is per-question. A single shared test cannot distinguish them: if it fails
    you do not know which question is at fault, and if it passes you have
    proved nothing about the other thirty.

    So every compulsory question now gets its own test with its own id.
    """
    out = []
    # Whitespace is not an answer. A question the QRE marks compulsory must
    # refuse a run of spaces, and an optional one must accept it. Neither was
    # tested, and blank-versus-whitespace is the commoner real-world failure,
    # because a respondent pressing the space bar looks like a respondent who
    # answered.
    for q in spec.in_order():
        if q.kind not in ("text", "open_text"):
            continue
        out.append(_t("D4", q.id,
                      "whitespace_rejected" if q.mandatory else "whitespace_accepted",
                      f"{q.id} "
                      + ("refuses an answer of spaces alone, being compulsory"
                         if q.mandatory else
                         "accepts an answer of spaces alone, being optional"),
                      [q.id], None, f"question kind: {q.kind}"))

    for q in spec.in_order():
        if q.mandatory:
            out.append(_t("D4", q.id, "enforced",
                          f"{q.id} blocks progress when left blank",
                          [q.id], None, f"question kind: {q.kind}"))
        else:
            out.append(_t("D4", q.id, "not_enforced",
                          f"{q.id} is optional and permits progress when left "
                          f"blank", [q.id], None, f"question kind: {q.kind}"))
    return out


# D5 / D6 - dependency dimensions -------------------------------------------

def d5_option_source(spec: CanonicalSpec) -> list[CoverageTarget]:
    out = []
    for dep in spec.dependencies:
        if dep.kind != "option_source":
            continue
        subject = f"{dep.from_question}->{dep.to_question}"
        out.append(_t("D5", subject, "restricted",
                      f"{dep.to_question}'s option list is narrowed to what was "
                      f"chosen at {dep.from_question}",
                      [dep.from_question, dep.to_question], None,
                      "origin=inferred, reading is provisional"
                      if dep.origin == "inferred" else None))
    return out


def d6_text_pipe(spec: CanonicalSpec) -> list[CoverageTarget]:
    out = []
    for dep in spec.dependencies:
        if dep.kind != "text_pipe":
            continue
        subject = f"{dep.from_question}->{dep.to_question}"
        out.append(_t("D6", subject, "rendered",
                      f"{dep.to_question}'s wording renders the answer given at "
                      f"{dep.from_question}",
                      [dep.from_question, dep.to_question], None,
                      "origin=inferred, no table in the QRE states this link"
                      if dep.origin == "inferred" else None))
    return out


# D7 - Randomization configuration ------------------------------------------

def d7_randomization(spec: CanonicalSpec) -> list[CoverageTarget]:
    """Three separate claims per shuffled question, not one.

    The earlier model collapsed shuffling into a single target and blocked the
    whole thing on the missing anchor list. That was too blunt: only one of the
    three claims actually needs the anchors.

      completeness  every option appears exactly once. Testable in one run and
                    needs nothing from the QRE beyond the option list.
      order_varies  the order genuinely differs between respondents. This is
                    what proves shuffling is switched on at all, and it needs
                    several runs rather than one.
      anchors_held  the pinned options stay in place. This is the only claim
                    that needs the QRE to say which options are anchored.
    """
    out = []
    for r in spec.randomization:
        q = spec.question(r.question_id)
        n = len(q.options) if q else 0

        out.append(_t("D7", r.question_id, "completeness",
                      f"{r.question_id} presents all {n} items exactly once, with "
                      f"none missing and none repeated",
                      [r.question_id], None,
                      "single run; needs no information the QRE has not given"))

        out.append(_t("D7", r.question_id, "order_varies",
                      f"{r.question_id} presents its items in a different order to "
                      f"different respondents, proving shuffling is switched on",
                      [r.question_id], None,
                      "needs several runs of the same path and a comparison of "
                      "the observed order between them"))

        if r.anchored_origin == "project_input_none":
            # Confirmed as having no pinned options, so the claim does not
            # exist. Emitting it as an uncovered target would report a gap
            # where the project has already given a definite answer.
            continue
        if r.anchors_stated and r.anchored:
            out.append(_t("D7", r.question_id, "anchors_held",
                          f"{r.question_id} keeps {r.anchored} in place while the "
                          f"rest shuffle", [r.question_id]))
        else:
            out.append(_t("D7", r.question_id, "anchors_held",
                          f"{r.question_id} keeps its anchored items in place",
                          [r.question_id], RANDOMIZATION_ANCHOR_UNDEFINED,
                          f"anchored_origin={r.anchored_origin}: the QRE does not "
                          "say which items are anchored, so there is no position "
                          "to assert. Everything else about the shuffle is "
                          "covered by the other two claims"))
    return out


# D8 - Quota cell state ------------------------------------------------------

def d8_quota(spec: CanonicalSpec) -> list[CoverageTarget]:
    """Quota behaviour, and it is not the same behaviour for every quota.

    A hard quota turns a respondent away once its cell is at target. A soft
    quota does not: it records that the cell is over and lets the respondent
    through, so the field team can see the imbalance and decide.

    The specification carries that distinction in `enforcement` and an earlier
    version never read it, so a soft quota was tested as though it terminated
    the survey. That is a wrong test rather than a missing one, and a wrong
    test is worse: it fails against a correct build and sends someone looking
    for a defect that is not there.
    """
    out = []
    for quota in spec.quotas:
        hard = (quota.enforcement or "hard").lower() != "soft"
        for cell in quota.cells:
            subject = f"{quota.id}:{cell.option_id}"
            sized = cell.target_count is not None

            out.append(_t("D8", subject, "available",
                          f"{subject} ({cell.option_label}) admits a respondent "
                          f"while below target", [quota.id], None,
                          f"{quota.enforcement} quota"))

            if hard:
                out.append(_t("D8", subject, "full",
                              f"{subject} ({cell.option_label}) turns a "
                              f"respondent away once at target", [quota.id],
                              None if sized else QUOTA_SIZE_UNDEFINED,
                              (f"hard quota: needs {cell.target_count} "
                               f"respondents in this cell first, then one more"
                               if sized else
                               f"target is {cell.target_percent}% with no stated "
                               "sample size, so a fill campaign cannot be sized")))
            else:
                out.append(_t("D8", subject, "over_target_admits",
                              f"{subject} ({cell.option_label}) still admits a "
                              f"respondent once over target, being a soft quota",
                              [quota.id],
                              None if sized else QUOTA_SIZE_UNDEFINED,
                              (f"soft quota: needs {cell.target_count} "
                               f"respondents in this cell first, then one more "
                               f"who must still be let through"
                               if sized else
                               f"target is {cell.target_percent}% with no stated "
                               "sample size, so a fill campaign cannot be sized")))

            # A respondent outside this cell must not count against it. Nothing
            # proved that before, and getting it wrong silently mis-fills every
            # cell in the quota.
            others = [c for c in quota.cells if c.option_id != cell.option_id]
            if others and sized:
                out.append(_t("D8", subject, "not_counted_by_other_cell",
                              f"{subject} ({cell.option_label}) is not "
                              f"incremented by a respondent who answers "
                              f"{others[0].option_label!r}", [quota.id], None,
                              "fill a different cell, then confirm this one is "
                              "unchanged"))
    return out


# D9 - Interaction -----------------------------------------------------------

def d9_interaction(spec: CanonicalSpec, cap: int = 8) -> list[CoverageTarget]:
    """Selected combinations. Always BOUNDED, never claimed exhaustive.

    Risk rule for v0.1, stated plainly so it can be ratified or replaced: pair
    a guarded question with a dependency feeding it. A question that is both
    conditionally shown and dependent on an earlier answer is where the two
    mechanisms can disagree, and neither dimension alone would catch it.
    """
    guarded = {q.id for q in spec.questions if q.guard is not None}
    pairs = sorted({(d.from_question, d.to_question) for d in spec.dependencies
                    if d.to_question in guarded
                    and d.kind in ("option_source", "text_pipe")})
    out = []
    for source, target in pairs[:cap]:
        out.append(_t("D9", f"{source}+{target}", "combined",
                      f"{target} is shown by its guard and simultaneously reflects "
                      f"its dependency on {source}",
                      [source, target], None,
                      "risk-selected pair, BOUNDED by design"))
    return out


ENUMERATORS = [
    ("D1", d1_visibility),
    ("D2", d2_endings),
    ("D3", d3_validation_explicit),
    ("D3", d3_input_robustness),
    ("D4", d4_mandatory),
    ("D5", d5_option_source),
    ("D6", d6_text_pipe),
    ("D7", d7_randomization),
    ("D8", d8_quota),
    ("D9", d9_interaction),
]


def enumerate_targets(spec: CanonicalSpec) -> tuple[list[CoverageTarget], dict]:
    targets: list[CoverageTarget] = []
    per_dimension: dict[str, int] = {}
    for code, fn in ENUMERATORS:
        produced = fn(spec)
        # Accumulate rather than assign. A dimension may have more than one
        # enumerator, and overwriting here would under-report its size while
        # the targets themselves were all present, which is the worst kind of
        # wrong number: quietly too small.
        per_dimension[code] = per_dimension.get(code, 0) + len(produced)
        targets.extend(produced)

    # Ids are content-derived, so a duplicate id is a duplicate claim. B1 is
    # required to prove no target is silently duplicated, omitted or invented.
    ids = [t.target_id for t in targets]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        offenders = [(t.dimension, t.subject, t.polarity)
                     for t in targets if t.target_id in dupes]
        raise AssertionError(f"B1 produced duplicate targets: {offenders}")

    # Every rule in the spec must be referenced by at least one target, or a
    # specified behaviour is going untested without anyone noticing.
    referenced = {r for t in targets for r in t.traces_to}
    orphan_rules = sorted(r.id for r in spec.rules if r.id not in referenced)

    report = {
        "per_dimension": per_dimension,
        "records_enumerated": len(targets),
        "predetermined_unresolvable": sum(
            1 for t in targets if t.predetermined_reason),
        "orphan_rules": orphan_rules,
        "note": ("Dimensions are reported side by side and never summed. "
                 "records_enumerated counts records, not coverage."),
    }
    return targets, report
