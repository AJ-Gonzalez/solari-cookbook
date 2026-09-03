"""Working Nomads exposed jobs API. Every listing is remote by definition.

Endpoint: https://www.workingnomads.com/api/exposed_jobs/ — no key,
no pagination, the board's current set (~45 listings). Fields are
clean: company_name, location ("WORLDWIDE"), category_name, and a
description that usually carries the comp range in text.
"""
from ..comp import from_text
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://www.workingnomads.com/api/exposed_jobs/"


def fetch(token: str | None = None) -> list:
    return http_json(LIST_URL)


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for j in raw or []:
        if not isinstance(j, dict) or not j.get("title"):
            continue
        comp = from_text(strip_html(j.get("description") or ""))
        out.append(make_row(
            source="workingnomads",
            source_job_id=str(j.get("id") or j.get("url", "")),
            company=strip_html(j.get("company_name") or ""),
            title=strip_html(j.get("title") or ""),
            url=j.get("url") or "",
            location=j.get("location") or "",
            workplace="Remote",
            description=strip_html(j.get("description") or ""),
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
