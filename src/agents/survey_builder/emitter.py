"""Emit LimeSurvey LSS XML from the survey IR.

The schema here was derived by reading a real export, not from documentation.
Four things it gets right that are easy to get wrong:

1. answer_l10ns joins to answers on `aid`, not on qid + code. Without a unique
   aid the labels import as blank placeholders.

2. Multiple-choice options are subquestions, not answers, and they go in
   their own <subquestions> table. Putting them in <questions> with parent_qid
   set imports without error and leaves the parent with no options.

3. Subquestion labels still belong in question_l10ns alongside the real
   questions, keyed by the subquestion's own qid.

4. Attributes carrying display text need a populated <language> element or
   LimeSurvey drops them on import without complaint.
"""

from __future__ import annotations

from src.agents.survey_builder.models import Survey

DB_VERSION = "710"
LANGUAGE = "en"

#: A real export names the rendering theme on every question. The simple types
#: import without it, but F and K rely on it to render at all.
_QUESTION_THEME = {
    "L": "listradio",
    "M": "multiplechoice",
    "T": "longfreetext",
    "S": "shortfreetext",
    "F": "arrays/array",
    "K": "multiplenumeric",
}

_SURVEY_FIELDS = [
    "sid", "gsid", "admin", "adminemail", "anonymized", "format", "savetimings",
    "template", "language", "datestamp", "usecookie", "allowregister", "allowsave",
    "autoredirect", "allowprev", "printanswers", "ipaddr", "ipanonymize",
    "showsurveypolicynotice", "publicstatistics", "publicgraphs", "listpublic",
    "htmlemail", "sendconfirmation", "tokenanswerspersistence", "assessments",
    "usecaptcha", "usetokens", "bounce_email", "emailresponseto",
    "emailnotificationto", "tokenlength", "showxquestions", "showgroupinfo",
    "shownoanswer", "showqnumcode", "bounceprocessing", "showwelcome",
    "showprogress", "questionindex", "navigationdelay", "alloweditaftercompletion",
    "access_mode", "lastmodified",
]

_SURVEY_DEFAULTS = {
    "gsid": "1", "admin": "admin", "adminemail": "admin@example.com",
    "anonymized": "N", "format": "G", "savetimings": "N",
    "template": "fruity_twentythree", "language": LANGUAGE, "datestamp": "N",
    "usecookie": "N", "allowregister": "N", "allowsave": "Y", "autoredirect": "N",
    "allowprev": "Y", "printanswers": "N", "ipaddr": "N", "ipanonymize": "N",
    "showsurveypolicynotice": "0", "publicstatistics": "N", "publicgraphs": "N",
    "listpublic": "N", "htmlemail": "Y", "sendconfirmation": "Y",
    "tokenanswerspersistence": "I", "assessments": "I", "usecaptcha": "E",
    "usetokens": "N", "bounce_email": "inherit", "emailresponseto": "inherit",
    "emailnotificationto": "inherit", "tokenlength": "-1", "showxquestions": "I",
    "showgroupinfo": "I", "shownoanswer": "I", "showqnumcode": "I",
    "bounceprocessing": "N", "showwelcome": "I", "showprogress": "I",
    "questionindex": "-1", "navigationdelay": "-1",
    "alloweditaftercompletion": "I", "access_mode": "O",
    "lastmodified": "2026-01-01 00:00:00",
}


def _cdata(value) -> str:
    return f"<![CDATA[{value}]]>"


def _element(name: str, value) -> str | None:
    """None means omit the element entirely; "" means emit an empty one.

    LimeSurvey's own export makes this distinction: a NULL column is left out
    of the row, an empty-string column is written as <name/>. Emitting <name/>
    where the export omits the element stops subquestions importing.
    """
    if value is None:
        return None
    if value == "":
        return f"    <{name}/>"
    return f"    <{name}>{_cdata(value)}</{name}>"


def _table(name: str, fields: list[str], rows: list[dict]) -> list[str]:
    out = [f" <{name}>", "  <fields>"]
    out += [f"   <fieldname>{f}</fieldname>" for f in fields]
    out += ["  </fields>", "  <rows>"]
    for row in rows:
        out.append("   <row>")
        out += [e for e in (_element(f, row.get(f)) for f in fields) if e is not None]
        out.append("   </row>")
    out += ["  </rows>", f" </{name}>"]
    return out


#: Relevance strings name questions by title, e.g. "Q5.NAOK". On import
#: LimeSurvey rewrites those references as though the digits were a qid, so a
#: qid that collides with a title numeral corrupts the expression. Numbering
#: from well above any plausible question number avoids the collision.
_QID_BASE = 1000
_GID_BASE = 100


def _assign_ids(survey: Survey) -> None:
    """Number groups, questions, subquestions and answers.

    Subquestions are numbered in the same sequence as questions because they
    share the questions table.
    """
    next_qid = _QID_BASE
    next_aid = 1
    for index, group in enumerate(survey.groups):
        group.gid = _GID_BASE + index
        for question in group.questions:
            question.qid = next_qid
            next_qid += 1
            for subquestion in question.subquestions:
                subquestion.qid = next_qid
                next_qid += 1
            for option in question.options:
                option.aid = next_aid
                next_aid += 1


