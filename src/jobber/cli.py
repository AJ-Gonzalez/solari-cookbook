"""Command line interface: harvest, show, mark, scan, view, open,
similar, dashboard."""
import argparse
import json
import re
import sys
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from . import db, gates, rank
from .criteria import load_boards, load_criteria
from .sources import (arbeitnow, ashby, greenhouse, himalayas,
                      hn_whoishiring, jobicy, lever, remotive, remoteok,
                      smartrecruiters, themuse, workable, workingnomads, wwr)

SOURCES = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "remoteok": remoteok,
    "remotive": remotive,
    "jobicy": jobicy,
    "arbeitnow": arbeitnow,
    "himalayas": himalayas,
    "themuse": themuse,
    "wwr": wwr,
    "workingnomads": workingnomads,
    "hnwhoishiring": hn_whoishiring,
    "workable": workable,
    "smartrecruiters": smartrecruiters,
}
# Aggregator boards with one global feed: enabled flag in boards.toml,
# no per-company tokens.
TOKENLESS = {"remoteok", "remotive", "jobicy", "arbeitnow", "himalayas",
             "themuse", "wwr", "workingnomads", "hnwhoishiring"}


def cmd_harvest(args: argparse.Namespace) -> None:
    criteria = load_criteria()
    boards = load_boards()
    conn = db.connect(Path(args.db))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    all_rows = []
    for name, module in SOURCES.items():
        conf = boards.get(name, {})
        if name in TOKENLESS:
            if not conf.get("enabled"):
                continue
            tokens = [None]
        else:
            tokens = conf.get("tokens") or []
        ok = failed = 0
        for token in tokens:
            try:
                raw = module.fetch(token)
                rows = module.parse(raw, token)
            except Exception as e:
                failed += 1
                print(f"  {name}/{token}: {e}", file=sys.stderr)
                continue
            rows = [r for r in rows
                    if criteria.title_matches(r["title"])
                    and criteria.text_allowed(r["title"] + " " + r["description"])]
            rank.enrich(rows, criteria)
            all_rows.extend(rows)
            ok += 1
        print(f"{name}: {ok} board(s) ok, {failed} failed, {len(all_rows)} rows total")
    db.upsert_jobs(conn, all_rows, now)
    print(f"upserted {len(all_rows)} matching listings")

    if args.top:
        _print_queue(conn, args.top, ("new", "queued"), True)


def _print_queue(conn, limit: int, statuses, eligible_only: bool,
                 include_gated: bool = False) -> None:
    rows = db.ranked_rows(conn, statuses, eligible_only, include_gated)
    if not rows:
        print("queue is empty")
        return
    print(f"\n{'id':>5}  {'ratio':>7}  {'comp':>15}  {'elg':>7}  {'deg':>9}  "
          f"{'st':>7}  {'company':<18} {'title':<40}  url")
    for r in rows[:limit]:
        comp = "?"
        if r["comp_currency"] == "USD" and r["comp_min"]:
            hi = r["comp_max"] or r["comp_min"]
            comp = f"{r['comp_min'] // 1000}-{hi // 1000}k"
        elif r["comp_currency"]:
            comp = f"{r['comp_min']} {r['comp_currency']}"
        ratio = f"{r['ratio']:.0f}" if r["ratio"] is not None else "-"
        title = r["title"][:38] + ".." if len(r["title"]) > 40 else r["title"]
        print(f"{r['rowid']:>5}  {ratio:>7}  {comp:>15}  {r['location_eligible']:>7}  "
              f"{r['degree_flag']:>9}  {r['status']:>7}  {r['company'][:18]:<18} "
              f"{title:<40}  {r['url']}")


def _get_job(conn, rowid: int):
    r = conn.execute("SELECT rowid, * FROM jobs WHERE rowid=?", (rowid,)).fetchone()
    if r is None:
        sys.exit(f"no job with id {rowid}")
    return r


