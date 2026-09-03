#!/usr/bin/env python3
"""Live application run: visible browser, bank fills, human submits.

Flow:
1. Opens the posting's application form in a visible Chromium window.
2. Fills every field the answers bank knows.
3. Lists the gaps — the human types those directly into the form.
4. Waits (polling) until all required fields are filled.
5. The human clicks Submit. The runner detects the confirmation and
   learns the human-typed values into the bank for reuse.

Usage: .venv/bin/python scripts/apply_live.py <job_url>
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from src.jobber import db
from src.jobber.answers import AnswersBank, seed_from_file
from src.jobber.driver import discover_fields, open_application, walk_and_fill

CONFIRM_PAT = ("thank you", "submitted", "application received")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _select_filled(loc) -> bool:
    """Read a react-select's value via its CONTROL (the selected-value div
    is a sibling of the input, never a descendant — scoping to the input
    always reads empty)."""
    control = loc.locator(
        "xpath=ancestor::div[contains(@class,'select__control')][1]")
    if control.count() == 0:
        return bool((loc.input_value(timeout=2000) or "").strip())
    text = control.inner_text(timeout=2000).strip()
    return bool(text) and text.lower() not in ("select...", "select")


def empty_required(app_frame) -> list:
    out = []
    for f in discover_fields(app_frame):
        if not f.required or f.kind == "file":
            continue
        loc = app_frame.locator(f.locator_id).first
        try:
            if f.kind == "select":
                if not _select_filled(loc):
                    out.append(f)
                continue
            val = (loc.input_value(timeout=2000) or "").strip()
        except Exception:
            continue
        if not val:
            out.append(f)
    return out


def learn_typed(app_frame, bank, fields) -> int:
    """The human typed gap answers by hand — bank them for next time."""
    learned = 0
    for f in fields:
        if f.kind in ("file",):
            continue
        try:
            loc = app_frame.locator(f.locator_id).first
            if f.kind == "select":
                control = loc.locator(
                    "xpath=ancestor::div[contains(@class,'select__control')][1]")
                val = control.inner_text(timeout=2000).strip() \
                    if control.count() else ""
            else:
                val = (loc.input_value(timeout=2000) or "").strip()
            if val and bank.lookup(f.label) is None:
                bank.learn(f.label, val, f.kind)
                learned += 1
        except Exception:
            continue
    return learned


def main() -> int:
    job_url = sys.argv[1]
    conn = db.connect()
    bank = AnswersBank(conn)
    seed_from_file(bank, "answers.toml")
    resume = Path("personal/resume.pdf")
    if not resume.exists():
        print("no resume at personal/resume.pdf — attach manually in the form")
        resume = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                        "Gecko/20100101 Firefox/130.0"),
            viewport={"width": 1400, "height": 950},
        )
        page = ctx.new_page()
        log(f"opening {job_url}")
        app, form = open_application(page, job_url)
        if app is None:
            log("no application form found")
            return 1

        def ask(fields):
            print(f"\n=== {len(fields)} field(s) I can't answer — please "
                  "type them in the browser window ===", flush=True)
            for f in fields:
                print(f"  - {f.label[:80]}")
            return {}

        status = walk_and_fill(page, app, resume, bank, ask, dry_run=False)
        log(f"driver fill done: {status}")
        page.screenshot(path="/tmp/live_state.png", full_page=True)

        # Gaps: the human fills them in the visible window; we poll.
        gaps = empty_required(app)
        if gaps:
            print(f"\n=== {len(gaps)} required field(s) still empty — please "
                  "fill them in the browser window (no timeout; I'll wait) "
                  "===", flush=True)
            for f in gaps:
                print(f"  - {f.label[:80]}")
            while True:
                time.sleep(3)
                try:
                    gaps = empty_required(app)
                except Exception:
                    log("window was closed by the user — exiting")
                    return 1
                if not gaps:
                    break
            learned = learn_typed(app, bank, discover_fields(app))
            log(f"learned {learned} human-typed answer(s) into the bank")
        else:
            log("all required fields covered by the bank")

        log("FORM READY — review and click Submit in the browser window. "
            "Watching for the confirmation (no timeout)...")
        confirmed = False
        while True:
            try:
                body = app.locator("body").inner_text().lower()
                if any(k in body for k in CONFIRM_PAT):
                    confirmed = True
                    break
            except Exception:
                log("window was closed by the user — exiting")
                return 1
            time.sleep(3)
        log(f"confirmed={confirmed}")
        if confirmed:
            print("\n" + app.locator("body").inner_text()[:250], flush=True)
        page.wait_for_timeout(5000)
        browser.close()
        return 0 if confirmed else 2


if __name__ == "__main__":
    sys.exit(main())
