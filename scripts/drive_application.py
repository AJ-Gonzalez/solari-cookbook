#!/usr/bin/env python3
"""General application driver: fill a greenhouse/lever application with
mock data and submit. Test-mule tool — mock identity is unmissable.

Usage: .venv/bin/python scripts/drive_application.py <job_url> [--dry-run]

Form-stack support:
- greenhouse job-boards (main frame or custom-domain embed iframe)
- lever apply pages (server-rendered)
Lessons baked in (see LESSONS.md): apply buttons mount the embed late,
resume uploaders differ per board, EEO select labels are not standardized,
country-list questions need a coherent residence answer.
"""
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.jobber import db
from src.jobber.answers import AnswersBank, seed_from_file

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

MOCK_TEXT = ("Mock application from an automated test harness. "
             "Please disregard.")

DECLINE_PAT = re.compile(
    r"decline|none of the|not applicable|don't wish|do not want|prefer not",
    re.I)
EEO_PAT = re.compile(r"gender|ethnic|race|veteran|disability|identify", re.I)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_app_frame(page):
    return next((f for f in page.frames
                 if "greenhouse.io" in f.url
                 and ("job_app" in f.url or "jobs" in f.url)),
                page.main_frame)


def pick_menu_option(page, app, matcher: str) -> bool:
    opts = app.locator(".select__menu .select__option")
    n = opts.count()
    target = next((i for i in range(n)
                   if matcher.lower() in opts.nth(i).inner_text().lower()), None)
    if target is None:
        page.keyboard.press("Escape")
        return False
    opts.nth(target).click(timeout=5000)
    return True