def cmd_show(args: argparse.Namespace) -> None:
    conn = db.connect(Path(args.db))
    statuses = tuple(s.strip() for s in args.status.split(","))
    _print_queue(conn, args.top, statuses, not args.all_locations,
                 args.include_gated)


def _scan_and_report(conn, r) -> None:
    """Run a form scan and store it; prints what was found."""
    questions, gates_found = gates.scan_job(
        r["source"], r["url"], r["company"], r["source_job_id"])
    if questions is None:
        print("  form scan inconclusive (no form at canonical URL)")
        return
    db.set_gate_result(conn, r["rowid"], gates_found)
    if gates_found:
        print(f"  form scan: {len(questions)} questions, gates found:")
        for cat, qs in gates_found.items():
            for q in qs:
                print(f"    [{cat}] {q[:120]}")
    else:
        print(f"  form scan: {len(questions)} questions, no gates")


def cmd_mark(args: argparse.Namespace) -> None:
    conn = db.connect(Path(args.db))
    r = _get_job(conn, args.id)
    if args.status == "queued" and r["gate_flags"] is None \
            and r["source"] in ("greenhouse", "lever"):
        # Scan before queueing: gated roles surface here, not at apply time.
        _scan_and_report(conn, r)
    if not db.set_status(conn, args.id, args.status):
        sys.exit(f"could not set status: invalid id or status "
                 f"(valid: {', '.join(db.VALID_STATUSES)})")
    r = _get_job(conn, args.id)
    note = " [HARD-BLOCKED: excluded from default views]" if r["hard_block"] else ""
    print(f"[{args.id}] {args.status}: {r['title']} — {r['company']}{note}")


def cmd_scan(args: argparse.Namespace) -> None:
    conn = db.connect(Path(args.db))
    r = _get_job(conn, args.id)
    if r["source"] not in ("greenhouse", "lever"):
        sys.exit(f"scan not wired for {r['source']} yet (needs a browser session)")
    _scan_and_report(conn, r)
    r = _get_job(conn, args.id)
    print(f"hard_block={r['hard_block']}"
          + (" [excluded from default views]" if r["hard_block"] else ""))


def cmd_view(args: argparse.Namespace) -> None:
    conn = db.connect(Path(args.db))
    r = _get_job(conn, args.id)
    comp = "?"
    if r["comp_currency"] == "USD" and r["comp_min"]:
        hi = r["comp_max"] or r["comp_min"]
        comp = f"${r['comp_min']:,}-${hi:,} USD ({r['comp_confidence']})"
    elif r["comp_currency"] and r["comp_min"] and r["comp_max"]:
        comp = f"{r['comp_min']:,}-{r['comp_max']:,} {r['comp_currency']}"
    elif r["comp_currency"] and r["comp_min"]:
        comp = f"{r['comp_min']:,} {r['comp_currency']}"
    print(f"[{r['rowid']}] {r['title']}")
    print(f"company:    {r['company']} ({r['source']})")
    print(f"comp:       {comp}")
    print(f"location:   {r['location']}  eligible={r['location_eligible']}  "
          f"workplace={r['workplace']}")
    print(f"score:      ratio={r['ratio']}  qual={r['qual_score']}  "
          f"degree={r['degree_flag']}  hard_block={r['hard_block']}")
    if r["gate_flags"] and r["gate_flags"] != "{}":
        print(f"gates:      {r['gate_flags']}")
    print(f"url:        {r['url']}")
    print(f"\n{r['description'] or '(no description)'}")


def cmd_open(args: argparse.Namespace) -> None:
    conn = db.connect(Path(args.db))
    r = _get_job(conn, args.id)
    webbrowser.open(r["url"])
    print(f"opened [{r['rowid']}] {r['title']} — {r['url']}")


