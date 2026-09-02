"""Command line interface: `harvest` fetches and scores, `show` lists the queue."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import db, rank
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
            rows = [r for r in rows if criteria.title_matches(r["title"])]
            rank.enrich(rows, criteria)
            all_rows.extend(rows)
            ok += 1
        print(f"{name}: {ok} board(s) ok, {failed} failed, {len(all_rows)} rows total")
    db.upsert_jobs(conn, all_rows, now)
    print(f"upserted {len(all_rows)} matching listings")

    if args.top:
        _print_queue(conn, args.top)


def _ranked(conn, eligible_only: bool):
    rows = conn.execute(
        """
        SELECT * FROM jobs
        WHERE status NOT IN ('hidden', 'applied', 'rejected')
        ORDER BY ratio IS NULL, ratio DESC
        """
    ).fetchall()
    if eligible_only:
        rows = [r for r in rows if r["location_eligible"] in ("yes", "unknown")]
    return rows


def _print_queue(conn, limit: int) -> None:
    rows = _ranked(conn, eligible_only=True)
    if not rows:
        print("queue is empty")
        return
    print(f"\n{'ratio':>7}  {'comp':>15}  {'elg':>7}  {'deg':>9}  {'company':<18} {'title':<40}  url")
    for r in rows[:limit]:
        comp = "?"
        if r["comp_currency"] == "USD" and r["comp_min"]:
            hi = r["comp_max"] or r["comp_min"]
            comp = f"{r['comp_min'] // 1000}-{hi // 1000}k"
        elif r["comp_currency"]:
            comp = f"{r['comp_min']} {r['comp_currency']}"
        ratio = f"{r['ratio']:.0f}" if r["ratio"] is not None else "-"
        title = r["title"][:38] + ".." if len(r["title"]) > 40 else r["title"]
        print(f"{ratio:>7}  {comp:>15}  {r['location_eligible']:>7}  {r['degree_flag']:>9}  "
              f"{r['company'][:18]:<18} {title:<40}  {r['url']}")


def cmd_show(args: argparse.Namespace) -> None:
    conn = db.connect(Path(args.db))
    _print_queue(conn, args.top)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="jobber")
    p.add_argument("--db", default=str(db.DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="fetch all boards, score, store")
    h.add_argument("--top", type=int, default=20, help="print top N after harvest")
    h.set_defaults(func=cmd_harvest)

    s = sub.add_parser("show", help="print the ranked queue")
    s.add_argument("--top", type=int, default=30)
    s.set_defaults(func=cmd_show)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
