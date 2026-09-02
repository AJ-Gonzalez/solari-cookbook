"""RemoteOK public API. Every listing is remote by definition.

Endpoint: https://remoteok.com/api
The first element is their legal notice, not a job. Structured USD salary
fields when published; `candidate_required_location` drives eligibility.
"""
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://remoteok.com/api"


def fetch(token: str | None = None) -> list:
    return http_json(LIST_URL)


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for j in raw or []:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        # candidate_required_location is the real eligibility statement;
        # fall back to the display location.
        location = j.get("candidate_required_location") or j.get("location") or ""
        comp_min = j.get("salary_min")
        comp_max = j.get("salary_max")
        comp_min = int(comp_min) if str(comp_min or "").isdigit() else None
        comp_max = int(comp_max) if str(comp_max or "").isdigit() else None
        out.append(make_row(
            source="remoteok",
            source_job_id=str(j.get("id", "")),
            company=strip_html(j.get("company") or ""),
            title=strip_html(j.get("position") or ""),
            url=j.get("url") or j.get("apply_url", ""),
            location=location,
            workplace="Remote",
            description=strip_html(j.get("description") or ""),
            comp_min=comp_min,
            comp_max=comp_max,
            comp_currency="USD" if comp_min or comp_max else None,
            comp_confidence="listed" if comp_min or comp_max else "unknown",
        ))
    return out
