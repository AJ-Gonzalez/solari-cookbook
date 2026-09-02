"""Greenhouse public board API.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Public, unauthenticated JSON; `content=true` inlines the description HTML.
"""
from ..comp import from_text
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


def fetch(token: str) -> dict:
    return http_json(LIST_URL.format(token=token))


def parse(raw: dict, token: str) -> list[dict]:
    out = []
    for j in raw.get("jobs") or []:
        description = strip_html(j.get("content") or "")
        comp = from_text(description)
        out.append(make_row(
            source="greenhouse",
            source_job_id=str(j.get("id", "")),
            company=token,
            title=j.get("title", ""),
            url=j.get("absolute_url", ""),
            location=(j.get("location") or {}).get("name", ""),
            description=description,
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