def emit(survey: Survey) -> str:
    _assign_ids(survey)
    sid = survey.sid

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<document>",
        " <LimeSurveyDocType>Survey</LimeSurveyDocType>",
        f" <DBVersion>{DB_VERSION}</DBVersion>",
        " <languages>",
        f"  <language>{LANGUAGE}</language>",
        " </languages>",
    ]

    out += _table("surveys", _SURVEY_FIELDS, [{"sid": sid, **_SURVEY_DEFAULTS}])

    out += _table(
        "surveys_languagesettings",
        ["surveyls_survey_id", "surveyls_language", "surveyls_title",
         "surveyls_description", "surveyls_welcometext", "surveyls_endtext",
         "surveyls_urldescription"],
        [{
            "surveyls_survey_id": sid,
            "surveyls_language": LANGUAGE,
            "surveyls_title": survey.title,
            "surveyls_description": survey.description,
            "surveyls_welcometext": survey.welcome_text,
            "surveyls_endtext": survey.end_text,
        }],
    )

    out += _table(
        "groups",
        ["gid", "sid", "group_order", "randomization_group", "grelevance"],
        [{"gid": g.gid, "sid": sid, "group_order": g.group_order,
          "grelevance": g.relevance} for g in survey.groups],
    )

    out += _table(
        "group_l10ns",
        ["id", "gid", "group_name", "description", "language"],
        [{"id": g.gid, "gid": g.gid, "group_name": g.name, "language": LANGUAGE}
         for g in survey.groups],
    )

    # Questions and subquestions share one table, and order matters: each
    # subquestion must follow its parent immediately.
    question_rows = []
    subquestion_rows = []
    l10n_rows = []
    for group in survey.groups:
        for question in group.questions:
            question_rows.append({
                "qid": question.qid, "parent_qid": 0, "sid": sid, "gid": group.gid,
                "type": question.type, "title": question.title, "other": "N",
                "mandatory": question.mandatory, "encrypted": "N",
                "question_order": question.question_order, "scale_id": 0,
                "same_default": 0, "relevance": question.relevance,
                "question_theme_name": _QUESTION_THEME.get(question.type),
                "same_script": 0,
            })
            l10n_rows.append({
                "id": question.qid, "qid": question.qid,
                "question": f"<p>{question.text}</p>", "language": LANGUAGE,
            })
            for subquestion in question.subquestions:
                subquestion_rows.append({
                    "qid": subquestion.qid, "parent_qid": question.qid, "sid": sid,
                    "gid": group.gid, "type": "T", "title": subquestion.code,
                    "other": "N", "encrypted": "N",
                    "question_order": subquestion.question_order, "scale_id": 0,
                    "same_default": 0, "relevance": "1", "same_script": 0,
                })
                l10n_rows.append({
                    "id": subquestion.qid, "qid": subquestion.qid,
                    "question": f"<p>{subquestion.label}</p>", "language": LANGUAGE,
                })

    out += _table(
        "questions",
        ["qid", "parent_qid", "sid", "gid", "type", "title", "other", "mandatory",
         "encrypted", "question_order", "scale_id", "same_default", "relevance",
         "question_theme_name", "same_script"],
        question_rows,
    )
    out += _table(
        "subquestions",
        ["qid", "parent_qid", "sid", "gid", "type", "title", "preg", "other",
         "mandatory", "encrypted", "question_order", "scale_id", "same_default",
         "relevance", "question_theme_name", "modulename", "same_script"],
        subquestion_rows,
    )
    out += _table(
        "question_l10ns", ["id", "qid", "question", "help", "language"], l10n_rows
    )

    attribute_rows = []
    for group in survey.groups:
        for question in group.questions:
            for name, value in question.attributes.items():
                attribute_rows.append({
                    "qid": question.qid, "attribute": name,
                    "value": value, "language": None,
                })
            for name, value in question.localized_attributes.items():
                attribute_rows.append({
                    "qid": question.qid, "attribute": name,
                    "value": value, "language": LANGUAGE,
                })
    out += _table(
        "question_attributes", ["qid", "attribute", "value", "language"],
        attribute_rows,
    )

    answer_rows = []
    answer_l10n_rows = []
    for group in survey.groups:
        for question in group.questions:
            for option in question.options:
                answer_rows.append({
                    "aid": option.aid, "qid": question.qid, "code": option.code,
                    "sortorder": option.sortorder, "assessment_value": 0, "scale_id": 0,
                })
                answer_l10n_rows.append({
                    "id": option.aid, "aid": option.aid,
                    "answer": f"<p>{option.label}</p>", "language": LANGUAGE,
                })

    out += _table(
        "answers", ["aid", "qid", "code", "sortorder", "assessment_value", "scale_id"],
        answer_rows,
    )
    out += _table(
        "answer_l10ns", ["id", "aid", "answer", "language"], answer_l10n_rows
    )

    out.append("</document>")
    return "\n".join(out)


def write(survey: Survey, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(emit(survey))