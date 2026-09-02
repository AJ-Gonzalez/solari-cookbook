"""Quick company reputation checks via public search snippets.

Deliberately lightweight (a slice of the DD method): a Glassdoor rating
guess + adverse-news snippets per company, stored in the reputation
table. Snippets are search-engine excerpts, not primary research — treat
as a triage signal, and run the full DD workflow (dd/ folder) for any
company that matters. DuckDuckGo's HTML endpoint is used because it
tolerates programmatic queries better than most; failures are recorded,
never silently skipped.
"""
import html
import re
import sqlite3
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                    "Gecko/20100101 Firefox/130.0"}

RATING_RE = re.compile(r"(\d\.\d)\s*(?:out of 5|/5|/ 5|stars)")


def _ddg(query: str, timeout: int = 20) -> str | None:
    url = ("https://html.duckduckgo.com/html/?q="
           + urllib.parse.quote(query))
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return None


def snippets(html_text: str, limit: int = 6) -> list[str]:
    out = []
    for m in re.finditer(
            r'class="result__snippet"[^>]*>(.*?)</a>', html_text, re.S):
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = html.unescape(re.sub(r"\s+", " ", t)).strip()
        if t and t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def check_company(company: str) -> dict:
    """Returns {rating, reviews, adverse, sources, status}."""
    display = company.replace("_", " ").replace("-", " ").strip().title()
    rating = reviews = None
    adverse: list[str] = []
    sources: list[str] = []

    h = _ddg(f'"{display}" glassdoor rating out of 5 reviews')
    if h:
        sources.append("duckduckgo:glassdoor")
        for snip in snippets(h):
            m = RATING_RE.search(snip)
            if m and rating is None:
                rating = float(m.group(1))
            rm = re.search(r"([\d,]+)\s+reviews", snip)
            if rm and reviews is None:
                reviews = int(rm.group(1).replace(",", ""))

    time.sleep(4)
    h = _ddg(f'"{display}" (layoffs OR lawsuit OR scandal OR controversy) 2026')
    if h:
        sources.append("duckduckgo:adverse")
        adverse = snippets(h, limit=4)

    status = "ok" if sources else "failed"
    return {"rating": rating, "reviews": reviews,
            "adverse": adverse, "sources": sources, "status": status}


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reputation (
            company    TEXT PRIMARY KEY,
            rating     REAL,
            reviews    INTEGER,
            signals    TEXT,
            status     TEXT NOT NULL DEFAULT 'pending',
            checked_at TEXT
        )""")
    conn.commit()


def save(conn: sqlite3.Connection, company: str, result: dict) -> None:
    import json
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO reputation (company, rating, reviews, signals, status, checked_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(company) DO UPDATE SET
            rating=excluded.rating, reviews=excluded.reviews,
            signals=excluded.signals, status=excluded.status,
            checked_at=excluded.checked_at
        """,
        (company.lower(), result.get("rating"), result.get("reviews"),
         json.dumps(result.get("adverse", [])), result.get("status", "ok"),
         now),
    )
    conn.commit()


def pending_companies(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT company FROM jobs "
        "WHERE company NOT IN (SELECT company FROM reputation) "
        "ORDER BY company")]


def run_queue(conn: sqlite3.Connection, sleep_s: int = 8) -> int:
    """Check every company missing a reputation row. Returns count done."""
    done = 0
    for company in pending_companies(conn):
        result = check_company(company)
        save(conn, company, result)
        done += 1
        print(f"  {company}: rating={result.get('rating')} "
              f"adverse={len(result.get('adverse', []))} "
              f"status={result['status']}", flush=True)
        time.sleep(sleep_s)
    return done
