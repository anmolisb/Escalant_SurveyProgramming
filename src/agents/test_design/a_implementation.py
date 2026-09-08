"""Block A - Implementation Intake & Conformance.

"What was actually built, and does it match the specification?"

Reads the LimeSurvey `.lss` the Survey Builder emitted and derives an
implementation snapshot: for every canonical question and option, the physical
field address and value Agent 4 must actually use.

The architecture says Block A never trusts Agent 2's self-report. There is no
build manifest to trust here, so the snapshot is derived from the emitted
`.lss` itself, which is the artifact LimeSurvey will actually import. That is
stronger evidence than a manifest would be: a manifest states intent, the
`.lss` states what was built.

FIELD ADDRESSING, read off a real export rather than assumed
------------------------------------------------------------
LimeSurvey addresses an answer differently depending on question type, which
is why one canonical id cannot simply become one physical id:

  L (single)        field = Q5              value = answer code, e.g. "A001"
  T/S (free text)   field = Q14             value = the typed string
  M (multi)         field = Q1_SQ001        value = "Y" when ticked
  F (array/matrix)  field = Q9_SQ001        value = answer code for the column
  K (constant sum)  field = Q18_SQ001       value = the number

So a single-choice option needs one identifier, a multi-select option needs a
different KIND of identifier, and a matrix cell needs two: a row subquestion
and a column answer code. The full SGQA form is also recorded
(`{sid}X{gid}X{qid}`) because some Agent 4 drivers address fields that way.

THE TERMINATION MAPPING - the most important finding in this module
-------------------------------------------------------------------
LimeSurvey has no terminate action. The builder therefore inverts every
terminate rule into the main group's relevance, and nests the disposition
messages into a single end screen using `if()`.

The consequence for test design is large: a screened-out respondent never
reaches a page called TERM_AGE. They answer the screening group, the main
group is suppressed, and they land on the end screen showing the TERM_AGE
message text. Any assertion of the form `ending_reached == TERM_AGE` is
unobservable as written and must be rewritten as "main group not shown" plus
"end screen contains this text".
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .spec import CanonicalSpec


# Question types whose options live in the subquestions table rather than the
# answers table. Getting this wrong imports cleanly and leaves the question
# with no options at all.
SUBQUESTION_OPTION_TYPES = {"M", "K"}
ARRAY_TYPES = {"F"}
FREE_TEXT_TYPES = {"T", "S"}
SINGLE_TYPES = {"L"}

# What a ticked checkbox stores.
CHECKED = "Y"

# The builder's neutral-to-LimeSurvey type map, restated so conformance can
# check the built type against what the canonical spec asked for.
EXPECTED_TYPE = {
    "single": "L",
    "multi": "M",
    "text": "T",
    "matrix": "F",
    "constant_sum": "K",
}


@dataclass
class FieldBinding:
    """One addressable answer field in the built survey."""

    canonical_question: str
    canonical_option: str | None      # None for the question as a whole
    field_name: str                   # what ExpressionScript and the DOM use
    sgqa: str                         # {sid}X{gid}X{qid}, plus SQ code if any
    value: str | None                 # the value to submit, None for free text
    value_kind: str                   # answer_code | checkbox | number | text
    question_type: str                # LimeSurvey type letter
    qid: int = 0
    gid: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BuiltQuestion:
    canonical_id: str
    qid: int
    gid: int
    group_name: str
    type: str
    title: str
    mandatory: bool
    relevance: str
    order: int
    option_codes: dict[str, str] = field(default_factory=dict)   # label -> code
    subquestion_codes: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImplementationSnapshot:
    survey_id: str
    lss_path: str
    lss_sha256: str
    sid: int
    groups: dict[int, str]
    group_relevance: dict[int, str]
    questions: dict[str, BuiltQuestion]
    bindings: dict[str, FieldBinding]        # key: "Q5" or "Q5/Q5-O1"
    end_text: str
    termination_messages: dict[str, str]     # disposition id -> message text
    screening_gid: int | None
    main_gid: int | None

    def binding(self, question: str, option: str | None = None) -> FieldBinding | None:
        return self.bindings.get(f"{question}/{option}" if option else question)

    def to_dict(self) -> dict:
        return {
            "survey_id": self.survey_id,
            "lss_path": self.lss_path,
            "lss_sha256": self.lss_sha256,
            "sid": self.sid,
            "groups": {str(k): v for k, v in self.groups.items()},
            "group_relevance": {str(k): v for k, v in self.group_relevance.items()},
            "screening_gid": self.screening_gid,
            "main_gid": self.main_gid,
            "questions": {k: v.to_dict() for k, v in self.questions.items()},
            "bindings": {k: v.to_dict() for k, v in self.bindings.items()},
            "termination_messages": self.termination_messages,
            "end_text": self.end_text,
        }


def _rows(root, table: str) -> list[dict]:
    node = root.find(table)
    if node is None:
        return []
    rows = node.find("rows")
    if rows is None:
        return []
    return [{c.tag: (c.text or "") for c in row} for row in rows.findall("row")]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def parse_lss(lss_path: str | Path, spec: CanonicalSpec) -> ImplementationSnapshot:
    lss_path = Path(lss_path)
    raw = lss_path.read_bytes()
    root = ET.fromstring(raw.decode("utf-8"))

    sid = int(_rows(root, "surveys")[0]["sid"])

    groups: dict[int, str] = {}
    group_relevance: dict[int, str] = {}
    for g in _rows(root, "groups"):
        groups[int(g["gid"])] = ""
        group_relevance[int(g["gid"])] = g.get("grelevance", "1")
    for g in _rows(root, "group_l10ns"):
        gid = int(g["gid"])
        if gid in groups:
            groups[gid] = g.get("group_name", "")

    # Answer codes, keyed by parent qid then label.
    answers_by_qid: dict[int, list[dict]] = {}
    for a in _rows(root, "answers"):
        answers_by_qid.setdefault(int(a["qid"]), []).append(a)
    labels_by_aid = {int(l["aid"]): _strip_html(l.get("answer", ""))
                     for l in _rows(root, "answer_l10ns")}

    # Subquestion codes, keyed by parent qid.
    subs_by_parent: dict[int, list[dict]] = {}
    for s in _rows(root, "subquestions"):
        subs_by_parent.setdefault(int(s["parent_qid"]), []).append(s)
    q_labels = {int(l["qid"]): _strip_html(l.get("question", ""))
                for l in _rows(root, "question_l10ns")}

    attrs_by_qid: dict[int, dict[str, str]] = {}
    for a in _rows(root, "question_attributes"):
        attrs_by_qid.setdefault(int(a["qid"]), {})[a["attribute"]] = a.get("value", "")

    questions: dict[str, BuiltQuestion] = {}
    bindings: dict[str, FieldBinding] = {}

    for q in _rows(root, "questions"):
        if int(q.get("parent_qid", 0) or 0) != 0:
            continue
        qid, gid = int(q["qid"]), int(q["gid"])
        title, qtype = q["title"], q["type"]

        built = BuiltQuestion(
            canonical_id=title,
            qid=qid,
            gid=gid,
            group_name=groups.get(gid, ""),
            type=qtype,
            title=title,
            mandatory=(q.get("mandatory", "Y") == "Y"),
            relevance=q.get("relevance", "1"),
            order=int(q.get("question_order", 0) or 0),
            attributes=attrs_by_qid.get(qid, {}),
        )

        for a in sorted(answers_by_qid.get(qid, []),
                        key=lambda r: int(r.get("sortorder", 0) or 0)):
            built.option_codes[labels_by_aid.get(int(a["aid"]), "")] = a["code"]
        for s in sorted(subs_by_parent.get(qid, []),
                        key=lambda r: int(r.get("question_order", 0) or 0)):
            built.subquestion_codes[q_labels.get(int(s["qid"]), "")] = s["title"]

        questions[title] = built

        # ---- bind the question itself -----------------------------------
        base_sgqa = f"{sid}X{gid}X{qid}"
        cq = spec.question(title)

        if qtype in FREE_TEXT_TYPES:
            bindings[title] = FieldBinding(
                canonical_question=title, canonical_option=None,
                field_name=title, sgqa=base_sgqa, value=None,
                value_kind="text", question_type=qtype, qid=qid, gid=gid)
        elif qtype in SINGLE_TYPES:
            bindings[title] = FieldBinding(
                canonical_question=title, canonical_option=None,
                field_name=title, sgqa=base_sgqa, value=None,
                value_kind="answer_code", question_type=qtype, qid=qid, gid=gid)

        if cq is None:
            continue

        # ---- bind each canonical option ---------------------------------
        for opt in cq.options:
            label = opt.label.strip()
            if qtype in SINGLE_TYPES:
                code = built.option_codes.get(label)
                if code is None:
                    continue
                bindings[f"{title}/{opt.option_id}"] = FieldBinding(
                    canonical_question=title, canonical_option=opt.option_id,
                    field_name=title, sgqa=base_sgqa, value=code,
                    value_kind="answer_code", question_type=qtype,
                    qid=qid, gid=gid)
            elif qtype in SUBQUESTION_OPTION_TYPES:
                sq = built.subquestion_codes.get(label)
                if sq is None:
                    continue
                kind = "number" if qtype == "K" else "checkbox"
                bindings[f"{title}/{opt.option_id}"] = FieldBinding(
                    canonical_question=title, canonical_option=opt.option_id,
                    field_name=f"{title}_{sq}", sgqa=f"{base_sgqa}{sq}",
                    value=(CHECKED if qtype == "M" else None),
                    value_kind=kind, question_type=qtype, qid=qid, gid=gid)
            elif qtype in ARRAY_TYPES:
                # An array's canonical options are the SCALE (columns), stored
                # in the answers table. The rows are the subquestions.
                code = built.option_codes.get(label)
                if code is not None:
                    bindings[f"{title}/{opt.option_id}"] = FieldBinding(
                        canonical_question=title, canonical_option=opt.option_id,
                        field_name=f"{title}_<row>", sgqa=f"{base_sgqa}<row>",
                        value=code, value_kind="answer_code",
                        question_type=qtype, qid=qid, gid=gid)

        # ---- bind matrix / constant-sum rows ----------------------------
        for row_id in cq.matrix_rows:
            row_label = None
            for o in cq.options:
                if o.option_id == row_id:
                    row_label = o.label
            # Matrix rows in the canonical spec carry ids like Q9-R1; the
            # builder labels the subquestion with the row's text.
            row_label = row_label or row_id
            sq = built.subquestion_codes.get(row_label.strip())
            if sq is None:
                # Fall back to positional match: the builder emits rows in
                # canonical order, so position is a safe secondary key.
                ordered = list(built.subquestion_codes.values())
                idx = cq.matrix_rows.index(row_id)
                sq = ordered[idx] if idx < len(ordered) else None
            if sq is None:
                continue
            bindings[f"{title}/{row_id}"] = FieldBinding(
                canonical_question=title, canonical_option=row_id,
                field_name=f"{title}_{sq}", sgqa=f"{base_sgqa}{sq}",
                value=None,
                value_kind=("number" if qtype == "K" else "answer_code"),
                question_type=qtype, qid=qid, gid=gid)

    end_text = ""
    for row in _rows(root, "surveys_languagesettings"):
        end_text = row.get("surveyls_endtext", "") or ""

    screening_gid = next((g for g, n in groups.items()
                          if n.lower().startswith("screen")), None)
    main_gid = next((g for g, n in groups.items()
                     if not n.lower().startswith("screen")), None)

    return ImplementationSnapshot(
        survey_id=spec.survey_id,
        lss_path=str(lss_path),
        lss_sha256=hashlib.sha256(raw).hexdigest(),
        sid=sid,
        groups=groups,
        group_relevance=group_relevance,
        questions=questions,
        bindings=bindings,
        end_text=end_text,
        termination_messages=_termination_messages(end_text, spec),
        screening_gid=screening_gid,
        main_gid=main_gid,
    )


def _termination_messages(end_text: str, spec: CanonicalSpec) -> dict[str, str]:
    """Recover which disposition message each screenout produces.

    The builder collapses every disposition into one nested `if()` on the end
    screen, so the disposition id does not exist in the built survey at all.
    Matching the canonical message text back to its disposition is the only
    route to asserting what a screened-out respondent should see.
    """
    out: dict[str, str] = {}
    plain = _strip_html(end_text)
    for d in spec.dispositions:
        msg = (d.message or "").strip()
        if msg and msg in plain:
            out[d.id] = msg
    return out


def shared_messages(messages: dict[str, str]) -> dict[str, list[str]]:
    """Disposition ids grouped by identical message text.

    Any group with more than one member is indistinguishable on screen: the
    respondent sees the same words whichever rule fired, so an end-text
    assertion proves only that SOME screenout happened, not which. That is a
    genuine limit on what Agent 4 can verify and it must not be presented as
    full coverage of the individual disposition.
    """
    grouped: dict[str, list[str]] = {}
    for did, msg in messages.items():
        grouped.setdefault(msg, []).append(did)
    return {msg: sorted(ids) for msg, ids in grouped.items() if len(ids) > 1}


# --------------------------------------------------------------------------
# Conformance: does the build match the specification?
# --------------------------------------------------------------------------

def conformance(spec: CanonicalSpec, snap: ImplementationSnapshot) -> dict:
    """Every place the implementation disagrees with the specification.

    Findings are classified, not merely listed, because the three classes need
    different owners: a MISSING question is an Agent 2 defect, an UNSUPPORTED
    construct is a platform limit to accept or work around, and a
    SPEC_NOT_BUILT item is a decision someone made to omit.
    """
    findings: list[dict] = []

    spec_ids = {q.id for q in spec.questions}
    built_ids = set(snap.questions)

    for qid in sorted(spec_ids - built_ids):
        findings.append({"kind": "QUESTION_NOT_BUILT", "severity": "BLOCKING",
                         "subject": qid,
                         "detail": "specified but absent from the built survey"})
    for qid in sorted(built_ids - spec_ids):
        findings.append({"kind": "QUESTION_NOT_SPECIFIED", "severity": "HIGH",
                         "subject": qid,
                         "detail": "built but not present in the canonical spec"})

    for q in spec.in_order():
        built = snap.questions.get(q.id)
        if built is None:
            continue

        want = EXPECTED_TYPE.get(q.kind)
        if want and built.type != want:
            findings.append({"kind": "TYPE_MISMATCH", "severity": "BLOCKING",
                             "subject": q.id,
                             "detail": f"spec says {q.kind} (expect {want}), "
                                       f"built as {built.type}"})

        if q.mandatory != built.mandatory:
            findings.append({"kind": "MANDATORY_MISMATCH", "severity": "HIGH",
                             "subject": q.id,
                             "detail": f"spec mandatory={q.mandatory}, "
                                       f"built mandatory={built.mandatory}"})

        # Every canonical option must have a physical binding, or no test can
        # ever select it.
        for opt in q.options:
            if snap.binding(q.id, opt.option_id) is None:
                findings.append({"kind": "OPTION_NOT_BOUND", "severity": "BLOCKING",
                                 "subject": f"{q.id}/{opt.option_id}",
                                 "detail": f"option {opt.label!r} has no physical "
                                           f"identifier in the build"})

        if q.guard is not None and built.relevance in ("1", ""):
            findings.append({"kind": "GUARD_NOT_BUILT", "severity": "BLOCKING",
                             "subject": q.id,
                             "detail": f"spec guards this question "
                                       f"({q.guard.render()}) but the built "
                                       f"relevance is always-true"})

    # Rule classes the builder documents as deliberately not emitted.
    for r in spec.rules:
        if r.kind == "reject":
            findings.append({"kind": "REJECT_RULE_NOT_BUILT", "severity": "HIGH",
                             "subject": r.id,
                             "detail": "the builder skips reject rules as "
                                       "restatements of question-level "
                                       "constraints; no separate behaviour exists "
                                       "to test"})
        if r.kind == "skip":
            findings.append({"kind": "SKIP_RULE_NOT_BUILT", "severity": "NORMAL",
                             "subject": r.id,
                             "detail": "the builder treats a skip as the "
                                       "complement of a show rule and emits "
                                       "nothing; the behaviour is carried by the "
                                       "target question's relevance"})

    if spec.quotas:
        findings.append({"kind": "QUOTAS_NOT_BUILT", "severity": "HIGH",
                         "subject": ", ".join(q.id for q in spec.quotas),
                         "detail": "the builder emits no quota tables, so no "
                                   "quota behaviour exists in the built survey"})

    for r in spec.randomization:
        built = snap.questions.get(r.question_id)
        if built is None:
            continue
        if not any(k.startswith("random") for k in built.attributes):
            findings.append({"kind": "RANDOMIZATION_NOT_BUILT", "severity": "HIGH",
                             "subject": r.question_id,
                             "detail": "spec asks for randomization but the built "
                                       "question carries no randomization "
                                       "attribute"})

    # The termination mapping, recorded as a structural fact rather than a defect.
    terminating = [r for r in spec.rules if r.kind == "terminate"]
    if terminating:
        destinations = sorted({r.destination_id for r in terminating
                               if r.destination_id})
        recovered = [d for d in destinations if d in snap.termination_messages]
        findings.append({
            "kind": "TERMINATION_MODEL_DIFFERS", "severity": "NORMAL",
            "subject": ", ".join(destinations),
            "detail": ("LimeSurvey has no terminate action. The build inverts "
                       "every terminate rule into the main group's relevance "
                       "and nests the disposition messages into one end screen. "
                       f"Message text recovered for {len(recovered)} of "
                       f"{len(destinations)} screenout destinations. Assertions "
                       "must test 'main group suppressed' plus 'end screen "
                       "shows this text', never a page named after the "
                       "disposition."),
        })

        for did in destinations:
            if did not in snap.termination_messages:
                findings.append({
                    "kind": "DISPOSITION_MESSAGE_NOT_IN_BUILD",
                    "severity": "HIGH", "subject": did,
                    "detail": ("no message text for this disposition appears on "
                               "the built end screen, so a respondent who hits "
                               "it cannot be distinguished from one who "
                               "completed")})

        for msg, ids in shared_messages(snap.termination_messages).items():
            findings.append({
                "kind": "DISPOSITION_NOT_DISTINGUISHABLE", "severity": "HIGH",
                "subject": ", ".join(ids),
                "detail": (f"these {len(ids)} dispositions share identical end-"
                           f"screen text ({msg!r}), so Agent 4 sees the same "
                           "words whichever rule fired. An end-text assertion "
                           "proves a screenout occurred, not which one. To "
                           "distinguish them the QRE must give each "
                           "disposition its own wording.")})

    blocking = [f for f in findings if f["severity"] == "BLOCKING"]
    return {
        "lss_sha256": snap.lss_sha256,
        "questions_specified": len(spec_ids),
        "questions_built": len(built_ids),
        "options_bound": sum(1 for k in snap.bindings if "/" in k),
        "findings": findings,
        "blocking_count": len(blocking),
        "verdict": "CONFORMS_WITH_FINDINGS" if not blocking else "NOT_CONFORMANT",
        "note": ("Derived from the emitted .lss, not from a self-reported build "
                 "manifest. The .lss is what LimeSurvey actually imports, so it "
                 "is stronger evidence than a manifest of intent."),
    }
