"""Hacker News "Ask HN: Who is hiring?" via the public Algolia API.

Endpoints (no key):
- GET https://hn.algolia.com/api/v1/search_by_date
      ?query="Ask HN: Who is hiring?"&tags=story  -> monthly threads
- GET https://hn.algolia.com/api/v1/items/{story_id} -> comment tree

Only the newest monthly thread is harvested; its top-level comments
ARE the postings. HN convention is "Company | Role | Location | comp"
pipe-delimited first lines, so the title line is split and location
takes the trailing segments (comp text in there is harmless —
eligibility only reacts to explicit accept/reject tokens). On-site
posts exist: workplace=Remote only when the text says so.
"""
import re
from urllib.parse import quote

from ..comp import from_text
from .base import http_json, make_row
from .htmltext import strip_html

API = "https://hn.algolia.com/api/v1"
_THREAD = re.compile(r"^Ask HN: Who is hiring\? \(")


def fetch(token: str | None = None) -> list:
    hits = http_json(
        f"{API}/search_by_date?query={quote('\"Ask HN: Who is hiring?\"')}"
        "&tags=story&hitsPerPage=5"
    ).get("hits") or []
    story = next((h for h in hits
                  if _THREAD.match(h.get("title") or "")), None)
    if story is None:
        return []
    tree = http_json(f"{API}/items/{story['objectID']}")
    return tree.get("children") or []


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for c in raw or []:
        if not isinstance(c, dict) or not (c.get("comment_text") or c.get("text")):
            continue
        cid = str(c.get("objectID") or c.get("id") or "")
        text = strip_html(c.get("comment_text") or c.get("text") or "")
        first = (text.splitlines() or [""])[0].strip()
        segs = [s.strip() for s in first.split("|") if s.strip()]
        if len(segs) >= 2:
            company, title = segs[0], segs[1]
            location = ", ".join(segs[2:])[:200]
        else:
            company, title, location = "", first, ""
        remote = re.search(r"\bremote\b", text, re.I) is not None
        comp = from_text(text)
        out.append(make_row(
            source="hnwhoishiring",
            source_job_id=cid,
            company=company,
            title=title[:200],
            url=f"https://news.ycombinator.com/item?id={cid}",
            location=location,
            workplace="Remote" if remote else None,
            description=text,
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