def cmd_similar(args: argparse.Namespace) -> None:
    from .similar import find_similar  # deferred: tokenization costs ~1s
    conn = db.connect(Path(args.db))
    try:
        results = find_similar(conn, args.id, args.top)
        if not results:
            sys.exit(f"no similar roles found for id {args.id}")
        print(f"roles similar to [{args.id}]:")
        for r in results:
            comp = (f"{r['comp_min']}-{r['comp_max']} {r['comp_currency']}"
                    if r["comp_min"] else "?")
            url = conn.execute("SELECT url FROM jobs WHERE rowid=?",
                               (r["rowid"],)).fetchone()[0]
            print(f"  {r['score']:.3f}  [{r['rowid']}] {r['company']}"
                  f"  {r['title'][:44]}  {comp:<14} {url}")
    finally:
        conn.close()


def cmd_bestshot(args: argparse.Namespace) -> None:
    from .bestshot import bestshot  # deferred: tokenization costs ~3s
    criteria = load_criteria()
    conn = db.connect(Path(args.db))
    try:
        resume = Path(args.resume)
        resume_text = resume.read_text() if resume.exists() else ""
        if not resume_text:
            print(f"warning: {args.resume} missing — fit is focus-only")
        results = bestshot(conn, resume_text, criteria,
                           per_company=args.per_company,
                           min_fit=args.min_fit, limit=args.limit)
        if not results:
            sys.exit("no bestshot results — check gates/statuses/min-fit")
        print(f"best shots: {len(results)} roles "
              f"(cap {args.per_company}/company, floor {args.min_fit})")
        for r in results:
            comp = (f"{r['comp_min']}-{r['comp_max']} {r['comp_currency']}"
                    if r["comp_min"] else "?")
            flags = (f"  [{', '.join(r['screening'])}]"
                     if r["screening"] else "")
            if r.get("gaps"):
                flags += f"  gaps: {', '.join(r['gaps'])}"
            if r["penalty"] < 1.0:
                flags += f"  (demoted x{r['penalty']})"
            reposts = f" (+{r['reposts']} reposts)" if r["reposts"] else ""
            print(f"  {r['score']:.3f} (fit {r['fit']:.3f})"
                  f"  [{r['rowid']}] {r['company']}  {r['title'][:44]}"
                  f"  {comp:<14}{reposts}{flags}")
            print(f"        {r['url']}")
    finally:
        conn.close()


def cmd_batch_apply(args: argparse.Namespace) -> None:
    import tomllib
    from .answers import AnswersBank, seed_from_file
    from .batch import Cohort, run_batch
    conn = db.connect(Path(args.db))
    bank = AnswersBank(conn)
    seed_from_file(bank, "answers.toml")
    resume = Path("personal/resume.pdf")
    if not resume.exists():
        sys.exit("no resume at personal/resume.pdf — batch apply attaches it")
    toggles = tomllib.load(open("answers.toml", "rb")).get("toggles", {})
    cohort = Cohort(seniority=args.seniority, query=args.query,
                    limit=args.limit, from_bestshot=args.from_bestshot)
    summary = run_batch(conn, cohort, bank, resume,
                        auto_submit=bool(toggles.get("auto_submit")))
    print(f"\nbatch done: {summary}")


def cmd_dashboard(args: argparse.Namespace) -> None:
    from .dashboard import serve  # deferred: keeps CLI startup free of server imports
    serve(args.port, args.db)


def cmd_repqueue(args: argparse.Namespace) -> None:
    from . import reputation
    conn = db.connect(Path(args.db))
    reputation.ensure_table(conn)
    pending = reputation.pending_companies(conn)
    print(f"{len(pending)} company(ies) to check")
    done = reputation.run_queue(conn, sleep_s=args.sleep)
    print(f"checked {done} companies")


def cmd_companyinfo(args: argparse.Namespace) -> None:
    from . import companies
    conn = db.connect(Path(args.db))
    try:
        done = companies.enrich_missing(conn, limit=args.limit)
        total = conn.execute(
            "SELECT COUNT(*) c FROM companies WHERE summary IS NOT NULL"
        ).fetchone()["c"]
        print(f"enriched {done} new; {total} companies with summaries")
    finally:
        conn.close()


