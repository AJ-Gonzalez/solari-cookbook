"""Arbeitnow public API. Mixed board: remote and on-site EU jobs.

Endpoint: https://www.arbeitnow.com/api/job-board-api — no key, 175
per page, ordered by created_at, `?page=` to paginate. No salary
fields at all: comp is text-parsed from the description. `remote` is
per-listing, so workplace is only set when the flag says so.
"""
from ..comp import from_text
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://www.arbeitnow.com/api/job-board-api"
# Three pages ≈ 525 freshest listings; the criteria filter does the rest.
MAX_PAGES = 3


def fetch(token: str | None = None) -> list:
    out = []
    for page in range(1, MAX_PAGES + 1):
        body = http_json(f"{LIST_URL}?page={page}")
        data = body.get("data") or []
        out.extend(data)
        if len(data) < (body.get("meta") or {}).get("per_page", 175):
            break
    return out


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for j in raw or []:
        if not isinstance(j, dict) or not j.get("slug"):
            continue
        comp = from_text(strip_html(j.get("description") or ""))
        remote = bool(j.get("remote"))
        out.append(make_row(
            source="arbeitnow",
            source_job_id=str(j["slug"]),
            company=strip_html(j.get("company_name") or ""),
            title=strip_html(j.get("title") or ""),
            url=j.get("url") or "",
            location=j.get("location") or "",
            workplace="Remote" if remote else None,
            description=strip_html(j.get("description") or ""),
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
