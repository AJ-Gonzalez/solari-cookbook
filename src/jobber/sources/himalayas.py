"""Himalayas public API. Every listing is remote by definition.

Endpoint: https://himalayas.app/jobs/api — no key, server-fixed 20
per page, cursor pagination (limit param is ignored). The board holds
~100k listings across all categories, so harvesting is capped by page
count at the freshest slice; criteria filtering happens upstream.
Salary is structured min/max/currency with a period; only "annual" is
trusted, same reasoning as Jobicy's yearly check.
"""
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://himalayas.app/jobs/api"
MAX_PAGES = 60  # 20/page server-fixed -> freshest ~1,200 listings


def fetch(token: str | None = None) -> list:
    out, cursor, pages = [], None, 0
    while pages < MAX_PAGES:
        url = LIST_URL if cursor is None else f"{LIST_URL}?cursor={cursor}"
        body = http_json(url)
        jobs = body.get("jobs") or []
        out.extend(jobs)
        pages += 1
        cursor = body.get("nextCursor")
        if not cursor or not jobs:
            break
    return out


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for j in raw or []:
        if not isinstance(j, dict) or not j.get("applicationLink"):
            continue
        annual = (j.get("salaryPeriod") or "").lower() == "annual"
        comp_min = j.get("minSalary") if annual else None
        comp_max = j.get("maxSalary") if annual else None
        currency = j.get("currency") if annual else None
        listed = bool(comp_min or comp_max)
        out.append(make_row(
            source="himalayas",
            source_job_id=j["applicationLink"].rstrip("/").rsplit("/", 1)[-1],
            company=strip_html(j.get("companyName") or ""),
            title=strip_html(j.get("title") or ""),
            url=j.get("applicationLink") or "",
            location="; ".join(j.get("locationRestrictions") or []),
            workplace="Remote",
            description=strip_html(j.get("description") or ""),
            comp_min=int(comp_min) if comp_min else None,
            comp_max=int(comp_max) if comp_max else None,
            comp_currency=currency if listed else None,
            comp_confidence="listed" if listed else "unknown",
        ))
    return out