def cmd_screening(args: argparse.Namespace) -> None:
    from .gates import screening_signals
    conn = db.connect(Path(args.db))
    try:
        rows = conn.execute(
            """
            SELECT rowid, company, title, source, description, gate_flags
            FROM jobs
            WHERE status IN ('new','queued','staged','needs_human')
              AND hard_block = 0
            """).fetchall()
        by_source: dict = {}
        flagged = []
        for r in rows:
            text = (r["description"] or "") + " " + (r["gate_flags"] or "")
            signals = screening_signals(text)
            if signals:
                flagged.append((r["rowid"], r["company"], r["title"], signals))
                by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        total = len(rows)
        print(f"{len(flagged)} of {total} queue listings show "
              "automated-screening markers:\n")
        print("by ATS source:")
        for src, n in sorted(by_source.items(), key=lambda x: -x[1]):
            print(f"  {src:<14} {n}")
        print("\nflagged listings (top 20):")
        for rowid, company, title, signals in flagged[:20]:
            print(f"  [{rowid}] {company[:22]:<22} {title[:38]:<38} "
                  f"{', '.join(signals)}")
    finally:
        conn.close()


def _extract_token(platform: str, raw: str) -> str:
    m = (re.search(r"workable\.com/([A-Za-z0-9_-]+)", raw)
         if platform == "workable"
         else re.search(r"smartrecruiters\.com/([A-Za-z0-9_-]+)", raw))
    return (m.group(1) if m else raw.strip()).strip("/")


