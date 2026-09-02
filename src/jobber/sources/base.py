"""HTTP helper + normalized row construction shared by all source parsers."""
import json
import urllib.request
from typing import Any

HEADERS = {
    # Polite identification; these are public, unauthenticated endpoints.
    "User-Agent": "jobber/0.1 (personal job search; python-urllib)"
}


def http_json(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def make_row(
    *,
    source: str,
    source_job_id: str,
    company: str,
    title: str,
    url: str,
    location: str,
    workplace: str | None = None,
    description: str = "",
    comp_min: int | None = None,
    comp_max: int | None = None,
    comp_currency: str | None = None,
    comp_confidence: str = "unknown",
    comp_raw: Any = None,
) -> dict:
    return {
        "source": source,
        "source_job_id": str(source_job_id),
        "company": company,
        "title": title,
        "url": url,
        "location": location,
        "workplace": workplace,
        "description": description,
        "comp_min": comp_min,
        "comp_max": comp_max,
        "comp_currency": comp_currency,
        "comp_confidence": comp_confidence,
        "comp_raw": comp_raw,
    }
