"""Agent 4 — complete an entire survey automatically, end to end."""

from __future__ import annotations

import argparse
from playwright.sync_api import sync_playwright

MAX_PAGES = 30


def survey_url(base_url: str, sid: int) -> str:
    return f"{base_url.rstrip('/')}/index.php/survey/index/sid/{sid}/lang/en"


def page_is_finished(page) -> bool:
    has_move_button = page.locator(
        "input[name='move']:visible, input.ls-move-submit-btn:visible, "
        "button[type='submit']:visible, button:has-text('Next'):visible, "
        "button:has-text('Submit'):visible"
    ).count() > 0
    if has_move_button:
        return False
    text = page.inner_text("body").lower()
    return "thank you" in text or "survey has been completed" in text or not has_move_button


def _click_via_label_or_input(page, input_locator, force_check: bool):
    input_id = input_locator.get_attribute("id")
    if input_id:
        label = page.locator(f"label[for='{input_id}']")
        if label.count() > 0:
            label.first.click(force=True)
            page.wait_for_timeout(400)
            return
    if force_check:
        input_locator.check(force=True)
    else:
        input_locator.click(force=True)
    page.wait_for_timeout(400)


def answer_current_page(page) -> str:
    actions = []

    text_inputs = page.locator("input[type='text']:visible, textarea:visible")
    for i in range(text_inputs.count()):
        text_inputs.nth(i).fill("Automated response")
        actions.append("filled a text field")

    radios = page.locator("input[type='radio']")
    seen_names = set()
    for i in range(radios.count()):
        radio = radios.nth(i)
        name = radio.get_attribute("name")
        if name in seen_names:
            continue
        _click_via_label_or_input(page, radio, force_check=True)
        seen_names.add(name)
        actions.append(f"selected an option for {name}")

    checkboxes = page.locator("input[type='checkbox']")
    for i in range(checkboxes.count()):
        cb = checkboxes.nth(i)
        if not cb.is_checked():
            _click_via_label_or_input(page, cb, force_check=True)
            actions.append("checked a checkbox")

    if not actions:
        print("\n----- DEBUG: current page details -----")
        print("URL:", page.url)
        print("Visible text (first 1500 chars):")
        print(page.inner_text("body")[:1500])
        print("Number of <input> elements on page:", page.locator("input").count())
        print("----- END DEBUG -----\n")
        raise NotImplementedError(
            "No text field, radio button, or checkbox found on this page."
        )

    return "; ".join(actions)


def run(base_url: str, sid: int, headless: bool) -> bool:
    url = survey_url(base_url, sid)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        print(f"Opening {url} ...")
        page.goto(url)
        page.wait_for_load_state("networkidle")

        start_button = page.locator(
            "input[value='Start']:visible, input[value='Next']:visible, "
            "input.ls-move-submit-btn:visible, "
            "button:has-text('Start'):visible, button:has-text('Next'):visible, "
            "a:has-text('Start survey'):visible"
        ).first
        if start_button.count() > 0:
            print("Found a welcome screen. Starting the survey...")
            start_button.click()
            page.wait_for_load_state("networkidle")

        for page_number in range(1, MAX_PAGES + 1):
            print(f"--- Now on page {page_number}, URL: {page.url}")

            if page_is_finished(page):
                print(f"\nSURVEY COMPLETE after {page_number - 1} page(s) of questions.")
                browser.close()
                return True

            try:
                description = answer_current_page(page)
            except NotImplementedError as exc:
                print(f"\nSTOPPED at page {page_number}: {exc}")
                browser.close()
                return False

            print(f"Page {page_number}: {description}")

            page.click("input[name='move']:visible, "
                       "input.ls-move-submit-btn:visible, "
                       "button[type='submit']:visible, "
                       "button:has-text('Next'):visible, "
                       "button:has-text('Submit'):visible")
            page.wait_for_load_state("networkidle")

        print(f"\nSTOPPED: reached the {MAX_PAGES}-page safety limit.")
        browser.close()
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--sid", type=int, required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    ok = run(args.base_url, args.sid, headless=not args.headed)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
