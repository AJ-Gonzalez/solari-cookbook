"""Ashby public job-board API.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true
Public, unauthenticated JSON. Compensation is structured (comp_raw);
eligibility spans primary + secondary locations.
"""
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"


def fetch(token: str) -> dict:
    return http_json(LIST_URL.format(token=token))


def parse(raw: dict, token: str) -> list[dict]:
    out = []
    for j in raw.get("jobs") or []:
        if not j.get("isListed", True):
            continue
        locations = [j.get("location") or ""]
        locations += [s.get("location", "") for s in j.get("secondaryLocations") or []]
        location = " | ".join(loc for loc in locations if loc)
        out.append(make_row(
            source="ashby",
            source_job_id=str(j.get("id", "")),
            company=token,
            title=j.get("title", ""),
            url=j.get("jobUrl", ""),
            location=location,
            workplace=j.get("workplaceType"),
            description=strip_html(j.get("descriptionHtml") or ""),
            comp_raw=j.get("compensation"),
        ))
    return out
