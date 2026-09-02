#!/usr/bin/env python3
"""General application driver: fill a greenhouse application with mock
data and submit. Test-mule tool — mock identity is unmissable.

Usage: .venv/bin/python scripts/drive_application.py <job_url> [--dry-run]
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

RESUME = Path("/tmp/mock-harness-test.pdf")
MOCK_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 120 >>
stream
BT /F1 14 Tf 72 720 Td (MOCK APPLICATION - TEST HARNESS) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
trailer
<< /Size 6 /Root 1 0 R >>
startxref
9
%%EOF"""


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_app_frame(page):
    return next((f for f in page.frames
                 if "greenhouse.io" in f.url
                 and ("job_app" in f.url or "jobs" in f.url)),
                page.main_frame)


def try_fill(form, sel: str, value: str) -> bool:
    loc = form.locator(sel)
    if loc.count() == 0:
        return False
    loc.first.fill(value, timeout=5000)
    return True


def pick_menu_option(page, app, matcher: str) -> bool:
    opts = app.locator(".select__menu .select__option")
    n = opts.count()
    target = next((i for i in range(n)
                   if matcher.lower() in opts.nth(i).inner_text().lower()), None)
    if target is None:
        page.keyboard.press("Escape")
        return False
    opts.nth(target).click()
    return True


def main() -> int:
    job_url = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    resume_path = RESUME
    resume_path.write_bytes(MOCK_PDF)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                        "Gecko/20100101 Firefox/130.0"),
            locale="en-US",
        )
        page = ctx.new_page()
        log(f"opening {job_url}")
        page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        app = find_app_frame(page)
        form = app.locator("#application-form")
        form.wait_for(state="visible", timeout=30000)
        log(f"app frame: {app.url[:80]}")

        # Identity fields (skip absent ones — boards differ).
        identity = {
            "#first_name": "Mocktest",
            "#last_name": "McHarness",
            "#preferred_name": "Mock",
            "#email": "mock.harness@example.com",
            "#phone": "+52 55 1234 5678",
        }
        for sel, val in identity.items():
            if try_fill(form, sel, val):
                log(f"{sel} filled")

        # Phone country if present.
        if form.locator("#country").count():
            form.locator("#country").click()
            pick_menu_option(page, app, "Mexico")
            log("phone country: Mexico")

        # Custom text questions (non-select): fill with a mock marker.
        text_qs = form.locator(
            "input[id^='question_'][class*='input__single-line']")
        for i in range(text_qs.count()):
            el = text_qs.nth(i)
            if not el.input_value().strip():
                el.fill("Mock application from an automated test harness. "
                        "Please disregard.")
        log("custom text questions filled")

        # Custom react-select questions: choose an answer per-question.
        q_inputs = form.locator("input[id^='question_']")
        nq = q_inputs.count()
        log(f"custom question selects: {nq}")
        answered = set()
        for i in range(nq):
            inp = q_inputs.nth(i)
            qid = inp.get_attribute("id")
            if qid in answered:
                continue
            answered.add(qid)
            try:
                inp.click(timeout=5000)
            except Exception:
                continue
            opts = app.locator(".select__menu .select__option")
            if opts.count() == 0:
                continue
            # Log the question and take the least committal option.
            labels = [opts.nth(j).inner_text().strip() for j in range(opts.count())]
            decline = next((t for t in labels
                            if "decline" in t.lower() or "none of the" in t.lower()
                            or "not applicable" in t.lower()
                            or "don't wish" in t.lower()
                            or "do not want" in t.lower()), None)
            choice = decline or labels[0]
            app.locator(".select__menu .select__option",
                        has_text=choice).first.click()
            log(f"{qid}: '{choice}' (of {labels})")

        # Location (City) geo-typeahead (react-select): type, then pick.
        if form.locator("#candidate-location").count():
            form.locator("#candidate-location").click()
            form.locator("#candidate-location").type("Mexico City", delay=80)
            page.wait_for_timeout(2500)
            if not pick_menu_option(page, app, "Mexico City"):
                log("candidate-location: no matching option")
            else:
                log("candidate-location: Mexico City")

        # Generic location field fallback (other boards).
        loc_input = form.locator(
            "input[aria-label*='ocation' i], input[placeholder*='ocation' i]")
        if loc_input.count() and form.locator("#candidate-location").count() == 0:
            loc_input.first.click()
            loc_input.first.type("Mexico City", delay=60)
            page.wait_for_timeout(2500)
            picked = pick_menu_option(page, app, "Mexico City")
            if not picked:
                sugg = app.locator("[class*='suggestion'], [role='option']")
                if sugg.count():
                    sugg.first.click()
                    picked = True
            log(f"location fallback picked={picked}")

        # Checkbox groups: prefer "none of the above"-style labels.
        for text in ["None of the above", "Not applicable"]:
            lbl = form.locator("label", has_text=text)
            if lbl.count():
                lbl.first.click()
                log(f"checkbox: {text}")

        # EEO selects.
        for qid, matcher in [
            ("gender", "Decline"),
            ("hispanic_ethnicity", "Decline"),
            ("veteran_status", "don't wish"),
            ("disability_status", "do not want"),
        ]:
            if form.locator(f"#{qid}").count() == 0:
                continue
            form.locator(f"#{qid}").click()
            if pick_menu_option(page, app, matcher):
                log(f"{qid}: declined")

        # Checkbox groups: prefer "none of the above"-style labels.
        for text in ["None of the above", "Not applicable"]:
            lbl = form.locator("label", has_text=text)
            if lbl.count():
                lbl.first.click()
                log(f"checkbox: {text}")

        # Resume upload.
        file_inputs = form.locator("input[type=file]")
        if file_inputs.count():
            file_inputs.nth(0).set_input_files(str(resume_path))
            page.wait_for_timeout(2000)
            log("resume attached")

        submit = app.locator("button", has_text="Submit application").first
        if submit.count() == 0:
            log("NO submit button found")
            page.screenshot(path="/tmp/driver_no_submit.png", full_page=True)
            browser.close()
            return 1
        if submit.is_disabled():
            log("submit disabled — cannot submit")
            page.screenshot(path="/tmp/driver_blocked.png", full_page=True)
            browser.close()
            return 1

        if dry_run:
            log("dry run: would submit now")
            browser.close()
            return 0

        submit.click()
        page.wait_for_timeout(8000)
        body = app.locator("body").inner_text()[:400].replace("\n", " ")
        log(f"post-submit: {body}")
        confirmed = any(k in body.lower() for k in
                        ("submitted", "thank you", "application received"))
        log(f"confirmed={confirmed}")
        page.screenshot(path="/tmp/driver_result.png", full_page=True)
        browser.close()
        return 0 if confirmed else 2


if __name__ == "__main__":
    sys.exit(main())
