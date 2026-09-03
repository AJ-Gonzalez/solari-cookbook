"""Single-job fill flow shared by the live runner and batch mode.

Extracted from scripts/apply_live.py so batch mode reuses the proven
ashby/greenhouse/lever branches instead of duplicating them. The
submission layer stays human-controlled by default: a fill either
reaches "ready" (staged for review+submit) or leaves gaps for the
human — batch mode never blocks on a person, it records and moves on.
"""
import re
import time
from dataclasses import dataclass, field

CONFIRM_PAT = ("thank you", "submitted", "application received")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


@dataclass
class FillResult:
    outcome: str            # ready | gaps | no_form | submitted | error
    gaps: list[str] = field(default_factory=list)   # labels the bank missed
    app: object = None      # form frame handle (gap polling in live mode)
    note: str = ""


def _confirm_within(page, seconds: int) -> bool:
    """Poll page text for a submission confirmation."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if page.is_closed():
                return False
            body = ""
            for frame in page.frames:
                try:
                    body += frame.locator("body").inner_text().lower()
                except Exception:
                    continue  # frames detach during SPA re-renders
            if any(k in body for k in CONFIRM_PAT):
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def fill_job(page, job_url: str, resume, bank, auto_submit: bool = False,
             ask=None) -> FillResult:
    """Open the form and fill everything the bank covers. `ask` defaults
    to ignoring gaps (batch mode); the live runner passes its own."""
    from .driver import (drive_ashby, empty_required, open_application,
                         walk_and_fill)
    if ask is None:
        def ask(fields):
            return {}

    ashby = "ashbyhq.com" in job_url
    try:
        if ashby:
            for attempt in (1, 2, 3):
                try:
                    page.goto(job_url, wait_until="domcontentloaded",
                              timeout=45000)
                    break
                except Exception as e:
                    log(f"goto attempt {attempt} failed: {str(e)[:60]}")
                    page.wait_for_timeout(3000)
            page.wait_for_timeout(4000)
            status = drive_ashby(page, page.main_frame, resume, bank, ask,
                                 dry_run=False)
            log(f"driver fill done: {status}")
            if auto_submit and status == "ready":
                submit = page.locator(
                    "button", has_text="Submit Application").first
                if submit.count() and not submit.is_disabled():
                    log("AUTO-SUBMIT: clicking Submit")
                    submit.click(timeout=15000)
                    confirmed = _confirm_within(page, 25)
                    return FillResult(
                        "submitted" if confirmed else "ready",
                        note="" if confirmed else "auto-submit unconfirmed")
                return FillResult("gaps",
                                  note="submit missing/disabled — not sent")
            # Ashby gap detection is not wired yet — trust the driver status.
            if status == "ready":
                return FillResult("ready")
            return FillResult("gaps", note=f"driver status: {status}")

        app, form = open_application(page, job_url)
        if app is None:
            return FillResult("no_form")
        status = walk_and_fill(page, app, resume, bank, ask, dry_run=False)
        log(f"driver fill done: {status}")
        gaps = [f.label for f in empty_required(app)]
        if auto_submit and status == "ready" and not gaps:
            submit = app.locator("button", has_text="Submit application").first
            if submit.count() and not submit.is_disabled():
                log("AUTO-SUBMIT: clicking Submit")
                submit.click(timeout=15000)
                confirmed = _confirm_within(page, 25)
                return FillResult(
                    "submitted" if confirmed else "ready",
                    gaps=gaps,
                    note="" if confirmed else "auto-submit unconfirmed")
            return FillResult("gaps", gaps=gaps,
                              note="submit missing/disabled — not sent")
        if status == "ready" and not gaps:
            return FillResult("ready", app=app)
        return FillResult("gaps", gaps=gaps, app=app)
    except Exception as e:
        return FillResult("error", note=str(e)[:200])
