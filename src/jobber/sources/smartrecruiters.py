"""SmartRecruiters public API harvester.

Endpoints (no auth):
- GET https://api.smartrecruiters.com/v1/companies/{token}/postings
      -> {"totalFound": N, "content": [{id, name, location: {city, country},
         remote: bool, releasedDate, ...}]}
- GET .../postings/{id} -> adds "description" (plain text) per posting

Details are fetched per posting (bounded by max_details) because the list
response carries no description. Token = the company id in
jobs.smartrecruiters.com/{token}/... — see `jobber addtoken`.
"""
import json
import urllib.request

from ..comp import from_text
from .base import make_row
from .htmltext import strip_html

BASE = "https://api.smartrecruiters.com/v1/companies/{token}"
UA = {"User-Agent": "jobber/0.1 (personal job search; python-urllib)"}


def _get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def parse(raw: dict, token: str, details: dict | None = None) -> list[dict]:
    """Parse listings; `details` maps posting id -> detail response.
    Live harvest (fetch_all) fetches details directly."""
    out = []
    for j in raw.get("content") or []:
        pid = j.get("id")
        description = ""
        if details and pid in details:
            d = details[pid]
            description = strip_html(
                d.get("description")
                or (d.get("jobAd") or {}).get("description") or "")
        loc = j.get("location") or {}
        parts = [loc.get("city"), loc.get("region"), loc.get("country")]
        location = ", ".join(p for p in parts if p) or (
            "Remote" if j.get("remote") else "")
        remote = bool(j.get("remote")) or "remote" in location.lower()
        comp = from_text(description)
        out.append(make_row(
            source="smartrecruiters",
            source_job_id=str(pid or j.get("ref") or ""),
            company=token,
            title=j.get("name", ""),
            url=f"https://jobs.smartrecruiters.com/{token}/{pid}" if pid else "",
            location=location,
            workplace="Remote" if remote else None,
            description=description,
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out


def fetch_all(token: str, max_details: int = 50) -> list[dict]:
    base = BASE.format(token=token)
    listings = (_get(f"{base}/postings").get("content") or [])[:max_details]
    details = {}
    for j in listings:
        pid = j.get("id")
        if not pid:
            continue
        try:
            details[pid] = _get(f"{base}/postings/{pid}")
        except Exception:
            continue
    return parse({"content": listings}, token, details=details)


def fetch(token: str) -> list[dict]:
    """Source-contract entry point (same shape as the other harvesters)."""
    return fetch_all(token)
