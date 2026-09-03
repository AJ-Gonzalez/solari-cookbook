"""Workable public jobs API harvester.

Endpoint: POST https://apply.workable.com/api/v1/accounts/{token}/jobs
JSON body filters (all optional): {"remote": ["true"], "country": ["US"], ...}
Response: {"total": N, "results": [{id, title, shortlink, location: {city,
  country, ...}, ...}]}

Full job details (description, requirements) come from the same endpoint
with {"details": true} — fetch per-job only when needed to keep harvest
volume low. NOTE: token discovery is the bottleneck — a Workable subdomain
is the company slug in apply.workable.com/{subdomain}.
"""
import json
import urllib.request

from ..comp import from_text
from .base import make_row
from .htmltext import strip_html

JOBS_URL = "https://apply.workable.com/api/v1/accounts/{token}/jobs"
HEADERS_JSON = {
    "User-Agent": "jobber/0.1 (personal job search; python-urllib)",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def fetch(token: str) -> dict:
    body = json.dumps({}).encode()
    req = urllib.request.Request(
        JOBS_URL.format(token=token), data=body, headers=HEADERS_JSON,
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse(raw: dict, token: str) -> list[dict]:
    out = []
    for j in raw.get("results") or []:
        loc = j.get("location") or {}
        city = loc.get("city") or ""
        country = loc.get("country") or ""
        location = ", ".join(x for x in (city, country) if x) or (
            "Remote" if j.get("remote") else "")
        description = strip_html(j.get("description") or "")
        comp = from_text(description)
        out.append(make_row(
            source="workable",
            source_job_id=str(j.get("id", "")),
            company=token,
            title=j.get("title", ""),
            url=j.get("shortlink", "") or j.get("url", ""),
            location=location,
            workplace="Remote" if j.get("remote") else None,
            description=description,
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