def drive_greenhouse(page, app, resume_path: Path, dry_run: bool) -> int:
    form = app.locator("#application-form")
    form.wait_for(state="visible", timeout=30000)
    log(f"app frame: {app.url[:80]}")

    # Identity fields (boards differ; skip absent ones).
    for sel, val in {
        "#first_name": "Mocktest",
        "#last_name": "McHarness",
        "#preferred_name": "Mock",
        "#email": "mock.harness@example.com",
        "#phone": "+52 55 1234 5678",
    }.items():
        try:
            if form.locator(sel).count():
                form.locator(sel).first.fill(val, timeout=5000)
                log(f"{sel} filled")
        except Exception as e:
            log(f"{sel} skipped: {str(e)[:50]}")

    # Phone country react-select (boards without it are skipped).
    if form.locator("#country").count():
        try:
            form.locator("#country").click(timeout=5000)
            if pick_menu_option(page, app, "Mexico"):
                log("phone country: Mexico")
        except Exception as e:
            log(f"country select skipped: {str(e)[:50]}")

    # Custom text questions (non-select), incl. LinkedIn-style fields.
    text_qs = form.locator("input[id^='question_'][class*='input__single-line']")
    for i in range(text_qs.count()):
        el = text_qs.nth(i)
        if not el.input_value().strip():
            el.fill(MOCK_TEXT)
    linkedin = form.locator(
        "input[aria-label*='LinkedIn' i], input[id*='linkedin' i]")
    for i in range(linkedin.count()):
        if not linkedin.nth(i).input_value().strip():
            linkedin.nth(i).fill("https://www.linkedin.com/in/mock-harness")
    log("text questions filled")

    # Custom react-select questions. Country lists (>40 options) get a
    # coherent residence answer; small lists get the least committal pick.
    q_inputs = form.locator("input[id^='question_']")
    answered = set()
    for i in range(q_inputs.count()):
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
        labels = [opts.nth(j).inner_text().strip() for j in range(opts.count())]
        if len(labels) > 40:
            if "Mexico" in labels:
                try:
                    opts.nth(labels.index("Mexico")).click(timeout=5000)
                    log(f"{qid}: 'Mexico' (of {len(labels)})")
                except Exception as e:
                    page.keyboard.press("Escape")
                    log(f"{qid}: mexico pick failed ({str(e)[:40]})")
            else:
                page.keyboard.press("Escape")
                log(f"{qid}: country list without Mexico, skipped")
            continue
        choice = next((t for t in labels if DECLINE_PAT.search(t)), labels[0])
        try:
            opts.nth(labels.index(choice)).click(timeout=5000)
            log(f"{qid}: '{choice}' (of {len(labels)})")
        except Exception as e:
            page.keyboard.press("Escape")
            log(f"{qid}: click failed ({str(e)[:40]})")

    # Location (City) geo-typeahead (react-select): type, then pick.
    if form.locator("#candidate-location").count():
        try:
            form.locator("#candidate-location").click(timeout=5000)
            form.locator("#candidate-location").type("Mexico City", delay=80)
            page.wait_for_timeout(2500)
            if pick_menu_option(page, app, "Mexico City"):
                log("candidate-location: Mexico City")
        except Exception as e:
            log(f"candidate-location skipped: {str(e)[:50]}")

    # EEO-style selects: labels differ per board, so match surrounding
    # text and pick the least committal option. Skips answered selects.
    controls = form.locator(".select__control")
    for i in range(controls.count()):
        c = controls.nth(i)
        if c.locator(".select__single-value").count():
            continue
        ctx = c.evaluate(
            "el => { let t = el; for (let k = 0; k < 4 && t; k++) {"
            " t = t.parentElement; if (t && /gender|ethnic|race|veteran|"
            "disability|identify/i.test(t.innerText)) return t.innerText; }"
            " return ''; }")
        if not EEO_PAT.search(ctx or ""):
            continue
        try:
            c.click(timeout=4000)
        except Exception:
            continue
        opts = app.locator(".select__menu .select__option")
        n = opts.count()
        if n == 0:
            page.keyboard.press("Escape")
            continue
        labels = [opts.nth(j).inner_text().strip() for j in range(n)]
        pick = next((t for t in labels if DECLINE_PAT.search(t)), None)
        if pick is None:
            page.keyboard.press("Escape")
            log(f"eeo select (ctx: {ctx[:40]}): no decline option, skipped")
            continue
        try:
            opts.nth(labels.index(pick)).click(timeout=5000)
            log(f"eeo select: '{pick}'")
        except Exception as e:
            page.keyboard.press("Escape")
            log(f"eeo click failed: {str(e)[:40]}")

    # Checkbox groups: prefer "none of the above"-style labels.
    for text in ["None of the above", "Not applicable"]:
        lbl = form.locator("label", has_text=text)
        if lbl.count():
            try:
                lbl.first.click(timeout=4000)
                log(f"checkbox: {text}")
            except Exception as e:
                log(f"checkbox '{text}' failed: {str(e)[:40]}")

    # Resume upload: the first file input backs the resume slot; later
    # ones (cover letter, dropbox mirrors) can hang — don't touch them.
    # The upload zone mounts lazily, so poll for it.
    file_inputs = form.locator("input[type=file]")
    for _ in range(20):
        if file_inputs.count():
            break
        page.wait_for_timeout(500)
    if file_inputs.count():
        try:
            file_inputs.nth(0).set_input_files(str(resume_path), timeout=10000)
            page.wait_for_timeout(2500)
            log("resume set on first input")
        except Exception as e:
            log(f"file input 0: {str(e)[:60]}")
    else:
        log("file inputs never appeared")

    submit = app.locator("button", has_text="Submit application").first
    if submit.count() == 0:
        log("NO submit button found")
        page.screenshot(path="/tmp/driver_no_submit.png", full_page=True)
        return 1
    if submit.is_disabled():
        log("submit disabled")
        page.screenshot(path="/tmp/driver_blocked.png", full_page=True)
        return 1
    if dry_run:
        log("dry run: would submit now")
        return 0

    submit.click()
    page.wait_for_timeout(8000)
    body = app.locator("body").inner_text()[:400].replace("\n", " ")
    log(f"post-submit: {body}")
    errors = [e.inner_text().strip()
              for e in app.locator("[class*='error']").all()
              if e.inner_text().strip()]
    if errors:
        log(f"post-submit errors: {errors[:10]}")
    confirmed = any(k in body.lower() for k in
                    ("submitted", "thank you", "application received"))
    log(f"confirmed={confirmed}")
    return 0 if confirmed else 2


