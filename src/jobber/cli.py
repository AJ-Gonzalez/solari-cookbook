"""Command line interface: harvest, show, mark, scan, view, open, dashboard."""
import argparse
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from . import db, gates, rank
from .criteria import load_boards, load_criteria
from .sources import ashby, greenhouse, lever, remoteok

SOURCES = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "remoteok": remoteok,
}


def cmd_harvest(args: argparse.Namespace) -> None:
    criteria = load_criteria()
    boards = load_boards()
    conn = db.connect(Path(args.db))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    all_rows = []
    for name, module in SOURCES.items():
        conf = boards.get(name, {})
        if name == "remoteok":
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


def cmd_dashboard(args: argparse.Namespace) -> None:
    from .dashboard import serve  # deferred: keeps CLI startup free of server imports
    serve(args.port, args.db)


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

    d = sub.add_parser("dashboard", parents=[common], help="local web view of the queue")
    d.add_argument("--port", type=int, default=8799)
    d.set_defaults(func=cmd_dashboard)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