def _probe_token(platform: str, token: str) -> int | None:
    """Returns job count for a candidate token, None on error."""
    try:
        if platform == "workable":
            body = json.dumps({}).encode()
            req = urllib.request.Request(
                f"https://apply.workable.com/api/v1/accounts/{token}/jobs",
                data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "User-Agent": "jobber/0.1"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp).get("total")
        else:
            req = urllib.request.Request(
                f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                headers={"User-Agent": "jobber/0.1"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp).get("totalFound")
    except Exception:
        return None


def _append_token(path: Path, platform: str, token: str) -> None:
    """Add token to boards.toml's [platform] section. Creates the section
    if absent or commented out; updates the tokens list if present."""
    text = path.read_text() if path.exists() else ""
    pattern = re.compile(
        rf"\n\[{platform}\]\ntokens = \[([^\]]*)\]")
    m = pattern.search(text)
    if m:
        existing = [t.strip().strip('"') for t in m.group(1).split(",") if t.strip()]
        if token not in existing:
            existing.append(token)
        text = pattern.sub(
            f"\n[{platform}]\ntokens = [" +
            ", ".join(f'"{t}"' for t in existing) + "]", text, count=1)
    else:
        text += f"\n[{platform}]\ntokens = [\"{token}\"]\n"
    path.write_text(text)


def cmd_addtoken(args: argparse.Namespace) -> None:
    platform = "workable" if args.platform == "workable" else "smartrecruiters"
    token = _extract_token(platform, args.url_or_token)
    count = _probe_token(platform, token)
    if count is None:
        sys.exit(f"probe failed for '{token}' — invalid token or network error")
    if count == 0:
        sys.exit(f"token '{token}' is valid but lists 0 jobs — not adding")
    _append_token(Path("boards.toml"), platform, token)
    print(f"added {platform} token '{token}' ({count} jobs) to boards.toml")


def main(argv: list[str] | None = None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(db.DEFAULT_DB))
    p = argparse.ArgumentParser(prog="jobber", parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", parents=[common], help="fetch all boards, score, store")
    h.add_argument("--top", type=int, default=20, help="print top N after harvest")
    h.set_defaults(func=cmd_harvest)

    s = sub.add_parser("show", parents=[common], help="print the ranked queue")
    s.add_argument("--top", type=int, default=30)
    s.add_argument("--status", default="new,queued",
                   help="comma-separated statuses to include")
    s.add_argument("--all-locations", action="store_true",
                   help="include location_eligible=no listings too")
    s.add_argument("--include-gated", action="store_true",
                   help="include hard-blocked (gate-question) listings")
    s.set_defaults(func=cmd_show)

    m = sub.add_parser("mark", parents=[common], help="set a job's status by id")
    m.add_argument("id", type=int)
    m.add_argument("status", choices=db.VALID_STATUSES)
    m.set_defaults(func=cmd_mark)

    sc = sub.add_parser("scan", parents=[common],
                        help="scan a job's application form for gate questions")
    sc.add_argument("id", type=int)
    sc.set_defaults(func=cmd_scan)

    v = sub.add_parser("view", parents=[common], help="full listing detail by id")
    v.add_argument("id", type=int)
    v.set_defaults(func=cmd_view)

    o = sub.add_parser("open", parents=[common], help="open a job's posting URL in the browser")
    o.add_argument("id", type=int)
    o.set_defaults(func=cmd_open)

    q = sub.add_parser("repqueue", parents=[common],
                       help="run reputation checks for all unchecked companies")
    q.add_argument("--sleep", type=int, default=8,
                   help="seconds between companies (rate limiting)")
    q.set_defaults(func=cmd_repqueue)

    ci = sub.add_parser("companyinfo", parents=[common],
                        help="enrich company descriptions from Wikipedia")
    ci.add_argument("--limit", type=int, default=50,
                    help="max companies to look up this run")
    ci.set_defaults(func=cmd_companyinfo)

    scr = sub.add_parser("screening", parents=[common],
                         help="report automated-screening markers in the queue")
    scr.set_defaults(func=cmd_screening)

    d = sub.add_parser("dashboard", parents=[common], help="local web view of the queue")
    d.add_argument("--port", type=int, default=8799)
    d.set_defaults(func=cmd_dashboard)

    b = sub.add_parser("batch-apply", parents=[common],
                       help="fill a cohort of applications sequentially, "
                            "never blocking on human input")
    b.add_argument("--seniority", choices=["junior", "mid", "senior", "staff",
                                           "c-suite"], default=None)
    b.add_argument("--query", default=None,
                   help="substring filter on title/company, e.g. 'backend'")
    b.add_argument("--limit", type=int, default=10,
                   help="max jobs in the cohort (best-ratio first)")
    b.add_argument("--from-bestshot", action="store_true",
                   help="order the cohort by resume fit (bestshot) "
                        "instead of comp-per-requirement ratio")
    b.set_defaults(func=cmd_batch_apply)

    sim = sub.add_parser("similar", parents=[common],
                         help="find roles textually similar to a given job id")
    sim.add_argument("id", type=int)
    sim.add_argument("--top", type=int, default=15)
    sim.set_defaults(func=cmd_similar)

    bs = sub.add_parser("bestshot", parents=[common],
                        help="ranked apply queue: resume-seeded fit, "
                             "repost dedup, capped roles per company")
    bs.add_argument("--per-company", type=int, default=2,
                    help="max distinct roles kept per company")
    bs.add_argument("--min-fit", type=float, default=0.06,
                    help="raw cosine floor before priority boosting")
    bs.add_argument("--limit", type=int, default=40,
                    help="max roles in the output queue")
    bs.add_argument("--resume", default="resume.md",
                    help="markdown resume used as the fit seed")
    bs.set_defaults(func=cmd_bestshot)
    a = sub.add_parser("addtoken", help="verify an ATS token from an apply URL and add it to boards.toml")
    a.add_argument("platform", choices=["workable", "smartrecruiters"])
    a.add_argument("url_or_token", help="full apply URL or bare token")
    a.set_defaults(func=cmd_addtoken)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
