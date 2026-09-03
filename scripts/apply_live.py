#!/usr/bin/env python3
"""Live application run: visible browser, bank fills, human submits.

Flow:
1. Opens the posting's application form in a visible Chromium window.
2. Fills every field the answers bank knows (shared fill flow, which
   batch mode also uses).
3. Lists the gaps — the human types those directly into the form.
4. Waits (polling) until all required fields are filled.
5. The human clicks Submit. The runner detects the confirmation and
   learns the human-typed values into the bank for reuse.

Usage: .venv/bin/python scripts/apply_live.py <job_url>
"""
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from src.jobber import db
from src.jobber.answers import AnswersBank, seed_from_file
from src.jobber.apply_flow import CONFIRM_PAT, fill_job
from src.jobber.driver import discover_fields, empty_required


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


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
    toggles = tomllib.load(open("answers.toml", "rb")).get("toggles", {})
    auto_submit = bool(toggles.get("auto_submit"))
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

        def ask(fields):
            print(f"\n=== {len(fields)} field(s) I can't answer — please "
                  "type them in the browser window ===", flush=True)
            for f in fields:
                print(f"  - {f.label[:80]}")
            return {}

        result = fill_job(page, job_url, resume, bank,
                          auto_submit=auto_submit, ask=ask)
        log(f"fill outcome: {result.outcome}"
            + (f" — {result.note}" if result.note else ""))
        if result.outcome in ("no_form", "error"):
            log(f"fill failed: {result.note or 'no application form found'}")
            return 1

        # Gaps: the human fills them in the visible window; we poll.
        # (Ashby gap detection is not wired yet — fill leftovers by hand.)
        gaps = result.gaps if result.app is not None else []
        if gaps:
            print(f"\n=== {len(gaps)} required field(s) still empty — please "
                  "fill them in the browser window (no timeout; I'll wait) "
                  "===", flush=True)
            for label in gaps:
                print(f"  - {label[:80]}")
            while True:
                time.sleep(3)
                try:
                    gaps = [f.label for f in empty_required(result.app)]
                except Exception:
                    log("window was closed by the user — exiting")
                    return 1
                if not gaps:
                    break
            learned = learn_typed(result.app, bank,
                                  discover_fields(result.app))
            log(f"learned {learned} human-typed answer(s) into the bank")
        else:
            log("all required fields covered by the bank")

        log("FORM READY — review and click Submit in the browser window. "
            "Watching for the confirmation (no timeout)...")
        confirmed = False
        while True:
            try:
                if page.is_closed():
                    log("window closed by the user — exiting")
                    return 1
                body = ""
                for frame in page.frames:
                    try:
                        body += frame.locator("body").inner_text().lower()
                    except Exception:
                        continue  # frames detach during SPA re-renders
                if any(k in body for k in CONFIRM_PAT):
                    confirmed = True
                    break
            except Exception as e:
                log(f"watch retry: {str(e)[:60]}")
            time.sleep(3)
        log(f"confirmed={confirmed}")
        if confirmed:
            print("\n" + page.locator("body").inner_text()[:250], flush=True)
        page.wait_for_timeout(5000)
        browser.close()
        return 0 if confirmed else 2


if __name__ == "__main__":
    sys.exit(main())
