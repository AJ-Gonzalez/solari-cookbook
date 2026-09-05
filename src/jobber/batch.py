"""Batch apply: fill a cohort of jobs sequentially, never blocking.

A cohort is a slice of the queue (seniority, keyword query, eligibility)
ordered by rank ratio. Each job gets its own browser context (Ashby
persists application drafts per profile — a fresh context per job
prevents answers leaking between unrelated applications; LESSONS.md).

Outcome contract per job:
- submitted     auto-submit clicked and confirmation seen -> 'applied'
- ready         bank covered everything, no submit -> 'staged'
- gaps          bank couldn't cover required fields -> 'needs_human'
                (gap labels recorded; the live runner handles those jobs)
- no_form/error left 'new', recorded in apply_runs for review
"""
import json
import time
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

from .answers import AnswersBank
from .apply_flow import fill_job
from .seniority import classify


@dataclass
class Cohort:
    seniority: str | None = None   # junior|mid|senior|staff|c-suite
    query: str | None = None       # substring on title+company
    eligible_only: bool = True     # skip location_eligible='no'
    limit: int = 10
    from_bestshot: bool = False    # order by resume-fit instead of ratio
    worst: bool = False            # take the BOTTOM of the bestshot list


def select_cohort(conn, cohort: Cohort, resume_text: str | None = None) -> list:
    """Highest-ratio jobs matching the cohort, from 'new' status only
    (from_bestshot orders by resume-fit instead of ratio). resume_text
    overrides the resume.md seed for testing."""
    # Sources whose stored URL is an aggregator page, not an ATS form:
    # proven no_form at scale on 2026-09-05 (5/5 attempts). Kept visible
    # in the dashboard bestshot view; only apply cohorts skip them.
    NO_FORM_SOURCES = {"themuse", "wwr", "remoteok", "workingnomads",
                       "hnwhoishiring"}
    sql = """
        SELECT j.rowid, j.company, j.title, j.url, j.source, j.ratio,
               j.location_eligible, j.comp_min, j.comp_max,
               j.source_job_id
        FROM jobs j
        WHERE j.status = 'new' AND j.hard_block = 0
    """
    params: list = []
    if cohort.eligible_only:
        sql += " AND j.location_eligible != 'no'"
    if cohort.query:
        sql += " AND (j.title LIKE ? OR j.company LIKE ?)"
        like = f"%{cohort.query}%"
        params += [like, like]
    if cohort.from_bestshot:
        # Best-shot order: resume-seeded fit with per-company cap and
        # dedup; the cohort keeps batch's own statuses ('new' only) and
        # filters, so needs_human jobs re-enter via the live runner.
        from .bestshot import bestshot
        from .criteria import load_criteria
        rows = bestshot(conn, resume_text,
                        load_criteria(), per_company=3,
                        limit=10 ** 6, statuses=("new",))
        if cohort.query:
            q = cohort.query.lower()
            rows = [r for r in rows
                    if q in (r["title"] or "").lower()
                    or q in (r["company"] or "").lower()]
        if cohort.seniority:
            rows = [r for r in rows
                    if classify(r["title"] or "") == cohort.seniority]
        rows = [r for r in rows
                if r.get("source") not in NO_FORM_SOURCES]
        # Proven no-form trumps source guessing: stripe/databricks jobs
        # hide their form behind a JS careers-site redirect, so a real
        # ATS job can no_form just like an aggregator. One strike is
        # enough — revisit if the driver learns the redirect dance.
        tried_no_form = {x[0] for x in conn.execute(
            "SELECT DISTINCT job_rowid FROM apply_runs "
            "WHERE outcome = 'no_form'")}
        rows = [r for r in rows if r["rowid"] not in tried_no_form]
        if cohort.worst:
            # Bottom of the fit ranking, ascending: the most expendable
            # applications go first in a test run.
            return rows[-cohort.limit:][::-1]
        return rows[:cohort.limit]
    rows = conn.execute(sql + " ORDER BY j.ratio DESC", params).fetchall()
    if cohort.seniority:
        rows = [r for r in rows
                if classify(r["title"] or "") == cohort.seniority]
    return rows[:cohort.limit]


def record_outcome(conn, rowid: int, outcome: str, gaps: list[str],
                   now: str) -> None:
    conn.execute(
        "INSERT INTO apply_runs (job_rowid, started_at, outcome, gaps) "
        "VALUES (?, ?, ?, ?)", (rowid, now, outcome, json.dumps(gaps)))
    status = {"submitted": "applied", "ready": "staged",
              "gaps": "needs_human"}.get(outcome)
    if status:
        conn.execute("UPDATE jobs SET status=? WHERE rowid=?", (status, rowid))
    conn.commit()


def run_batch(conn, cohort: Cohort, bank: AnswersBank, resume,
              auto_submit: bool = False, fill_fn=fill_job,
              headless: bool = False, log=print,
              browser_mode: str = "local") -> dict:
    """Run the fill flow over the cohort with a fresh context per job.
    fill_fn takes (page, url, resume, bank, auto_submit) -> FillResult.
    browser_mode 'solari' swaps the local Chromium for a fresh stealth
    session per job (managed captcha solving; same fresh-context rule)."""
    rows = select_cohort(conn, cohort)

    def now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    summary = {"cohort": len(rows), "submitted": 0, "staged": 0,
               "needs_human": 0, "skipped": 0}
    if not rows:
        log("no jobs match the cohort")
        return summary

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        solari = None
        if browser_mode == "solari":
            from . import solari_browser
            solari = solari_browser
        else:
            browser = p.chromium.launch(headless=headless)
        for r in rows:
            log(f"\n=== [{r['rowid']}] {r['company']} — {r['title']} ===")
            log(f"    {r['url']}")
            session = None
            if solari is not None:
                session = solari.create_session()
                browser = p.chromium.connect_over_cdp(
                    session["cdpEndpoint"])
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
            else:
                ctx = browser.new_context(
                    user_agent=("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                                "Gecko/20100101 Firefox/130.0"),
                    viewport={"width": 1400, "height": 950},
                )
                page = ctx.new_page()
            result = None
            try:
                result = fill_fn(page, r["url"], resume, bank,
                                 auto_submit=auto_submit)
                outcome = (result.outcome if result.outcome in
                           ("submitted", "ready", "gaps", "no_form")
                           else "error")
                log(f"    -> {outcome}"
                    + (f" ({result.note})" if result.note else "")
                    + (f" gaps: {len(result.gaps)}" if result.gaps else ""))
            except Exception as e:
                outcome = "error"
                log(f"    -> error: {str(e)[:120]}")
            finally:
                if solari is not None:
                    try:
                        browser.close()
                    finally:
                        try:
                            solari.release_session(session["sessionId"])
                        except Exception as e:
                            log(f"    -> session release failed: "
                                f"{str(e)[:80]}")
                else:
                    ctx.close()
            record_outcome(conn, r["rowid"], outcome,
                           result.gaps if result else [], now())
            # 'ready' lands in the staged bucket: the form was filled,
            # submit wasn't confirmed — recorded, not applied.
            key = ("submitted" if outcome == "submitted"
                   else "staged" if outcome == "ready"
                   else "needs_human" if outcome == "gaps"
                   else "skipped")
            summary[key] += 1
            time.sleep(2)  # polite pacing between applications
        browser.close()
    return summary
