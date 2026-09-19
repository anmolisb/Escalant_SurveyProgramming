"""Agent 4 smoke test — proves the core wiring works end to end.

  python src/agents/respondent_bot/smoke_test.py --sid 123456

This does NOT yet read Agent 3's executable test files (see run.py's docstring
for that fuller version). What it proves instead, deliberately kept small:

    1. Playwright can open a real, live LimeSurvey survey in a browser
    2. it can find whatever the first question's input field is (text or
       single-choice), fill it in automatically
    3. it can click "Next"
    4. it can confirm the page actually moved forward

That's the "Agent 4 completes one full survey question automatically, end
to end" milestone. It intentionally does not hardcode any field names —
it looks at whatever's on the page, so it works against S01 or any other
survey without needing a pre-generated test file first.
"""

from __future__ import annotations

import argparse
import sys

from playwright.sync_api import sync_playwright


def run(base_url: str, sid: int, headless: bool) -> bool:
    url = f"{base_url.rstrip('/')}/index.php/survey/index/sid/{sid}/lang/en"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        print(f"Opening {url} ...")
        page.goto(url)
        page.wait_for_load_state("networkidle")

        # LimeSurvey often shows a "Welcome" screen with just a Next/Start
        # button before question 1. Click through it if present.
        start_button = page.locator(
            "input[value='Start']:visible, input[value='Next']:visible, "
            "a:has-text('Start survey'):visible, "
            "input.ls-move-submit-btn:visible, button:has-text('Next'):visible"
        ).first
        if start_button.count() > 0:
            print("Found a welcome screen. Clicking Next/Start...")
            start_button.click()
            page.wait_for_load_state("networkidle")

        page_before = page.inner_text("body")

        # Look for a free-text field first (input[type=text] or textarea);
        # fall back to a radio button (single-choice question) if none found.
        text_input = page.locator("input[type='text']:visible, textarea:visible").first
        radio_input = page.locator("input[type='radio']:visible").first

        if text_input.count() > 0:
            print("Found a free-text question. Filling it in...")
            text_input.fill("Smoke test answer")
        elif radio_input.count() > 0:
            print("Found a single-choice question. Selecting the first option...")
            radio_input.check()
        else:
            print("Could not find a text field or radio button on the first "
                  "page. Take a screenshot (see below) and check the survey "
                  "actually has a question on its first page.")
            page.screenshot(path="smoke_test_failure.png", full_page=True)
            browser.close()
            return False

        print("Clicking Next...")
        page.click("input[name='move']:visible, "
                   "button[type='submit']:visible, "
                   "input.ls-move-submit-btn:visible")
        page.wait_for_load_state("networkidle")

        page_after = page.inner_text("body")
        page.screenshot(path="smoke_test_result.png", full_page=True)
        browser.close()

    moved_forward = page_after != page_before
    if moved_forward:
        print("\nSUCCESS: the page changed after submitting an answer — "
              "Agent 4 completed one question end to end.")
        print("Screenshot saved to smoke_test_result.png")
    else:
        print("\nThe page did not appear to change after clicking Next. "
              "This usually means the answer wasn't accepted (e.g. a "
              "required field was missed). Check smoke_test_result.png.")

    return moved_forward


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--sid", type=int, required=True,
                         help="Survey ID from LimeSurvey admin, e.g. 123456")
    parser.add_argument("--headed", action="store_true",
                         help="Show the browser window instead of running invisibly")
    args = parser.parse_args()

    ok = run(args.base_url, args.sid, headless=not args.headed)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
