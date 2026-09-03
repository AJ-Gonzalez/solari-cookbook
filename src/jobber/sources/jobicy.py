"""Jobicy public API. Every listing is remote by definition.

Endpoint: https://jobicy.com/api/v2/remote-jobs — one GET, no key,
200 per page (the board's full recent set). Structured salary fields
min/max/currency/period; only "yearly" periods are trusted — monthly
or hourly numbers would sail under the comp floor as if annual.
"""
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://jobicy.com/api/v2/remote-jobs?count=200"


def fetch(token: str | None = None) -> list:
    return http_json(LIST_URL).get("jobs") or []


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for j in raw or []:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        yearly = (j.get("salaryPeriod") or "").lower() == "yearly"
        comp_min = j.get("salaryMin") if yearly else None
        comp_max = j.get("salaryMax") if yearly else None
        currency = j.get("salaryCurrency") if yearly else None
        listed = bool(comp_min or comp_max)
        out.append(make_row(
            source="jobicy",
            source_job_id=str(j["id"]),
            company=strip_html(j.get("companyName") or ""),
            title=strip_html(j.get("jobTitle") or ""),
            url=j.get("url") or "",
            location=j.get("jobGeo") or "",
            workplace="Remote",
            description=strip_html(j.get("jobDescription") or ""),
            comp_min=int(comp_min) if comp_min else None,
            comp_max=int(comp_max) if comp_max else None,
            comp_currency=currency if listed else None,
            comp_confidence="listed" if listed else "unknown",
        ))
    return out
