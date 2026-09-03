"""Remotive public API. Every listing is remote by definition.

Endpoint: https://remotive.com/api/remote-jobs — one GET, no key, no
pagination. `candidate_required_location` is the real eligibility
statement (like RemoteOK's); `salary` is free text ("$100k - $120k"),
so it goes through comp.from_text with the description as fallback.
"""
from ..comp import from_text
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://remotive.com/api/remote-jobs"


def fetch(token: str | None = None) -> list:
    return http_json(LIST_URL).get("jobs") or []


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for j in raw or []:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        comp = from_text(j.get("salary") or "")
        if not comp:
            comp = from_text(strip_html(j.get("description") or ""))
        out.append(make_row(
            source="remotive",
            source_job_id=str(j["id"]),
            company=strip_html(j.get("company_name") or ""),
            title=strip_html(j.get("title") or ""),
            url=j.get("url") or "",
            location=j.get("candidate_required_location") or "",
            workplace="Remote",
            description=strip_html(j.get("description") or ""),
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
