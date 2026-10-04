"""Respondent Bot: drives a real browser through Agent 3's tests.

This is the version to demonstrate. It opens a visible browser, fills each
answer the way a respondent would, moves through the survey, and records what
it saw. At the end it writes an Excel workbook showing what the bot did, what
it expected, what it found, and why anything failed.

Why a browser rather than HTTP requests
---------------------------------------
An earlier version posted forms directly. It worked, but two things were wrong
with it for this purpose. It could not be watched, which matters when the point
is to show the thing running. And it had to reconstruct what a browser would
send, which is where its worst bug came from: every radio option carries a
value in the markup, so copying the form pre-filled every question, and a test
meant to leave a question blank submitted an answer instead. A browser does not
make that mistake, because it only sends what is actually selected.

Five outcomes, not two
----------------------
    PASSED            every assertion was observed and matched
    FAILED            an assertion was observed and did not match
    BLOCKED           the journey could not complete, so nothing was asserted
    INCONCLUSIVE      the assertion could not be observed at all
    SKIPPED           needs several respondents, not a single journey

BLOCKED is not FAILED. A test that could not run tells you nothing about the
survey, and recording it as a failure would send someone hunting a defect that
may not exist.

What this agent does not decide
-------------------------------
What a failure means. It might be a defect in the survey, a wrong reading in
the specification, or a gap the survey builder already knows about. Working
that out needs the whole picture across every test, and it is Agent 5's job.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PASSED, FAILED, BLOCKED = "PASSED", "FAILED", "BLOCKED"
INCONCLUSIVE, SKIPPED = "INCONCLUSIVE", "SKIPPED"

STATUS_ORDER = [PASSED, FAILED, BLOCKED, INCONCLUSIVE, SKIPPED]


# ---------------------------------------------------------------- records

@dataclass
class Action:
    """One thing the bot did, in the words a person would use."""
    step: int
    question: str
    did: str
    detail: str = ""


@dataclass
class Check:
    """One thing that was meant to happen, and what did.

    Every field here is written to be read by a person. The machine-readable
    kind is kept for the JSON, but the report shows the sentences, because
    "field_present: True / False" tells a reader nothing about what went wrong.
    """
    kind: str
    target: str
    expected: Any                 # kept for the JSON record
    observed: Any
    matched: bool | None
    why: str = ""
    should: str = ""              # what should have happened, in words
    actually: str = ""            # what did happen, in words


@dataclass
class Result:
    test_id: str
    title: str
    dimension: str
    #: The readable id and position Agent 3 gave this test. Carried through so
    #: the two reports can be read side by side, which they could not be while
    #: Agent 3 said TC-FT01 and Agent 4 said EX-36fbba288b for the same test.
    case_id: str = ""
    order: int = 0
    question: str = ""
    status: str = BLOCKED
    actions: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    blocked_reason: str = ""
    provisional: list = field(default_factory=list)
    seconds: float = 0.0


# ---------------------------------------------------------------- the driver

class Bot:
    def __init__(self, page, base: str, sid: str, wording: dict[str, str],
                 options: dict[str, dict[str, str]] | None = None):
        self.page = page
        self.base = base.rstrip("/")
        self.sid = str(sid)
        #: question id -> its wording, for finding the live field
        self.wording = wording
        #: Which of Agent 3's questions were on screen, in the order the
        #: respondent met them. A test asking "does answering Q1 lead to Q2"
        #: is about a moment in the middle of the journey, not about the page
        #: the respondent finishes on, so the answer has to be recorded while
        #: passing through.
        self.seen: list[str] = []
        #: The text of every page passed through. A question's wording can
        #: only be read while that question is on screen, and by the end of
        #: the journey the respondent is looking at a thank-you page.
        self.seen_text: list[str] = []
        #: The questions on the current page, read once and reused until the
        #: page changes.
        self._cache = None
        #: question id -> {option id -> its label}, for finding the live option.
        #: Needed because LimeSurvey renumbers sub-questions on import exactly
        #: as it renumbers questions: Agent 3's SQ001 is served as S17.
        self.options = options or {}

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join((text or "").split()).casefold().rstrip(" .:?!")

    def visible_questions(self) -> dict[str, str]:
        """Live field name -> the wording rendered beside it.

        The only dependable way to tell which live field is which question.
        LimeSurvey renumbers question ids when a survey is imported, so the
        identifier Agent 3 compiled does not survive. The wording does.
        """
        if getattr(self, "_cache", None) is not None:
            return self._cache
        out: dict[str, str] = {}
        try:
            elements = self.page.query_selector_all('[id^="ls-question-text-"]')
        except Exception:
            # The page navigated while it was being read. That is a race, not
            # a fault, and the caller can look again in a moment.
            return out
        for el in elements:
            try:
                ident = el.get_attribute("id") or ""
                out[ident.replace("ls-question-text-", "")] = " ".join(
                    (el.inner_text() or "").split())
            except Exception:
                continue
        return out

    def note_visible(self) -> None:
        """Record what is on the current page, before moving off it.

        The page is read once here and cached. Every other method used to ask
        the browser again, and a DOM round trip is the most expensive thing
        this bot does.
        """
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        self._cache = None
        text = self.page_text()
        if text:
            self.seen_text.append(text)
        live = self.visible_questions()
        for text in live.values():
            seen = self._norm(text)
            for qid, w in self.wording.items():
                if not w:
                    continue
                want = self._norm(w)
                if (seen == want or seen.startswith(want[:40])) and \
                        qid not in self.seen:
                    self.seen.append(qid)

    def was_seen(self, canonical_question: str) -> bool:
        # A sub-question is not a question in its own right. Asking whether
        # Q4_SQ001 appeared means asking whether Q4 appeared, because the
        # options of a tick-box question are not separately visible things.
        base = canonical_question.split("_")[0]
        return base in self.seen

    def text_ever_contained(self, wanted: str) -> bool:
        want = wanted.casefold()
        return any(want in t.casefold() for t in self.seen_text)

    def came_after(self, first: str, second: str) -> bool:
        if first not in self.seen or second not in self.seen:
            return False
        return self.seen.index(second) > self.seen.index(first)

    def locate(self, canonical_question: str, sub: str = "") -> str | None:
        """The live field for one of Agent 3's questions.

        Returns the base field. A sub-question suffix is resolved separately,
        because LimeSurvey does not join the two the way Agent 3 writes them.
        """
        wanted = self._norm(self.wording.get(canonical_question, ""))
        if not wanted:
            return None
        for live, text in self.visible_questions().items():
            seen = self._norm(text)
            if seen == wanted or seen.startswith(wanted[:40]):
                return live
        return None

    def _tick(self, el) -> None:
        """Select a radio or tick box that may not be clickable directly.

        LimeSurvey hides the real input and styles the label on top of it.
        Playwright refuses to click something it judges invisible, and waits
        for it to become actionable instead, which for a permanently hidden
        input means waiting until the timeout. That wait is what made a run
        appear to hang.

        So: the ordinary click first, then the label, then setting the value
        directly and telling the page it changed. The last route is a last
        resort because it bypasses whatever the page would have done on a real
        click, but an unticked box fails the test for the wrong reason.
        """
        try:
            el.check(timeout=2_000)
            return
        except Exception:
            pass

        ident = el.get_attribute("id")
        if ident:
            label = self.page.query_selector(f'label[for="{ident}"]')
            if label is not None:
                try:
                    label.click(timeout=2_000)
                    return
                except Exception:
                    pass

        try:
            el.click(force=True, timeout=2_000)
            return
        except Exception:
            pass

        el.evaluate("e => { e.checked = true; "
                    "e.dispatchEvent(new Event('change', {bubbles:true})); "
                    "e.dispatchEvent(new Event('click', {bubbles:true})); }")

    def _label_of(self, el) -> str:
        """The words printed beside a tick box."""
        ident = el.get_attribute("id")
        if ident:
            lab = self.page.query_selector(f'label[for="{ident}"]')
            if lab:
                return " ".join((lab.inner_text() or "").split())
        handle = el.evaluate_handle("e => e.closest('li') || e.parentElement")
        try:
            return " ".join((handle.as_element().inner_text() or "").split())
        except Exception:
            return ""

    def find_choice(self, live: str, sub: str, wanted_label: str = ""):
        """The tick box for one option of a multi-select.

        LimeSurvey renumbers sub-questions on import just as it renumbers
        questions, so Agent 3's Q4_SQ001 is served as Q12_S17. Neither half of
        that identifier survives, which is why the label is matched instead:
        the words beside the box are the one thing that does survive.

        The identifier is still tried first, in case nothing was renumbered.
        """
        for selector in (f'input[name="{live}_{sub}"]',
                         f'input[name="{live}{sub}"]',
                         f'input[id*="{live}{sub}"]'):
            el = self.page.query_selector(selector)
            if el is not None:
                return el, selector

        if wanted_label:
            want = self._norm(wanted_label)
            for el in self.page.query_selector_all(
                    f'input[type="checkbox"][name^="{live}"]'):
                if self._norm(self._label_of(el)).startswith(want[:32]):
                    return el, f"matched the label {wanted_label!r}"

        return None, self.tick_boxes_on_page()

    def tick_boxes_on_page(self) -> list[str]:
        out = []
        for el in self.page.query_selector_all('input[type="checkbox"]')[:12]:
            name = el.get_attribute("name") or "?"
            out.append(f"{name} ({self._label_of(el)[:24]})")
        return out

    def on_end_page(self) -> bool:
        return not self.page.query_selector(
            '#ls-button-submit, button[value="movenext"], '
            'input[value="movenext"]')

    def page_text(self) -> str:
        try:
            return " ".join((self.page.inner_text("body") or "").split())
        except Exception:                                      # pragma: no cover
            return ""

    def error_showing(self, live_field: str | None = None) -> bool:
        if live_field:
            near = self.page.query_selector(
                f'#question{live_field} .text-danger, '
                f'#question{live_field} .has-error, '
                f'[id*="{live_field}"] .ls-em-error:not(.ls-em-success)')
            if near:
                return True
        return bool(self.page.query_selector(
            '.has-error, .alert-danger, .ls-em-error:not(.ls-em-success)'))

    # -- moving -------------------------------------------------------------

    def start(self) -> None:
        self.page.goto(f"{self.base}/index.php/{self.sid}",
                       wait_until="domcontentloaded")
        # LimeSurvey shows a welcome screen before the first question. Agent 3
        # knows nothing about it, and rightly so: it belongs to the tool, not
        # the questionnaire.
        for _ in range(3):
            if self.visible_questions() or self.on_end_page():
                self.note_visible()
                return
            self.next()

    def next(self) -> None:
        """Move forward, and only forward.

        The previous-page control sits beside the next one and matches some of
        the same selectors. Clicking it sends the respondent backwards, and a
        test that alternates forwards and backwards never finishes.
        """
        for selector in ('button[value="movenext"]',
                         'input[value="movenext"]',
                         'button[value="movesubmit"]',
                         '#ls-button-submit'):
            button = self.page.query_selector(selector)
            if button is None:
                continue
            if (button.get_attribute("value") or "") == "moveprev":
                continue
            button.click()
            self._cache = None
            self.page.wait_for_load_state("domcontentloaded")
            self.note_visible()
            return

    # -- filling ------------------------------------------------------------

    def fill(self, live: str, value: Any, kind: str) -> str:
        """Do what a respondent would do, and say what was done."""
        if kind == "answer_code":
            el = self.page.query_selector(
                f'input[name="{live}"][value="{value}"]')
            if el is None:
                raise LookupError(f'no option {value!r} on {live}')
            label = self._label_for(live, str(value))
            self._tick(el)
            return f"chose {label!r}"

        if kind == "checkbox":
            el = self.page.query_selector(f'input[name="{live}"]')
            if el is None:
                raise LookupError(
                    f"no tick box {live}. The page offers "
                    f"{self.tick_boxes_on_page()}")
            self._tick(el)
            return "ticked it"

        if kind in ("text", "number"):
            el = (self.page.query_selector(f'textarea[name="{live}"]')
                  or self.page.query_selector(f'input[name="{live}"]'))
            if el is None:
                raise LookupError(f'no text field {live}')
            shown = str(value)
            try:
                el.fill(shown, timeout=3_000)
            except Exception:
                el.evaluate(
                    "(e, v) => { e.value = v; "
                    "e.dispatchEvent(new Event('input', {bubbles:true})); "
                    "e.dispatchEvent(new Event('change', {bubbles:true})); }",
                    shown)
            if not shown.strip() and shown:
                return f"typed {len(shown)} space{'s' if len(shown) != 1 else ''}"
            if len(shown) > 40:
                return f"typed a {len(shown)}-character answer"
            return f"typed {shown!r}"

        raise LookupError(f"no way to fill a {kind!r} field")

    def _label_for(self, live: str, value: str) -> str:
        el = self.page.query_selector(f'#answer-label-{live}{value}')
        if el:
            return " ".join((el.inner_text() or "").split())
        el = self.page.query_selector(
            f'label[for="answer{live}{value}"]')
        return " ".join((el.inner_text() or "").split()) if el else value


# ---------------------------------------------------------------- one test

def run_test(bot: Bot, test: dict, pause: int, budget: float = 45.0) -> Result:
    import time
    started = time.time()

    def out_of_time() -> bool:
        return (time.time() - started) > budget

    res = Result(test_id=test["test_id"], title=test.get("title", ""),
                 dimension=test.get("dimension", ""),
                 provisional=test.get("provisional_semantics", []))

    if test.get("campaign"):
        res.status = SKIPPED
        res.blocked_reason = ("needs several respondents, so it is not a "
                              "single journey")
        return res

    # Which question is this test about. Named for the report, so a reader can
    # scan by question rather than by test id.
    # The question under test is the one the assertions talk about, not the
    # last one the journey happened to fill. An earlier version took the last
    # step, so a test about Q1 was filed under Q7 and the report read as
    # nonsense.
    for a in test.get("assertions", []):
        if a.get("canonical"):
            res.question = str(a["canonical"]).split("/")[0]
            break
    if not res.question:
        for step in reversed(test.get("steps", [])):
            if step.get("canonical"):
                res.question = str(step["canonical"]).split("/")[0]
                break

    advanced: bool | None = None
    stuck = 0

    try:
        bot.start()
        for step in test.get("steps", []):
            n = step.get("step", 0)

            if out_of_time():
                res.status = BLOCKED
                res.blocked_reason = (
                    f"gave up after {budget:.0f} seconds at step {n}. The "
                    f"survey was not moving on, so the test was stopped rather "
                    f"than left running")
                res.seconds = round(time.time() - started, 2)
                return res

            if step.get("action") == "submit_page":
                # Whether the survey moved on is decided by which questions
                # are now on screen, not by whether the page text changed.
                # A refusal redisplays the same page with an error message
                # added, which changes the text while leaving the respondent
                # exactly where they were. Reading that as progress turned
                # every correct refusal into a reported failure.
                before = set(bot.visible_questions()) or {bot.page.url}
                bot.next()
                after = set(bot.visible_questions()) or {bot.page.url}
                advanced = before != after
                # "Next" is per page, not per question. LimeSurvey puts a
                # whole group on one page, so this sends every answer on that
                # page at once. Saying "clicked Next" after a single question
                # reads as though the survey advances question by question,
                # which it does not.
                on_page = ", ".join(bot.seen[-8:]) or "the page"
                res.actions.append(Action(
                    n, "", "submitted the page",
                    f"one Next button sends every question on the page at "
                    f"once. " + ("the survey moved on to the next page"
                                 if advanced else
                                 "the survey stayed on the same page")))
                if not advanced:
                    stuck += 1
                    # Clicking Next into a page that refuses to move is
                    # sometimes the point of a test, so one is expected. Two in
                    # a row means the journey cannot continue, and carrying on
                    # would just click the same button until the budget ran out.
                    if stuck >= 2:
                        res.blocked_reason = (
                            f"the survey would not move past step {n}, even "
                            f"after two attempts")
                        break
                else:
                    stuck = 0
                continue

            canonical = str(step.get("canonical") or "").split("/")[0]
            field_name = step.get("field_name") or ""
            _, _, sub = field_name.partition("_")

            if step.get("value_kind") == "blank":
                res.actions.append(Action(
                    n, canonical, "left it blank",
                    "deliberately answered nothing"))
                continue

            live = bot.locate(canonical)
            if live is None:
                res.status = BLOCKED
                res.blocked_reason = (
                    f"{canonical} was not on the page when the test reached "
                    f"step {n}. Agent 3 compiled it as {field_name}")
                res.seconds = round(time.time() - started, 2)
                return res

            target = live
            if sub and step.get("value_kind") == "checkbox":
                option_id = str(step.get("canonical") or "").partition("/")[2]
                wanted_label = bot.options.get(canonical, {}).get(option_id, "")
                el, how = bot.find_choice(live, sub, wanted_label)
                if el is None:
                    res.status = BLOCKED
                    res.blocked_reason = (
                        f"{canonical} is on the page as {live}, but its option "
                        f"{wanted_label or sub!r} was not found. The page "
                        f"offers {how}")
                    res.seconds = round(time.time() - started, 2)
                    return res
                target = el.get_attribute("name") or live
                ticked_label = bot._label_of(el)

            try:
                did = bot.fill(target, step.get("value"),
                               step.get("value_kind") or "text")
            except LookupError as exc:
                res.status = BLOCKED
                res.blocked_reason = f"could not answer {canonical}: {exc}"
                res.seconds = round(time.time() - started, 2)
                return res

            res.actions.append(Action(
                n, canonical, did,
                f"LimeSurvey calls this question {live}"))
            if pause:
                bot.page.wait_for_timeout(pause)

    except Exception as exc:                                   # pragma: no cover
        res.status = BLOCKED
        res.blocked_reason = f"{type(exc).__name__}: {exc}"
        res.seconds = round(time.time() - started, 2)
        return res

    if res.blocked_reason:
        res.status = BLOCKED
        res.seconds = round(time.time() - started, 2)
        return res

    for a in test.get("assertions", []):
        res.checks.append(observe(bot, a, advanced))

    verdicts = [c.matched for c in res.checks]
    if not verdicts:
        res.status = INCONCLUSIVE
    elif any(v is False for v in verdicts):
        res.status = FAILED
    elif any(v is True for v in verdicts):
        res.status = PASSED
    else:
        res.status = INCONCLUSIVE

    res.seconds = round(time.time() - started, 2)
    return res


def observe(bot: Bot, a: dict, advanced: bool | None) -> Check:
    """Compare one expectation against what the bot saw.

    Each branch writes two sentences: what should have happened and what did.
    Those are what the report shows, because a reader needs to know that "Q1
    never appeared on screen" rather than that field_present came back False.
    """
    kind = a.get("kind")
    expected = a.get("expected")
    canonical = str(a.get("canonical") or a.get("field_name") or "")
    base = canonical.split("/")[0]
    live = bot.locate(base)
    text = bot.page_text()
    met = ", ".join(bot.seen) or "none at all"

    def check(matched, should, actually, why="") -> Check:
        return Check(kind, base, expected, actually, matched, why,
                     should, actually)

    if kind == "field_present":
        want = expected if isinstance(expected, bool) else True
        seen = bot.was_seen(base) or live is not None
        if want:
            return check(seen is True,
                         f"{base} should have appeared on screen, so the "
                         f"respondent could answer it",
                         f"{base} did appear" if seen else
                         f"{base} never appeared. The respondent was shown: "
                         f"{met}")
        return check(seen is False,
                     f"{base} should NOT have appeared, because the "
                     f"respondent's answers should have hidden it",
                     f"{base} stayed hidden, as it should" if not seen else
                     f"{base} appeared anyway, when it should have been hidden")

    if kind == "next_field_present":
        follower = str(expected) if not isinstance(expected, bool) else base
        seen = bot.was_seen(follower)
        return check(seen is True,
                     f"after answering, the next question the respondent sees "
                     f"should be {follower}",
                     f"{follower} did come next" if seen else
                     f"{follower} never appeared. The respondent was shown: "
                     f"{met}")

    if kind == "page_advances":
        return check(advanced is True,
                     "the survey should accept the answer and move to the "
                     "next page",
                     "it moved on, as it should" if advanced else
                     "it stayed on the same page, refusing to move")

    if kind == "page_does_not_advance":
        return check(advanced is False,
                     "the survey should refuse to move on, because the answer "
                     "breaks a rule the questionnaire sets",
                     "it refused to move on, as it should"
                     if advanced is False else
                     "it accepted the answer and moved on, when it should "
                     "have stopped the respondent")

    if kind == "error_shown_on_question":
        seen = bot.error_showing(live)
        return check(seen is True,
                     f"an error message should appear on {base}, telling the "
                     f"respondent what is wrong",
                     "an error message appeared" if seen else
                     "no error message appeared anywhere on the page")

    if kind == "survey_completed":
        seen = bot.on_end_page() and "do not qualify" not in text.casefold()
        return check(seen is True,
                     "the respondent should reach the end of the survey and "
                     "be thanked",
                     "they reached the completion page" if seen else
                     f"they did not. The page says: {text[:90]!r}")

    if kind == "not_on_end_page":
        seen = not bot.on_end_page()
        return check(seen is True,
                     "the respondent should still be travelling through the "
                     "survey at this point, not finished",
                     "they were still answering questions" if seen else
                     "the survey had already ended")

    if kind == "group_suppressed":
        seen = not bot.visible_questions()
        return check(seen is True,
                     "no question from the main section should appear, "
                     "because this respondent was screened out",
                     "no main-section question appeared" if seen else
                     "questions appeared even though the respondent should "
                     "have been screened out")

    if kind in ("end_page_message", "end_page_message_non_discriminating"):
        want = " ".join(re.sub(r"<[^>]+>", " ", str(expected or "")).split())
        seen = want.casefold() in text.casefold() if want else False
        if kind.endswith("non_discriminating"):
            return Check(kind, base, want, text[:120], None,
                         "cannot be judged", 
                         f"the final page should say: {want[:70]!r}",
                         f"it said: {text[:70]!r}. Several screen-outs in this "
                         f"survey use identical wording, so seeing it cannot "
                         f"prove which one fired")
        return check(seen is True,
                     f"the final page should say: {want[:80]!r}",
                     f"it said exactly that" if seen else
                     f"it said something else: {text[:80]!r}")

    if kind == "question_text_contains":
        want = str(expected or "")
        # Read from the pages passed through, not the page the respondent
        # finished on. A question's wording can only be seen while that
        # question is on screen, and by the end of a journey that is a
        # thank-you page.
        seen = bot.text_ever_contained(want)
        return check(seen is True,
                     f"the question wording should include the respondent's "
                     f"earlier answer, {want[:50]!r}",
                     "it did, on the page where that question appeared"
                     if seen else
                     f"it never did. The respondent was shown: "
                     f"{', '.join(bot.seen) or 'nothing'}")

    return Check(kind, base, expected, None, None,
                 "not checked",
                 f"something the questionnaire claims about {base}",
                 f"this runner cannot observe {kind!r} yet, so the test proves "
                 f"nothing either way")


# ---------------------------------------------------------------- the report

def write_workbook(path: Path, results: list[Result], survey: str,
                   sid: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    INK, LINE = "1B1832", "C7C2DC"
    FILL = {PASSED: "DAEDEA", FAILED: "F8E4E6", BLOCKED: "FAEBDE",
            INCONCLUSIVE: "E4E1F7", SKIPPED: "EFEFEF"}
    FONT = {PASSED: "0F766E", FAILED: "A32C36", BLOCKED: "9C4709",
            INCONCLUSIVE: "4338A8", SKIPPED: "635E7E"}
    thin = Side(style="thin", color=LINE)
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(vertical="top", wrap_text=True)

    wb = Workbook()

    # -- summary -----------------------------------------------------------
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"Agent 4 run: {survey}"
    ws["A1"].font = Font(name="Calibri", size=15, bold=True, color=INK)
    ws["A2"] = (f"Survey id {sid}, run {datetime.now().strftime('%d %b %Y %H:%M')}. "
                f"The bot filled the survey as a respondent would and recorded "
                f"what it saw. What a failure means is Agent 5's call.")
    ws["A2"].font = Font(name="Calibri", size=10, italic=True, color="4A4566")
    ws.merge_cells("A2:E2")

    counts = {s: sum(1 for r in results if r.status == s) for s in STATUS_ORDER}
    MEANING = {
        PASSED: "Every check was observed and matched what Agent 3 expected.",
        FAILED: "A check was observed and did not match. Worth investigating.",
        BLOCKED: "The journey could not finish, so nothing was checked. This "
                 "says nothing about the survey.",
        INCONCLUSIVE: "The check could not be observed at all.",
        SKIPPED: "Needs several respondents, so not run as a single journey.",
    }
    for i, h in enumerate(("Outcome", "Tests", "What it means"), 1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=INK)
    row = 5
    for status in STATUS_ORDER:
        if not counts[status]:
            continue
        ws.cell(row=row, column=1, value=status).font = Font(
            name="Calibri", size=11, bold=True, color=FONT[status])
        ws.cell(row=row, column=1).fill = PatternFill(
            "solid", fgColor=FILL[status])
        ws.cell(row=row, column=2, value=counts[status]).font = Font(
            name="Consolas", size=11, bold=True)
        ws.cell(row=row, column=3, value=MEANING[status]).alignment = wrap
        ws.row_dimensions[row].height = 30
        row += 1
    for col, w in zip("ABC", (18, 8, 78)):
        ws.column_dimensions[col].width = w

    # -- one row per test ---------------------------------------------------
    ws = wb.create_sheet("Test results")
    head = ["Order", "Test Case ID", "Question", "What was being tested",
            "Outcome", "What the bot did, step by step",
            "What should have happened", "What the bot saw",
            "Why it failed", "Notes"]
    width = [7, 13, 10, 44, 13, 52, 42, 40, 44, 28]
    for i, h in enumerate(head, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=INK)
        c.alignment = Alignment(vertical="bottom", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width[i - 1]

    # Questionnaire order, the same order Agent 3 lists them in, so a reader
    # can follow one document into the other. Sorting failures to the top
    # made the interesting rows easy to find and made the two reports
    # impossible to read together, which mattered more.
    for r_i, r in enumerate(sorted(results,
                                   key=lambda x: (x.order or 9999, x.test_id)),
                            start=2):
        did = "\n".join(
            f"{a.step}. {a.question + ': ' if a.question else ''}{a.did}"
            for a in r.actions) or "nothing, the test did not start"
        expected = "\n".join(
            f"{i}. {c.should}" for i, c in enumerate(r.checks, 1)) or "-"
        saw = "\n".join(
            f"{i}. {c.actually}" for i, c in enumerate(r.checks, 1)) or "-"
        why = "\n".join(c.actually for c in r.checks if c.matched is False)
        if r.status == BLOCKED:
            why = r.blocked_reason
        if r.status == SKIPPED:
            why = r.blocked_reason
        notes = ("leans on an unconfirmed reading: "
                 + ", ".join(r.provisional)) if r.provisional else ""

        values = [r.order or "", r.case_id or r.test_id,
                  r.question or "whole survey", r.title, r.status,
                  did, expected, saw, why or "-", notes or "-"]
        for i, v in enumerate(values, 1):
            c = ws.cell(row=r_i, column=i, value=v)
            c.font = Font(name="Calibri", size=10)
            c.border = box
            c.alignment = wrap
        ws.cell(row=r_i, column=5).font = Font(
            name="Calibri", size=10, bold=True, color=FONT[r.status])
        ws.cell(row=r_i, column=5).fill = PatternFill(
            "solid", fgColor=FILL[r.status])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:J{len(results) + 1}"

    # A reader who opens this tab cold needs to know two things before the
    # rows make sense: that every test is here, not only the failures, and
    # that the question names come from the questionnaire while LimeSurvey
    # uses its own.
    note = ws.cell(row=len(results) + 3, column=1, value=(
        "Every test is listed here, not only the failures, in the same order "
        "and under the same Test Case IDs as Agent 3's workbook, so the two "
        "can be read side by side. Filter the Outcome column to see the "
        "failures on their own.\n"
        "Question names such as S1 and Q4 are the questionnaire's own. "
        "LimeSurvey renames them internally when a survey is imported, and "
        "where that name is useful for finding the field in the admin it is "
        "noted in the step detail."))
    note.font = Font(name="Calibri", size=10, italic=True, color="4A4566")
    note.alignment = wrap
    ws.merge_cells(start_row=len(results) + 3, start_column=1,
                   end_row=len(results) + 3, end_column=10)
    ws.row_dimensions[len(results) + 3].height = 46

    # -- every action, for anyone who wants the detail ---------------------
    ws = wb.create_sheet("Every action")
    for i, h in enumerate(("Test Case ID", "Step", "Question",
                           "What the bot did", "Where on the survey"), 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=INK)
    for col, w in zip("ABCDE", (14, 7, 12, 52, 34)):
        ws.column_dimensions[col].width = w
    row = 2
    for r in results:
        for a in r.actions:
            for i, v in enumerate((r.case_id or r.test_id, a.step, a.question,
                                   a.did, a.detail), 1):
                cell = ws.cell(row=row, column=i, value=v)
                cell.font = Font(name="Calibri", size=10)
                cell.alignment = wrap
            row += 1
    ws.freeze_panes = "A2"

    wb.save(path)


# ---------------------------------------------------------------- entry point

def _fan_out(args, directory: Path, tests: list, workers: int) -> int:
    """Split the tests across worker processes and put the results back."""
    import time as _time
    started = _time.time()
    print(f"  running {len(tests)} tests across {workers} workers\n",
          flush=True)

    shard_dir = directory / "agent4" / "_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    for stale in shard_dir.glob("*.json"):
        stale.unlink()

    running = []
    for i in range(workers):
        command = [sys.executable, "-u", __file__, str(directory),
                   "--sid", args.sid, "--base", args.base,
                   "--shard", f"{i}/{workers}",
                   "--budget", str(args.budget),
                   "--shard-out", str(shard_dir / f"{i}.json")]
        running.append(subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1))

    # Every worker's output has to be read as it arrives. Draining one pipe
    # at a time lets the others fill their buffer and block, which silently
    # turns four workers back into one: the run looks stalled and takes no
    # less time than before.
    lines_in: "queue.Queue[str | None]" = queue.Queue()

    def pump(process):
        for line in process.stdout:
            lines_in.put(line.rstrip())
        process.wait()
        lines_in.put(None)

    readers = [threading.Thread(target=pump, args=(p,), daemon=True)
               for p in running]
    for r in readers:
        r.start()

    done = 0
    finished = 0
    while finished < len(running):
        text = lines_in.get()
        if text is None:
            finished += 1
            continue
        bare = text.strip()
        if bare.startswith("##DONE "):
            done += 1
            print(f"  [{done:>3}/{len(tests)}] {bare[7:]}", flush=True)
    for p in running:
        p.wait()

    # A worker that fails has to say so. The parent prints only the lines it
    # recognises, so without this a crash looks like a run that found
    # nothing at all.
    broken = [i for i, p in enumerate(running) if p.returncode not in (0, None)]
    if broken:
        print(f"\n  {len(broken)} of {len(running)} workers failed. "
              f"Re-run one on its own to see why:", flush=True)
        print(f"    python -m src.agents.respondent_bot.run_browser "
              f"{directory} --sid {args.sid} --workers 1", flush=True)

    merged: list = []
    for i in range(workers):
        piece = shard_dir / f"{i}.json"
        if piece.exists():
            merged += json.loads(piece.read_text(encoding="utf-8"))["results"]
            piece.unlink()
    try:
        shard_dir.rmdir()
    except OSError:
        pass

    counts: dict = {}
    for r in merged:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    took = _time.time() - started

    print(f"\n  {len(merged)} tests in {took:.0f} seconds")
    for status in STATUS_ORDER:
        if counts.get(status):
            print(f"    {status:<14} {counts[status]:>4}")

    dest = directory / "agent4"
    dest.mkdir(exist_ok=True)
    payload = {"survey": directory.name, "survey_id": args.sid,
               "run_at": datetime.now(timezone.utc).isoformat(),
               "counts": counts, "results": merged}
    (dest / "agent4_results.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # Rebuilt field by field rather than by keyword, so a row written by an
    # older worker, or one missing a field, still merges instead of taking
    # the whole run down at the last step.
    rebuilt = []
    for raw in merged:
        r = Result(test_id=raw.get("test_id", ""), title=raw.get("title", ""),
                   dimension=raw.get("dimension", ""))
        for name in Result.__dataclass_fields__:
            if name in raw and name not in ("actions", "checks"):
                setattr(r, name, raw[name])
        r.actions = [Action(**{k: v for k, v in a.items()
                               if k in Action.__dataclass_fields__})
                     for a in raw.get("actions", [])]
        r.checks = [Check(**{k: v for k, v in c.items()
                             if k in Check.__dataclass_fields__})
                    for c in raw.get("checks", [])]
        rebuilt.append(r)
    book = dest / "agent4_results.xlsx"
    try:
        write_workbook(book, rebuilt, directory.name, args.sid)
    except PermissionError:
        book = dest / f"agent4_results_{datetime.now():%H%M%S}.xlsx"
        write_workbook(book, rebuilt, directory.name, args.sid)
    print(f"\n  wrote {book}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Drive a browser through Agent 3's tests.")
    ap.add_argument("survey_dir")
    ap.add_argument("--sid", required=True)
    # Inside a container localhost is the container, so the address is
    # taken from the environment when one is set.
    ap.add_argument("--base",
                    default=os.environ.get("LIMESURVEY_BASE",
                                           "http://localhost:8080"))
    ap.add_argument("--headed", action="store_true",
                    help="show the browser, for demonstrating")
    ap.add_argument("--slow", type=int, default=0,
                    help="milliseconds to pause after each answer, so the run "
                         "can be followed")
    ap.add_argument("--workers", type=int, default=0,
                    help="run this many tests at once. 0 picks a sensible "
                         "number: several when running in the background, "
                         "one when you are watching a browser.")
    ap.add_argument("--shard", default="",
                    help="internal: run one slice of the tests, as i/n")
    ap.add_argument("--shard-out", default="",
                    help="internal: where a worker writes its slice")
    ap.add_argument("--budget", type=float, default=45.0,
                    help="seconds to allow one test before giving up on it")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("This needs Playwright.\n"
              "  pip install playwright\n"
              "  playwright install chromium")
        return 1

    directory = Path(args.survey_dir)
    package = directory / "agent3" / "agent3_executable_tests.json"
    if not package.exists():
        print(f"no test package at {package}. Run Agent 3 first.")
        return 1

    wording: dict[str, str] = {}
    options: dict[str, dict[str, str]] = {}
    canonical = directory / "part2_canonical.json"
    if canonical.exists():
        doc = json.loads(canonical.read_text(encoding="utf-8"))
        for q in (doc.get("content") or doc).get("questions", []):
            wording[q["question_id"]] = q.get("wording", "")
            options[q["question_id"]] = {
                o["option_id"]: o.get("label", "")
                for o in (q.get("options") or [])}
    else:
        print(f"  warning: {canonical.name} is missing, so the bot cannot "
              f"match a renumbered field by its wording")

    index: dict[str, dict] = {}
    index_file = directory / "agent3" / "agent3_test_case_index.json"
    if index_file.exists():
        for row in json.loads(index_file.read_text(encoding="utf-8"))["tests"]:
            if row.get("executable_id"):
                index[row["executable_id"]] = row
    else:
        print("  note: no test case index from Agent 3, so this report will "
              "use internal ids and its own order")

    tests = [t for t in json.loads(package.read_text(encoding="utf-8"))
             ["content"]["tests"] if t.get("executable")]
    tests.sort(key=lambda t: index.get(t["test_id"], {}).get("order", 9999))
    if args.only:
        tests = [t for t in tests if t["test_id"] == args.only]
    if args.limit:
        tests = tests[:args.limit]
    if not tests:
        print("no tests to run")
        return 1

    # ---- run several at once ------------------------------------------
    # Nearly all of a test's time is spent waiting for a page, which is idle
    # time. Running a few journeys side by side recovers it. Each worker is
    # a separate process running this same code on a slice of the tests, so
    # the thing being parallelised is the part already known to work.
    # More workers is faster only while the waiting dominates. Each one is a
    # browser, so beyond roughly twice the processor count the machine
    # becomes the limit. Capped at the number of tests, since an idle worker
    # costs a browser launch and returns nothing.
    default = 1 if args.headed else min(8, max(2, (os.cpu_count() or 4)))
    workers = min(args.workers or default, len(tests), 24)
    if workers > 1 and not args.shard and not args.only:
        return _fan_out(args, directory, tests, workers)

    if args.shard:
        # Named apart from "index", which already holds Agent 3's test-case
        # index. Reusing the name overwrote it with an integer and every
        # worker died on the next line, silently, because the parent was
        # discarding whatever the children printed.
        slice_no, slice_count = (int(x) for x in args.shard.split("/"))
        tests = [t for n, t in enumerate(tests) if n % slice_count == slice_no]
        if not tests:
            print(json.dumps({"counts": {}, "results": []}))
            return 0

    results: list[Result] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed,
                                     slow_mo=args.slow if args.headed else 0)
        for i, t in enumerate(tests, 1):
            label = index.get(t["test_id"], {}).get("test_case_id") \
                or t["test_id"]
            print(f"  [{i:>3}/{len(tests)}] {label:<10} "
                  f"{t.get('title','')[:54]}", flush=True)
            # A fresh context per test, so one respondent's session cannot
            # leak into the next.
            context = browser.new_context()
            page = context.new_page()
            # Without this a single unresponsive page holds the whole run.
            page.set_default_timeout(10_000)
            page.set_default_navigation_timeout(15_000)
            bot = Bot(page, args.base, args.sid, wording, options)
            r = run_test(bot, t, args.slow, args.budget)
            row = index.get(t["test_id"], {})
            r.case_id = row.get("test_case_id", "")
            r.order = row.get("order", 0)
            if row.get("question"):
                r.question = row["question"]
            print(f"          {r.status}"
                  + (f"  {r.blocked_reason[:64]}" if r.blocked_reason else ""),
                  flush=True)
            if args.shard_out:
                # One unambiguous line per finished test, for the parent.
                print(f"##DONE {r.status} {label}", flush=True)
            results.append(r)
            context.close()
        browser.close()

    counts = {s: sum(1 for r in results if r.status == s) for s in STATUS_ORDER}
    print()
    print(f"  {len(results)} tests")
    for s in STATUS_ORDER:
        if counts[s]:
            print(f"    {s:<14} {counts[s]:>4}")

    for r in results:
        if r.status == FAILED:
            print(f"\n  FAILED  {r.test_id}  {r.title[:60]}")
            for c in r.checks:
                if c.matched is False:
                    print(f"      should: {c.should}")
                    print(f"      but   : {c.actually}")
            last = [a for a in r.actions][-3:]
            for a in last:
                print(f"      did: {a.step}. "
                      f"{a.question + ': ' if a.question else ''}{a.did}")
        elif r.status in (BLOCKED, SKIPPED) and r.blocked_reason:
            print(f"\n  {r.status}  {r.test_id}  {r.blocked_reason[:110]}")

    if args.shard_out:
        # A worker hands its slice back and writes nothing else. The parent
        # merges them and produces the single report.
        Path(args.shard_out).write_text(json.dumps(
            {"results": [asdict(r) for r in results]}, indent=2,
            default=str), encoding="utf-8")
        return 0

    dest = directory / "agent4"
    dest.mkdir(exist_ok=True)
    book = dest / "agent4_results.xlsx"
    try:
        write_workbook(book, results, directory.name, args.sid)
    except PermissionError:
        # Almost always the previous report still open in Excel. Losing a
        # finished run to that would be absurd, so write beside it.
        book = dest / f"agent4_results_{datetime.now():%H%M%S}.xlsx"
        write_workbook(book, results, directory.name, args.sid)
        print(f"\n  the usual file was open in Excel, so this run went to "
              f"{book.name}")
    (dest / "agent4_results.json").write_text(
        json.dumps({"survey": directory.name, "survey_id": args.sid,
                    "run_at": datetime.now(timezone.utc).isoformat(),
                    "counts": counts,
                    "results": [asdict(r) for r in results]},
                   indent=2, default=str), encoding="utf-8")
    print(f"\n  wrote {book}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
