"""Company knowledge: what each employer does, from Wikipedia.

Free, keyless enrichment via the Wikimedia REST APIs:
- search: https://en.wikipedia.org/w/rest.php/v1/search/page?q=...&limit=1
- summary: https://en.wikipedia.org/api/rest_v1/page/summary/{title}

Stored in the `companies` table keyed by lowercased company name so
dashboard details and reports can join on it. Not every employer has a
notable Wikipedia page — misses are recorded with summary=NULL so we
don't re-query them every run.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .sources.base import HEADERS

_SEARCH = "https://en.wikipedia.org/w/rest.php/v1/search/page?q={}&limit=5"
_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
# Extract must read like a business, not a common noun or sponsored
# event ("Litmus" the dye, "Fleetio 200" the race, "Creative Force" the
# racehorse whose "increases" tripped a substring match).
_IS_COMPANY_RE = re.compile(
    r"\b(company|inc\.?|corporation|software|business|headquartered|"
    r"startup|provider|platform|technology)\b", re.I)


def _get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except Exception:
        return None


def clean_company(name: str) -> str:
    """Strip noise that breaks wiki search: legal suffixes, parentheses."""
    return re.sub(r"\b(inc|llc|ltd|corp|co|gmbh|plc)\b\.?$|[()]",
                  "", name.lower(), flags=re.I).strip(" .,-")


def fetch_summary(company: str) -> tuple[str, str] | None:
    """Returns (summary, source_url) or None if nothing notable found."""
    q = urllib.parse.quote(clean_company(company))
    hits = (_get_json(_SEARCH.format(q)) or {}).get("pages") or []
    if not hits:
        return None
    # Common nouns collide: "Litmus" the company vs the dye, "Fleetio" vs
    # a NASCAR race. Prefer explicitly company-disambiguated titles; else
    # accept an exact clean-name match; anything else is a wrong answer,
    # which is worse than no answer.
    target = clean_company(company)
    ranked = sorted(
        hits,
        key=lambda h: (
            any(s in h.get("title", "").lower()
                for s in ("(company)", "(software)", "(business)")),
            clean_company(h.get("title", "")) == target,
        ),
        reverse=True)
    title = ranked[0].get("title", "")
    if not title or target not in clean_company(title):
        return None
    body = _get_json(_SUMMARY.format(urllib.parse.quote(title)))
    if not body or body.get("type") == "disambiguation":
        return None
    extract = (body.get("extract") or "").strip()
    if not extract:
        return None
    # Entity check: the extract must read like a business, not a common
    # noun or sponsored event ("Litmus" the dye, "Fleetio 200" the race).
    if not _IS_COMPANY_RE.search(extract):
        return None
    url = body.get("content_urls", {}).get("desktop", {}).get("page", "")
    return extract, url


def enrich_missing(conn, limit: int = 50, sleep_s: float = 1.0) -> int:
    """Look up unchecked companies; returns how many got summaries."""
    rows = conn.execute(
        """
        SELECT DISTINCT lower(j.company) AS name FROM jobs j
        WHERE lower(j.company) NOT IN (SELECT name FROM companies)
        LIMIT ?
        """, (limit,)).fetchall()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    done = 0
    for r in rows:
        found = fetch_summary(r["name"])
        summary, url = found if found else (None, None)
        conn.execute(
            "INSERT OR REPLACE INTO companies "
            "(name, summary, source_url, source, checked_at) "
            "VALUES (?, ?, ?, 'wikipedia', ?)",
            (r["name"], summary, url, now))
        conn.commit()
        done += 1 if summary else 0
        time.sleep(sleep_s)
    return done


def get_summary(conn, company: str) -> str | None:
    row = conn.execute("SELECT summary FROM companies WHERE name = ?",
                       (company.lower(),)).fetchone()
    return row["summary"] if row else None
