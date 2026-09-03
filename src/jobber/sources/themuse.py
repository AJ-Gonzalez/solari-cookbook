"""The Muse public jobs API. Mixed board, heavy location filtering.

Endpoint: https://www.themuse.com/api/public/jobs — no key, 20 per
page, supports server-side category/level/location params. With the
Software Engineering category alone there are ~2,000 pages, so the
harvest is server-filtered by category and capped by page count.
External jobs expose only a Muse landing page (no apply URL in the
API); the landing page is stored and the real form is resolved later.
"""
from ..comp import from_text
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://www.themuse.com/api/public/jobs"
# Server-side category filter: "Software Engineering" is the relevant pool.
CATEGORY = "Software Engineering"
MAX_PAGES = 40  # 20/page -> freshest ~800 listings


def fetch(token: str | None = None) -> list:
    out = []
    for page in range(1, MAX_PAGES + 1):
        body = http_json(
            f"{LIST_URL}?page={page}&category={CATEGORY.replace(' ', '%20')}")
        results = body.get("results") or []
        out.extend(results)
        if page >= body.get("page_count", 0) or not results:
            break
    return out


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for j in raw or []:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        contents = strip_html(j.get("contents") or "")
        comp = from_text(contents)
        locations = [l.get("name", "") for l in j.get("locations") or []]
        out.append(make_row(
            source="themuse",
            source_job_id=str(j["id"]),
            company=(j.get("company") or {}).get("name", ""),
            title=j.get("name", ""),
            url=(j.get("refs") or {}).get("landing_page", ""),
            location="; ".join(filter(None, locations)),
            workplace=None,
            description=contents,
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
