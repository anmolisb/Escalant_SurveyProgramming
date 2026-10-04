"""Agent 5: QA Adjudicator.

Agent 4 says what happened. This says what it means and who should act.

Why this is a separate step
---------------------------
A failing test is not a defect. On the first full S01 run, seven tests did not
pass and only two were the survey's fault; the rest were faults in the bot.
Had that run been reported as "seven defects", someone would have spent a day
investigating a survey that was behaving correctly.

Telling those apart needs the whole run rather than one test. Ten tests failing
on one question means something different from ten failing across ten
questions, and neither is visible from inside a single result.

What it decides
---------------
Every test that did not pass is given one cause and one owner:

    SURVEY_DEFECT       the built survey does not do what the questionnaire says
    SPECIFICATION_ERROR the questionnaire was read wrongly upstream
    NOT_BUILT_YET       the questionnaire asks for something not yet emitted
    UNSETTLED_QUESTION  the questionnaire never said, and a reading was assumed
    TEST_MODEL_GAP      the rule is enforced, but not in the way the test expects
    HARNESS_FAULT       the bot could not carry out the test

The last two matter. TEST_MODEL_GAP came out of a real run: a maximum length
enforced by preventing the respondent typing past it, rather than by rejecting
what they typed. The rule works. The test has no category for it. Reporting
that as a survey defect would be wrong, and hiding it would be worse, because
it is a real thing to fix in the test design.

The path view
-------------
A survey programmer does not think in test cases. They think in journeys: can a
respondent get through, and where do they come unstuck. So the report leads
with the paths, says which completed and which broke, and names the step it
broke at.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- causes

SURVEY_DEFECT = "SURVEY_DEFECT"
SPECIFICATION_ERROR = "SPECIFICATION_ERROR"
NOT_BUILT_YET = "NOT_BUILT_YET"
UNSETTLED_QUESTION = "UNSETTLED_QUESTION"
TEST_MODEL_GAP = "TEST_MODEL_GAP"
HARNESS_FAULT = "HARNESS_FAULT"
UNDECIDED = "UNDECIDED"

#: What each cause is called on screen. The codes above are fine inside the
#: code and useless on a report: nobody outside this team can tell
#: TEST_MODEL_GAP from SURVEY_DEFECT, and those two mean opposite things —
#: one blocks fielding and the other does not.
LABEL = {
    SURVEY_DEFECT: "The survey needs fixing",
    SPECIFICATION_ERROR: "The document was read wrongly",
    NOT_BUILT_YET: "Not built yet",
    UNSETTLED_QUESTION: "The document does not say what to do",
    TEST_MODEL_GAP: "Our check needs fixing, not the survey",
    HARNESS_FAULT: "The bot could not finish this one",
    UNDECIDED: "Someone needs to look at this",
}

#: Named as a person, because a QA analyst has to send this to someone.
OWNER = {
    SURVEY_DEFECT: "Whoever programs the survey",
    SPECIFICATION_ERROR: "Whoever owns the questionnaire reader",
    NOT_BUILT_YET: "Whoever programs the survey",
    UNSETTLED_QUESTION: "Whoever wrote the questionnaire",
    TEST_MODEL_GAP: "Whoever owns the test designer",
    HARNESS_FAULT: "Whoever owns the bot",
    UNDECIDED: "A QA analyst, by hand",
}

#: Which step of the pipeline produced the problem, said plainly. An analyst
#: needs to know where in the chain to look, not which module is at fault.
STAGE = {
    SURVEY_DEFECT: "Step 2, building the survey",
    SPECIFICATION_ERROR: "Step 1, reading the questionnaire",
    NOT_BUILT_YET: "Step 2, building the survey",
    UNSETTLED_QUESTION: "Before step 1: the questionnaire itself",
    TEST_MODEL_GAP: "Step 3, designing the tests",
    HARNESS_FAULT: "Step 4, running the tests",
    UNDECIDED: "Not yet known",
}

#: What an analyst should do about it before anyone writes code. Triage, not
#: repair: whether it blocks fielding, and what to gather.
TRIAGE = {
    SURVEY_DEFECT:
        "Treat as a defect. Do not field the survey until it is fixed: a "
        "real respondent hits this.",
    SPECIFICATION_ERROR:
        "Do not raise this against the survey yet. Check the questionnaire "
        "first, because the survey may be correct and the reading of it "
        "wrong.",
    NOT_BUILT_YET:
        "Already known. No new ticket. Confirm it is on the list and move "
        "on.",
    UNSETTLED_QUESTION:
        "Not a defect. Add it to the list of questions for the client and "
        "hold the test until they answer.",
    TEST_MODEL_GAP:
        "Not a defect in the survey. Raise it against the test design so "
        "the check stops reporting a problem that is not there.",
    HARNESS_FAULT:
        "No verdict either way. Re-run once the bot is fixed, and do not "
        "count this for or against the survey in the meantime.",
    UNDECIDED: "Read the evidence and classify it by hand.",
}

#: Plain words only. A survey programmer reading this should not have to know
#: what an agent is, what a canonical specification is, or what a guard is.
MEANS = {
    SURVEY_DEFECT:
        "The survey does not behave the way the questionnaire describes. A "
        "real respondent would see the wrong thing.",
    SPECIFICATION_ERROR:
        "The survey may well be fine. The questionnaire was read wrongly when "
        "it was turned into instructions, so the test is checking for the "
        "wrong behaviour.",
    NOT_BUILT_YET:
        "The questionnaire asks for something the survey does not have yet. "
        "This is expected to fail until it is added.",
    UNSETTLED_QUESTION:
        "The questionnaire does not say what should happen here, so a "
        "reasonable guess was made. Nothing is wrong until someone decides "
        "which behaviour is intended.",
    TEST_MODEL_GAP:
        "The rule works, but the survey enforces it a different way than the "
        "test looks for. Nothing is broken. The test needs to learn the other "
        "way.",
    HARNESS_FAULT:
        "The bot could not finish this test, so nothing was proved either "
        "way. This says nothing about the survey.",
    UNDECIDED:
        "No rule matched this one, so it has not been classified. Someone "
        "should read it.",
}

#: Where in the pipeline the correction belongs, in words rather than agent
#: numbers. Someone reading a defect report wants to know who to talk to.
WHERE = {
    SURVEY_DEFECT:
        "In the survey itself, inside LimeSurvey. Whoever builds the survey "
        "needs to change how this question is set up.",
    SPECIFICATION_ERROR:
        "In the step that reads the questionnaire. What it wrote down does "
        "not match what the document says, so the instructions everything "
        "else follows are wrong at this point.",
    NOT_BUILT_YET:
        "In the step that builds the survey. It does not produce this kind of "
        "behaviour yet, so nothing downstream can find it.",
    UNSETTLED_QUESTION:
        "Nowhere in the tooling. The questionnaire leaves this open, so the "
        "answer has to come from whoever wrote it.",
    TEST_MODEL_GAP:
        "In the step that designs the tests. It only knows one way for this "
        "rule to be enforced, and the survey uses another.",
    HARNESS_FAULT:
        "In the bot that runs the tests. It could not carry this one out.",
    UNDECIDED: "Not yet known.",
}

# Ranked by whether a real respondent's data would be wrong.
SEVERITY = {
    SURVEY_DEFECT: 1,
    SPECIFICATION_ERROR: 2,
    NOT_BUILT_YET: 3,
    TEST_MODEL_GAP: 4,
    UNSETTLED_QUESTION: 5,
    HARNESS_FAULT: 6,
    UNDECIDED: 7,
}


@dataclass
class Judgement:
    """One check that did not pass, and the four things an analyst needs.

    Held per check rather than per group, because the expected and observed
    sentences differ from one check to the next even when the cause is
    shared, and those two sentences are the whole evidence.
    """
    test_case_id: str
    question: str
    path_id: str
    title: str
    outcome: str
    cause: str
    label: str
    owner: str
    reason: str
    to_fix: str
    observed: str = ""
    order: int = 0
    #: 1 — what should have happened, and what did
    expected_text: str = ""
    observed_text: str = ""
    #: 2 — which part of the platform produced the problem
    component: str = ""
    component_why: str = ""
    #: 3 — what to change, and in which artefact
    fix_where: str = ""
    fix_what: str = ""
    #: 4 — the steps
    fix_how: str = ""
    #: what the bot actually did, and what the survey is set to do
    bot_did: str = ""
    diagnosis: str = ""


@dataclass
class PathVerdict:
    path_id: str
    name: str
    route_class: str
    tests: int = 0
    passed: int = 0
    failed: int = 0
    other: int = 0
    broke_at: str = ""          # the earliest question that failed
    first_failure: str = ""
    first_order: int = 9999
    causes: list = field(default_factory=list)

    #: Causes a respondent would actually notice. A journey is only broken if
    #: something on it would go wrong for a real person. A gap in our own test
    #: design failing on a journey says nothing about that journey, and
    #: calling it broken sends the reader to the wrong place, which is the
    #: first thing they read.
    _REAL = (SURVEY_DEFECT, SPECIFICATION_ERROR, NOT_BUILT_YET)

    @property
    def status(self) -> str:
        if any(c in self._REAL for c in self.causes):
            return "BROKEN"
        if self.failed or self.other:
            return "NOT PROVEN"
        return "WORKING"

    @property
    def status_note(self) -> str:
        if self.status == "WORKING":
            return "every test on this journey passed"
        if self.status == "BROKEN":
            return ("a respondent taking this journey would meet something "
                    "wrong")
        return ("nothing on this journey is known to be wrong, but not "
                "everything could be proved: "
                + ", ".join(self.causes))


# ---------------------------------------------------------------- deciding

#: Which part of the platform produced the problem, and what it produces.
#: Named the way the team talks about them rather than by agent number.
def _component(cause: str, dimension: str, question: str) -> tuple:
    """Which part of the platform, and what it got wrong on this question."""
    setting, _ = SETTING.get(dimension, ("the question settings", ""))
    where = question or "this survey"
    return {
        SURVEY_DEFECT: (
            "The survey builder",
            f"It writes the LimeSurvey file. What it wrote for {setting} on "
            f"{where} does not match what the questionnaire says."),
        SPECIFICATION_ERROR: (
            "The questionnaire reader",
            f"It turns the Word document into the instructions everything "
            f"else follows. It recorded {setting} for {where} wrongly."),
        NOT_BUILT_YET: (
            "The survey builder",
            f"It cannot write {setting} yet, so {where} was built without "
            f"it."),
        UNSETTLED_QUESTION: (
            "The questionnaire itself",
            f"It does not say what {where} should do for {setting}, so the "
            f"test designer picked a reading."),
        TEST_MODEL_GAP: (
            "The test designer",
            f"It wrote this check, and it knows only one way for {setting} "
            f"to be enforced on {where}."),
        HARNESS_FAULT: (
            "The respondent bot",
            f"It drives the survey in a browser and stopped before reaching "
            f"{setting} on {where}."),
        UNDECIDED: ("Not yet identified", ""),
    }[cause]


COMPONENT = {
    SURVEY_DEFECT: ("The survey builder",
                    "It writes the LimeSurvey file from the specification, "
                    "and what it wrote for this question does not match the "
                    "specification."),
    SPECIFICATION_ERROR: ("The questionnaire reader",
                          "It turns the Word document into the specification "
                          "everything else follows, and it recorded this "
                          "point wrongly."),
    NOT_BUILT_YET: ("The survey builder",
                    "It does not yet know how to produce this kind of "
                    "behaviour, so the survey was built without it."),
    UNSETTLED_QUESTION: ("The questionnaire itself",
                         "It does not say what should happen here, so the "
                         "test designer had to pick a reading."),
    TEST_MODEL_GAP: ("The test designer",
                     "It writes the checks, and it only knows one way for "
                     "this rule to be enforced."),
    HARNESS_FAULT: ("The respondent bot",
                    "It drives the survey in a browser, and it could not "
                    "complete this journey."),
    UNDECIDED: ("Not yet identified", ""),
}

#: Where the change goes, and what to change there.
FIX_WHERE = {
    SURVEY_DEFECT: "In LimeSurvey, on the question itself",
    SPECIFICATION_ERROR: "In the questionnaire reader, then regenerate",
    NOT_BUILT_YET: "In the survey builder, then rebuild the survey",
    UNSETTLED_QUESTION: "Nowhere in the platform, until the client answers",
    TEST_MODEL_GAP: "In the test designer, then redesign the tests",
    HARNESS_FAULT: "In the respondent bot, then run the tests again",
    UNDECIDED: "Not yet known",
}


#: Which LimeSurvey setting a check is about, by the kind of behaviour it
#: tests. Without this the advice can only say "how the question is set up",
#: which sends an analyst to read the whole question and work it out.
SETTING = {
    "D1": ("the Relevance equation",
           "the box on the question labelled Relevance equation, which "
           "decides whether the question is shown"),
    "D2": ("the end-of-survey routing",
           "the relevance equations that send a respondent to an end page, "
           "and the text on that end page"),
    "D3": ("the validation settings",
           "the question's validation: Maximum characters, Minimum "
           "characters, Minimum answers, or the validation equation"),
    "D4": ("the Mandatory setting",
           "the Mandatory switch on the question, which decides whether the "
           "respondent can leave it empty"),
    "D5": ("the array filter",
           "the Array filter attribute, which carries the options chosen "
           "earlier into this question"),
    "D6": ("the piped text",
           "the placeholder in the question wording that inserts an earlier "
           "answer"),
    "D7": ("the Randomize settings",
           "the Randomization group or Random order attribute on the "
           "question"),
    "D8": ("the quota",
           "the quota definition and its limit, under Settings then Quotas"),
    "D9": ("more than one setting at once",
           "the combination of relevance and dependency on this question"),
}


#: How each LimeSurvey setting enforces a rule, and what that means for a
#: test. The distinction matters: a setting that prevents the respondent
#: entering something can never produce a rejection to observe.
ENFORCEMENT = {
    "maximum_chars": ("the longest answer allowed", "prevents",
                      "the field will not accept more characters than this, "
                      "so there is nothing to reject and no error appears"),
    "em_validation_q": ("a validation equation", "rejects",
                        "the answer is checked on submit and refused with a "
                        "message if it fails"),
    "min_answers": ("the fewest options that must be chosen", "rejects",
                    "the page refuses to move on with a message"),
    "max_answers": ("the most options that may be chosen", "prevents",
                    "further boxes are disabled once the limit is reached"),
    "array_filter": ("carrying options forward", "filters",
                     "only the options chosen earlier are offered"),
    "random_order": ("shuffling", "reorders",
                     "the options are drawn in a different order each time"),
}


def _built_rules(built: dict) -> list:
    """What the survey actually does, read from the file that was built."""
    out = []
    for key, value in (built.get("attributes") or {}).items():
        if key.endswith("_tip"):
            continue
        name, how, effect = ENFORCEMENT.get(
            key, (key.replace("_", " "), "applies", ""))
        out.append({"setting": key, "value": str(value), "name": name,
                    "how": how, "effect": effect})
    if built.get("relevance") not in (None, "", "1"):
        out.append({"setting": "relevance", "value": str(built["relevance"]),
                    "name": "the Relevance equation", "how": "hides",
                    "effect": "the question is only shown when this is true"})
    if built.get("mandatory"):
        out.append({"setting": "mandatory", "value": "Y",
                    "name": "the Mandatory setting", "how": "rejects",
                    "effect": "the page refuses to move on if it is empty"})
    return out


def _what_the_bot_did(result: dict, question: str = "") -> str:
    """What the bot did to the question this check is about.

    Taking the last step of the journey is wrong: the last thing filled is
    whatever came at the end of the survey, not the question under test. On a
    check about Q6 that reported "at Q8, the bot typed x", which points a
    reader at the wrong question entirely.
    """
    steps = [a for a in (result.get("actions") or [])
             if a.get("did") and not str(a.get("did")).startswith("clicked")
             and not str(a.get("did")).startswith("submitted")]
    if not steps:
        return ""
    if question:
        mine = [a for a in steps
                if str(a.get("question") or "").split("/")[0] == question]
        if mine:
            did = "; then ".join(str(a.get("did")) for a in mine)
            return f"At {question}, the bot {did}."
        # The check is about a question the bot never answered, which is
        # itself the finding: it was meant to be hidden, or never appeared.
        return (f"The bot never answered {question} on this journey.")
    last = steps[-1]
    who = last.get("question") or ""
    return f"At {who}, the bot {last.get('did')}." if who else ""


def _how_enforced(built: dict) -> tuple:
    """What the built survey uses to enforce this, split by mechanism.

    A setting that stops the respondent entering something can never produce
    a rejection to observe, so a check expecting one will always fail. That
    distinction is usually the whole explanation, and it is only knowable by
    reading the file that was built.
    """
    prevents, rejects = [], []
    for key, value in (built.get("attributes") or {}).items():
        if key.endswith("_tip"):
            continue
        name, how, _ = ENFORCEMENT.get(key, (key.replace("_", " "),
                                             "applies", ""))
        entry = f"{name} ({key} = {value})"
        if how == "prevents":
            prevents.append(entry)
        elif how == "rejects":
            rejects.append(entry)
    if built.get("mandatory"):
        rejects.append("the Mandatory setting")
    return prevents, rejects


def _diagnose(dimension: str, question: str, built: dict,
              asked: str, result: dict) -> str:
    """One sentence saying why the survey and the check disagree."""
    prevents, rejects = _how_enforced(built)
    if dimension == "D3" and prevents:
        return (f"{question} uses {' and '.join(prevents)}, which stops the "
                f"respondent entering a bad answer rather than rejecting one, "
                f"so the rejection the check waits for can never happen.")
    if dimension == "D1" and built.get("relevance") not in (None, "", "1"):
        wanted = asked or "a different condition"
        return (f"{question} is shown when {built['relevance']} in the built "
                f"survey. The questionnaire asks for {wanted}.")
    return ""


def _specifics(cause: str, dimension: str, question: str,
               condition: str, built: dict) -> tuple:
    """What to change and how, named exactly rather than in general terms.

    A lookup on the cause alone produces the same sentence for every check
    that shares it. An analyst needs the question, the setting on that
    question, and what it should say, which can only come from the check.
    """
    setting, setting_detail = SETTING.get(
        dimension, ("the question settings", "the settings on this question"))
    where = question or "the survey"
    should = f" It should be: {condition}." if condition else ""

    if cause == SURVEY_DEFECT:
        return (f"{where} \u2192 {setting}",
                f"Change {setting_detail}.{should}",
                f"Open the survey in LimeSurvey, go to {where}, and correct "
                f"{setting}. Save, then run the tests again. If you would "
                f"rather rebuild from the questionnaire, fix it there instead "
                f"and re-run every step.")

    if cause == SPECIFICATION_ERROR:
        return (f"The recorded reading of {where}",
                f"The reader wrote down the wrong thing for {setting} on "
                f"{where}.{should} Compare that against the Word document.",
                f"Correct the reading for {where}, run the questionnaire "
                f"reader again, rebuild the survey, redesign the tests, and "
                f"re-run. The survey may have been right all along.")

    if cause == NOT_BUILT_YET:
        return (f"The builder, for {setting}",
                f"The builder does not write {setting_detail} yet, so {where} "
                f"was built without it.",
                f"No action on this check. Once the builder emits {setting} "
                f"and the survey is rebuilt, it will pass.")

    if cause == UNSETTLED_QUESTION:
        return ("The questionnaire, not the platform",
                f"The questionnaire does not say what {where} should do here, "
                f"so a reading was assumed to write the check.",
                "Ask whoever wrote the questionnaire. Record their answer as "
                "the agreed reading, then redesign the tests. Nothing in the "
                "platform changes until they reply.")

    if cause == TEST_MODEL_GAP:
        prevents, rejects = _how_enforced(built)
        what = (f"Change the check to confirm the field caps the answer at "
                f"{prevents[0]} rather than expecting a refusal. Nothing on "
                f"{where} needs changing."
                if prevents else
                f"Change the check to look for the way {setting} is actually "
                f"enforced. Nothing on {where} needs changing.")
        if rejects:
            does = "do" if len(rejects) > 1 else "does"
            what += (f" Worth knowing: {' and '.join(rejects)} on {where} "
                     f"{does} reject a bad answer and {does} show a message, "
                     f"so that half is working and could be checked "
                     f"separately.")
        return (f"The check for {setting} on {where}", what,
                f"Confirm in LimeSurvey that a respondent genuinely cannot "
                f"break the rule on {where}. Then change the check, redesign "
                f"the tests, and run again. Do not raise anything against the "
                f"survey.")

    if cause == HARNESS_FAULT:
        return (f"The bot, on its way to {where}",
                f"The bot stopped before it could check {setting} on {where}.",
                f"Re-run this one test alone with the browser visible to see "
                f"where it stops. Fix that, then run the package again. Leave "
                f"the check unscored until then.")

    return ("Not yet identified", "Read the evidence and classify it by hand.",
            "Decide the cause first.")


def _decide(result: dict, index_row: dict, conformance: list,
            provisional: list) -> tuple:
    """One test's cause, why it happened, and what to do about it.

    The order of these questions is the argument. A failure the bot caused is
    not evidence about the survey, so that is asked first. A behaviour nobody
    has built yet cannot be a fault in the thing that builds it, so that is
    asked next. The survey is blamed only when nothing else explains it.

    The questionnaire itself is taken as correct on logic. It is only at
    fault when it leaves something out, and then the answer has to come from
    whoever wrote it rather than from anyone fixing code.
    """
    status = result.get("status")
    question = index_row.get("question", "")
    title = (result.get("title") or "").lower()
    seen = " ".join(str(c.get("actually", "")) for c in result.get("checks", []))
    where = question or "this survey"

    # 1. Did the test actually run
    if status in ("BLOCKED", "SKIPPED"):
        return (HARNESS_FAULT,
                f"The bot never reached the point it was testing, so it saw "
                f"nothing about {where}.",
                "Fix the bot and run this test again. Until then it is "
                "neither a pass nor a failure, and it should not be counted "
                "as either.")

    if status == "INCONCLUSIVE":
        return (TEST_MODEL_GAP,
                f"The bot got to {where} but could not tell whether the "
                f"survey did the right thing.",
                "Give the test something it can actually look at, or record "
                "that this claim cannot be proved by running the survey.")

    # 2. Is the behaviour even built yet
    for f in conformance:
        if f.get("subject", "").split("/")[0] != question:
            continue
        if f.get("kind") in ("RANDOMIZATION_NOT_BUILT", "QUOTAS_NOT_BUILT",
                             "SKIP_RULE_NOT_BUILT", "REJECT_RULE_NOT_BUILT",
                             "GUARD_NOT_BUILT"):
            missing = {"RANDOMIZATION_NOT_BUILT": "shuffling the options",
                       "QUOTAS_NOT_BUILT": "the quotas",
                       "SKIP_RULE_NOT_BUILT": "the skip rule",
                       "REJECT_RULE_NOT_BUILT": "the answer rule",
                       "GUARD_NOT_BUILT": "the rule that hides this question"
                       }[f["kind"]]
            return (NOT_BUILT_YET,
                    f"The questionnaire asks for {missing} at {where}, and "
                    f"the survey does not have it. This was already known "
                    f"before the bot ran.",
                    f"Nothing to do on this test. It will pass once {missing} "
                    f"is added to the survey.")

    # 3. Was the questionnaire read wrongly when it was turned into instructions
    for f in conformance:
        if f.get("subject", "").split("/")[0] != question:
            continue
        if f.get("kind") == "GUARD_CANNOT_BE_FALSIFIED":
            return (SPECIFICATION_ERROR,
                    f"The rule that decides when {where} appears was written "
                    f"down in a way that is always true, so {where} can never "
                    f"be hidden. That is a mistake in the reading, not in the "
                    f"questionnaire.",
                    f"Correct how {where}'s display rule was read, then run "
                    f"the whole thing again. The survey may well be fine.")
        if f.get("kind") == "DISPOSITION_NOT_DISTINGUISHABLE":
            return (SPECIFICATION_ERROR,
                    "Several endings in this survey show identical wording, "
                    "so reaching one of them cannot prove which one it was.",
                    "Give each ending its own wording in the questionnaire. "
                    "Until then this test can only show that the respondent "
                    "was screened out, not why.")

    # 4. A rule enforced a different way than the test expects
    if ("rejects" in title or "refuses" in title) and \
            "accepted the answer and moved on" in seen and \
            "no error message appeared" in seen:
        return (TEST_MODEL_GAP,
                f"The survey took the answer without complaining. That is "
                f"what happens when a limit is enforced by stopping the "
                f"respondent entering it in the first place, rather than by "
                f"rejecting it afterwards. The test only looks for a "
                f"rejection.",
                f"Check how the rule is set up on {where}. If the respondent "
                f"cannot break it at all, the rule works and the test should "
                f"be written to check that instead.")

    # 5. Does it rest on something nobody has ruled on
    if provisional:
        readable = {
            "whitespace_is_an_answer":
                "whether typing only spaces counts as answering a compulsory "
                "question",
            "unasked_reference":
                "what a rule means when it mentions a question the respondent "
                "never saw",
            "rule_precedence": "which rule wins when two of them apply at once",
            "multi_equality":
                "whether \u201cequals\u201d for a tick-box question means "
                "exactly those options or at least those options",
        }
        points = [readable.get(p, p) for p in provisional]
        return (UNSETTLED_QUESTION,
                "The questionnaire does not say " + points[0]
                + (f", and {len(points) - 1} other point(s) like it"
                   if len(points) > 1 else "")
                + ". A reasonable reading was assumed so the test could be "
                  "written.",
                "Ask whoever wrote the questionnaire which behaviour they "
                "intended. Until then this is an open question rather than a "
                "defect, and the survey is not necessarily wrong.")

    # 6. Nothing else explains it
    if status == "FAILED":
        return (SURVEY_DEFECT,
                f"The bot reached {where}, did what the test said, and the "
                f"survey did not behave the way the questionnaire describes.",
                f"Open {where} in LimeSurvey and compare how it is set up "
                f"against what the questionnaire says it should do.")

    return (UNDECIDED, "No rule matched this one.",
            "Read this one by hand and decide what it means.")


# ---------------------------------------------------------------- the run

def adjudicate(directory: Path) -> dict:
    a4 = json.loads((directory / "agent4" / "agent4_results.json")
                    .read_text(encoding="utf-8"))
    index = {r["executable_id"]: r for r in json.loads(
        (directory / "agent3" / "agent3_test_case_index.json")
        .read_text(encoding="utf-8"))["tests"] if r.get("executable_id")}

    conf_file = directory / "agent3" / "agent3_conformance.json"
    conformance = []
    if conf_file.exists():
        conformance = (json.loads(conf_file.read_text(encoding="utf-8"))
                       .get("content", {}).get("findings", []))

    paths = []
    paths_file = directory / "agent3" / "agent3_paths.json"
    if paths_file.exists():
        paths = (json.loads(paths_file.read_text(encoding="utf-8"))
                 .get("content", {}).get("paths", []))

    # What the questionnaire states for each question, so the advice can say
    # what a setting should contain rather than only naming the setting.
    conditions: dict = {}
    canonical = directory / "part2_canonical.json"
    if canonical.exists():
        doc = json.loads(canonical.read_text(encoding="utf-8"))
        for q in (doc.get("content") or doc).get("questions", []):
            guard = (q.get("guard") or {}).get("condition") or {}
            text = guard.get("source_text")
            rules = {k: v for k, v in (q.get("validation") or {}).items()
                     if v is not None and k not in ("mandatory_origin",)}
            if text:
                conditions[q["question_id"]] = text
            elif rules:
                readable = ", ".join(
                    f"{k.replace('_', ' ')} {v}" for k, v in rules.items()
                    if k != "mandatory")
                if rules.get("mandatory"):
                    readable = ("must be answered"
                                + (f", {readable}" if readable else ""))
                conditions[q["question_id"]] = readable

    # What the survey was actually built to do. Agent 3 records every
    # setting it found in the file, and reading it back is the difference
    # between naming a category and explaining a failure.
    snapshot: dict = {}
    snap_file = directory / "agent3" / "implementation_snapshot.json"
    if snap_file.exists():
        doc = json.loads(snap_file.read_text(encoding="utf-8"))
        content = doc.get("content", doc)
        for entry in (content.get("questions") or {}).values():
            if isinstance(entry, dict) and entry.get("canonical_id"):
                snapshot[entry["canonical_id"]] = entry

    judgements: list[Judgement] = []
    verdicts: dict[str, PathVerdict] = {
        p["path_id"]: PathVerdict(p["path_id"], p.get("name", ""),
                                  p.get("route_class", ""))
        for p in paths}

    for r in a4.get("results", []):
        if not r.get("status"):
            # A row with no outcome is not a result. Counting it would inflate
            # the totals with something that never ran.
            continue
        row = index.get(r.get("test_id"), {})
        pid = row.get("path_id") or ""
        v = verdicts.get(pid)
        if v:
            v.tests += 1

        if r.get("status") == "PASSED":
            if v:
                v.passed += 1
            continue

        cause, reason, to_fix = _decide(
            r, row, conformance, r.get("provisional") or [])

        # The bot writes a sentence for what should have happened and one for
        # what did. Those are the evidence, so they are kept per check rather
        # than summarised: two checks under one cause rarely failed the same
        # way, and a summary hides which is which.
        failed_checks = [c for c in (r.get("checks") or [])
                         if c.get("matched") is False]
        # Older runs recorded only the machine-readable kind, so fall back to
        # a sentence built from it. A blank "what should have happened" is
        # worse than a plain one.
        PLAIN = {
            "page_does_not_advance": "the survey should have refused to move on",
            "page_advances": "the survey should have moved on",
            "field_present": "the question should have been on screen",
            "next_field_present": "the next question should have appeared",
            "error_shown_on_question": "an error message should have appeared",
            "survey_completed": "the respondent should have reached the end",
            "not_on_end_page": "the respondent should still have been answering",
            "group_suppressed": "no main-section question should have appeared",
            "question_text_contains": "the wording should have carried the "
                                      "earlier answer",
            "end_page_message": "the final page should have shown its own wording",
        }
        expected_text = " ".join(
            str(c.get("should") or PLAIN.get(c.get("kind"), "")) 
            for c in failed_checks).strip()
        observed_text = " ".join(str(c.get("actually") or "")
                                 for c in failed_checks).strip()
        if not expected_text and r.get("blocked_reason"):
            expected_text = ("The bot should have reached this point and "
                             "checked it.")
            observed_text = str(r.get("blocked_reason"))
        if not expected_text:
            # Last resort: the test's own name says what it was checking, so
            # a reader is never left with an empty box.
            expected_text = (f"What the check is named for: "
                             f"{r.get('title') or 'see the test'}.")
        if not observed_text:
            observed_text = "The bot recorded no detail for this one."

        dimension = row.get("dimension", "")
        question = row.get("question") or ""
        # The condition the questionnaire actually states, so the advice can
        # say what the setting should contain rather than only naming it.
        condition = conditions.get(question, "")
        built = snapshot.get(question, {})
        component, component_why = _component(cause, dimension, question)
        diagnosis = _diagnose(dimension, question or "this question",
                              built, condition, r)
        bot_did = _what_the_bot_did(r, question)
        # The diagnosis belongs inside the section it explains, not beside
        # them as a fifth thing to read.
        if diagnosis:
            component_why = f"{component_why} {diagnosis}"
        fix_where, fix_what, fix_how = _specifics(
            cause, dimension, question, condition, built)
        j = Judgement(
            test_case_id=row.get("test_case_id") or r.get("test_id", ""),
            question=row.get("question", ""),
            path_id=pid,
            title=r.get("title", ""),
            outcome=r.get("status", ""),
            cause=cause, label=LABEL[cause], owner=OWNER[cause],
            reason=reason, to_fix=to_fix,
            order=row.get("order", 0),
            observed=observed_text,
            expected_text=expected_text,
            observed_text=observed_text,
            component=component, component_why=component_why,
            fix_where=fix_where, fix_what=fix_what, fix_how=fix_how,
            bot_did=bot_did, diagnosis=diagnosis)
        judgements.append(j)

        if v:
            if r.get("status") == "FAILED":
                v.failed += 1
            else:
                v.other += 1
            if cause not in v.causes:
                v.causes.append(cause)
            # The earliest question in questionnaire order is where the
            # journey first came unstuck, which is the one worth naming.
            if j.order and j.order < v.first_order:
                v.broke_at = j.question or "start"
                v.first_failure = j.title
                v.first_order = j.order

    return {"judgements": judgements, "paths": verdicts, "a4": a4}


# ---------------------------------------------------------------- grouping

def group(judgements: list[Judgement]) -> list[dict]:
    """Collect failures that share a cause and a question.

    One mistake upstream can fail nine tests. Listing nine defects invites nine
    investigations of one problem, so they are reported once with the nine
    underneath.
    """
    buckets: dict[tuple, list[Judgement]] = defaultdict(list)
    for j in judgements:
        buckets[(j.cause, j.question)].append(j)

    out = []
    for (cause, question), group_js in buckets.items():
        out.append({
            "cause": cause,
            "label": LABEL[cause],
            "owner": OWNER[cause],
            "question": question or "whole survey",
            "count": len(group_js),
            "means": MEANS[cause],
            "where_to_fix": WHERE[cause],
            "stage": STAGE[cause],
            "triage": TRIAGE[cause],
            "reason": group_js[0].reason,
            "to_fix": group_js[0].to_fix,
            "tests": [j.test_case_id or "(unnamed)" for j in group_js],
            "what_failed": [
                {"test": j.test_case_id, "title": j.title,
                 "observed": j.observed} for j in group_js],
            "severity": SEVERITY[cause],
            "order": min((j.order for j in group_js), default=999),
        })
    out.sort(key=lambda g: (g["severity"], g["order"]))
    return out


# ---------------------------------------------------------------- the report

PATH_FILL = {"WORKING": "DAEDEA", "BROKEN": "F8E4E6",
             "NOT PROVEN": "FAEBDE"}
PATH_FONT = {"WORKING": "0F766E", "BROKEN": "A32C36",
             "NOT PROVEN": "9C4709"}
CAUSE_FILL = {
    SURVEY_DEFECT: "F8E4E6", SPECIFICATION_ERROR: "FAEBDE",
    NOT_BUILT_YET: "EFEFEF", UNSETTLED_QUESTION: "E4E1F7",
    TEST_MODEL_GAP: "E4E1F7", HARNESS_FAULT: "EFEFEF", UNDECIDED: "FAEBDE",
}
CAUSE_FONT = {
    SURVEY_DEFECT: "A32C36", SPECIFICATION_ERROR: "9C4709",
    NOT_BUILT_YET: "635E7E", UNSETTLED_QUESTION: "4338A8",
    TEST_MODEL_GAP: "4338A8", HARNESS_FAULT: "635E7E", UNDECIDED: "9C4709",
}
INK = "1B1832"


def write_report(path: Path, data: dict, survey: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    thin = Side(style="thin", color="C7C2DC")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(vertical="top", wrap_text=True)

    judgements = data["judgements"]
    verdicts = list(data["paths"].values())
    groups = group(judgements)
    counts = data["a4"].get("counts", {})

    wb = Workbook()

    # ---- 1. the journeys, because that is how a programmer thinks --------
    ws = wb.active
    ws.title = "Respondent journeys"
    ws["A1"] = f"Which journeys through {survey} work"
    ws["A1"].font = Font(name="Calibri", size=15, bold=True, color=INK)
    ws["A2"] = ("A journey is one complete route a respondent can take. Each "
                "one carries the tests that can only be checked along it, so "
                "a broken journey means a respondent taking that route meets "
                "something wrong.")
    ws["A2"].font = Font(name="Calibri", size=10, italic=True, color="4A4566")
    ws.merge_cells("A2:H2")

    head = ["Path", "The journey", "Kind", "Status", "What the status means",
            "Tests on it", "Passed", "Came unstuck at",
            "What went wrong first"]
    for i, h in enumerate(head, 1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=INK)
        c.alignment = Alignment(vertical="bottom", wrap_text=True)
    for col, w in zip("ABCDEFGHI", (8, 40, 19, 14, 44, 11, 9, 16, 44)):
        ws.column_dimensions[col].width = w

    for r, v in enumerate(sorted(verdicts, key=lambda x: x.path_id), start=5):
        values = [v.path_id, v.name, v.route_class, v.status, v.status_note,
                  v.tests, v.passed, v.broke_at or "-",
                  v.first_failure or "-"]
        for i, val in enumerate(values, 1):
            c = ws.cell(row=r, column=i, value=val)
            c.font = Font(name="Calibri", size=10)
            c.border = box
            c.alignment = wrap
        ws.cell(row=r, column=4).font = Font(
            name="Calibri", size=10, bold=True, color=PATH_FONT[v.status])
        ws.cell(row=r, column=4).fill = PatternFill(
            "solid", fgColor=PATH_FILL[v.status])
    ws.freeze_panes = "A5"

    note = ws.cell(row=len(verdicts) + 6, column=1, value=(
        "WORKING means every test on this journey passed.\n"
        "BROKEN means a respondent taking it would meet something wrong: a "
        "defect in the survey, a misreading of the questionnaire, or a rule "
        "not built yet.\n"
        "NOT PROVEN means nothing is known to be wrong, but something could "
        "not be checked. A gap in our own test design failing on a journey "
        "says nothing about that journey, so it is not called broken."))
    note.font = Font(name="Calibri", size=10, italic=True, color="4A4566")
    note.alignment = wrap
    ws.merge_cells(start_row=len(verdicts) + 6, start_column=1,
                   end_row=len(verdicts) + 6, end_column=9)
    ws.row_dimensions[len(verdicts) + 6].height = 44

    # ---- 2. what to fix, grouped -----------------------------------------
    ws = wb.create_sheet("What to fix")
    ws["A1"] = "What needs correcting, and by whom"
    ws["A1"].font = Font(name="Calibri", size=15, bold=True, color=INK)
    ws["A2"] = ("Failures that share a cause and a question are reported once. "
                "One mistake upstream can fail nine tests, and nine entries "
                "would invite nine investigations of one problem. Ordered so "
                "that anything a real respondent would notice comes first.")
    ws["A2"].font = Font(name="Calibri", size=10, italic=True, color="4A4566")
    ws.merge_cells("A2:G2")

    head = ["Cause", "Question", "Tests", "Who should act",
            "What this means", "Why it was judged this way", "What to do"]
    for i, h in enumerate(head, 1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=INK)
        c.alignment = Alignment(vertical="bottom", wrap_text=True)
    for col, w in zip("ABCDEFG", (22, 11, 26, 24, 46, 50, 50)):
        ws.column_dimensions[col].width = w

    for r, g in enumerate(groups, start=5):
        values = [g.get("label", g["cause"]), g["question"],
                  ", ".join(g["tests"]),
                  g["owner"], g["means"], g["reason"], g["to_fix"]]
        for i, val in enumerate(values, 1):
            c = ws.cell(row=r, column=i, value=val)
            c.font = Font(name="Calibri", size=10)
            c.border = box
            c.alignment = wrap
        ws.cell(row=r, column=1).font = Font(
            name="Calibri", size=10, bold=True, color=CAUSE_FONT[g["cause"]])
        ws.cell(row=r, column=1).fill = PatternFill(
            "solid", fgColor=CAUSE_FILL[g["cause"]])
    ws.freeze_panes = "A5"

    # ---- 3. every judgement, for anyone who wants the detail -------------
    ws = wb.create_sheet("Every test judged")
    head = ["Order", "Test Case ID", "Question", "Path", "What was tested",
            "Outcome", "Cause", "What the bot saw", "What to do"]
    for i, h in enumerate(head, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=INK)
        c.alignment = Alignment(vertical="bottom", wrap_text=True)
    for col, w in zip("ABCDEFGHI", (7, 13, 10, 7, 44, 13, 22, 48, 46)):
        ws.column_dimensions[col].width = w

    for r, j in enumerate(sorted(judgements, key=lambda x: x.order), start=2):
        values = [j.order, j.test_case_id, j.question, j.path_id, j.title,
                  j.outcome, j.label or j.cause, j.observed, j.to_fix]
        for i, val in enumerate(values, 1):
            c = ws.cell(row=r, column=i, value=val)
            c.font = Font(name="Calibri", size=10)
            c.border = box
            c.alignment = wrap
        ws.cell(row=r, column=7).font = Font(
            name="Calibri", size=10, bold=True, color=CAUSE_FONT[j.cause])
        ws.cell(row=r, column=7).fill = PatternFill(
            "solid", fgColor=CAUSE_FILL[j.cause])
    ws.freeze_panes = "A2"
    if judgements:
        ws.auto_filter.ref = f"A1:I{len(judgements) + 1}"

    wb.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent 5: adjudicate a run.")
    ap.add_argument("survey_dir")
    args = ap.parse_args()

    directory = Path(args.survey_dir)
    for needed in ("agent4/agent4_results.json",
                   "agent3/agent3_test_case_index.json"):
        if not (directory / needed).exists():
            print(f"missing {needed}. Run Agent 3 and then Agent 4 first.")
            return 1

    data = adjudicate(directory)
    groups = group(data["judgements"])
    verdicts = list(data["paths"].values())

    print(f"\n  Agent 5: {directory.name}")
    print("  " + "=" * 62)
    working = sum(1 for v in verdicts if v.status == "WORKING")
    print(f"  journeys      {working} of {len(verdicts)} working")
    passed = data["a4"].get("counts", {}).get("PASSED", 0)
    total = sum(data["a4"].get("counts", {}).values())
    print(f"  tests         {passed} of {total} passed")
    print()
    for v in sorted(verdicts, key=lambda x: x.path_id):
        mark = {"WORKING": "ok  ", "BROKEN": "FAIL", "NOT PROVEN": "?   "}
        print(f"    {mark[v.status]}  {v.path_id}  {v.name[:46]:<48}"
              + (f"broke at {v.broke_at}" if v.broke_at else ""))
    print()
    if groups:
        print("  WHAT TO FIX")
        for g in groups:
            print(f"    {g.get('label', g['cause']):<38} "
                  f"{g['question']:<6} {g['count']} check(s)")
            print(f"        -> {g['owner']}")
            print(f"        {g['to_fix'][:92]}")
    else:
        print("  Nothing to fix. Every test passed.")

    dest = directory / "agent5"
    dest.mkdir(exist_ok=True)
    book = dest / "agent5_qc_report.xlsx"
    try:
        write_report(book, data, directory.name)
    except PermissionError:
        book = dest / f"agent5_qc_report_{datetime.now():%H%M%S}.xlsx"
        write_report(book, data, directory.name)
    (dest / "agent5_findings.json").write_text(json.dumps({
        "survey": directory.name,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        # asdict only serialises declared fields, so a computed property is
        # silently dropped. Anything reading this file then has no status at
        # all, and a reader defaulting it to WORKING would report every
        # journey as fine while counting none of them.
        "journeys": [{**asdict(v), "status": v.status,
                      "status_note": v.status_note} for v in verdicts],
        "groups": groups,
        "judgements": [asdict(j) for j in data["judgements"]],
    }, indent=2, default=str), encoding="utf-8")
    print(f"\n  wrote {book}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