def drive_lever(page, resume_path: Path, dry_run: bool) -> int:
    """Lever apply forms: server-rendered, plain name attributes."""
    page.wait_for_timeout(2000)
    form = page.locator("#application-form")
    form.wait_for(state="visible", timeout=30000)
    log("lever form visible")

    form.locator("input[name=name]").fill("Mocktest McHarness")
    form.locator("input[name=email]").fill("mock.harness@example.com")
    form.locator("input[name=phone]").fill("+52 55 1234 5678")
    if form.locator("input[name=location]").count():
        form.locator("input[name=location]").fill("Mexico City, Mexico")
    if form.locator("input[name='urls[LinkedIn]']").count():
        form.locator("input[name='urls[LinkedIn]']").fill(
            "https://www.linkedin.com/in/mock-harness")
    log("identity fields filled")

    # Custom card questions: radios -> first option, texts -> mock marker,
    # checkboxes -> first of each group.
    radios = form.locator("input[type=radio]")
    seen = set()
    for i in range(radios.count()):
        r = radios.nth(i)
        nm = r.get_attribute("name")
        if nm and nm not in seen:
            seen.add(nm)
            r.check(force=True)
            log(f"radio {nm.split('[')[-1]}: first option")
    texts = form.locator("input[type=text][name^='cards'], textarea[name^='cards']")
    for i in range(texts.count()):
        el = texts.nth(i)
        if not el.input_value().strip():
            el.fill(MOCK_TEXT)
    cbs = form.locator("input[type=checkbox][name^='cards']")
    seen_cb = set()
    for i in range(cbs.count()):
        cb = cbs.nth(i)
        nm = cb.get_attribute("name")
        if nm and nm not in seen_cb:
            seen_cb.add(nm)
            cb.check(force=True)
            log(f"checkbox {nm.split('[')[-1]}: first option")

    # EEO selects: least committal option or second entry.
    eeo = form.locator("select[name^='eeo']")
    for i in range(eeo.count()):
        s = eeo.nth(i)
        labels = [s.locator("option").nth(j).inner_text().strip()
                  for j in range(s.locator("option").count())]
        idx = next((j for j, t in enumerate(labels)
                    if j > 0 and re.search(r"decline|don't wish|do not want",
                                           t, re.I)), 1)
        if len(labels) > 1:
            s.select_option(index=idx)
            log(f"eeo select: '{labels[idx]}'")

    # Resume.
    if form.locator("input[name=resume]").count():
        form.locator("input[name=resume]").set_input_files(str(resume_path))
        page.wait_for_timeout(2000)
        log("resume attached")

    submit = form.locator("button[type=submit], input[type=submit]").first
    if submit.count() == 0:
        log("NO submit button")
        page.screenshot(path="/tmp/driver_no_submit.png", full_page=True)
        return 1
    if submit.is_disabled():
        log("submit disabled")
        page.screenshot(path="/tmp/driver_blocked.png", full_page=True)
        return 1
    if dry_run:
        log("dry run: would submit now")
        return 0

    try:
        submit.click(timeout=15000)
    except Exception as e:
        log(f"submit click failed: {str(e)[:80]}")
        page.screenshot(path="/tmp/driver_submit_fail.png", full_page=True)
        return 1
    page.wait_for_timeout(8000)
    body = page.locator("body").inner_text()[:400].replace("\n", " ")
    log(f"post-submit: {body}")
    confirmed = any(k in body.lower() for k in
                    ("submitted", "thank you", "application received"))
    log(f"confirmed={confirmed}")
    return 0 if confirmed else 2


def main() -> int:
    job_url = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    resume_path = RESUME
    resume_path.write_bytes(MOCK_PDF)
    conn = db.connect()
    bank = AnswersBank(conn)
    seed_from_file(bank, "answers.toml")

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

        if "lever.co" in page.url:
            log("lever form detected")
            if not page.url.rstrip("/").endswith("/apply"):
                # The posting page hosts the form at /apply.
                page.goto(page.url.rstrip("/") + "/apply",
                          wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
            code = drive_lever(page, resume_path, dry_run)
            browser.close()
            return code

        if "ashbyhq.com" in page.url:
            log("ashby form detected")
            from src.jobber.driver import drive_ashby
            code = drive_ashby(page, page.main_frame, resume_path,
                               lambda q: {}, dry_run)
            browser.close()
            return code

        # Poll for the form: SPA sites mount the greenhouse embed (behind
        # an Apply button) late; one-shot checks race the render.
        deadline = time.time() + 30
        app = find_app_frame(page)
        form = app.locator("#application-form")
        while form.count() == 0 and time.time() < deadline:
            for trigger in ["button:has-text('Apply')",
                            "a:has-text('Apply Now')",
                            "text=Apply Now"]:
                loc = page.locator(trigger)
                if loc.count():
                    try:
                        loc.first.click(timeout=3000)
                        break
                    except Exception:
                        continue
            page.wait_for_timeout(2000)
            app = find_app_frame(page)
            form = app.locator("#application-form")

        if form.count() == 0:
            log("no application form found (even after apply-trigger poll)")
            page.screenshot(path="/tmp/driver_no_form.png", full_page=True)
            browser.close()
            return 1

        code = drive_greenhouse(page, app, resume_path, dry_run)
        browser.close()
        return code


if __name__ == "__main__":
    sys.exit(main())
