"""Lever public postings API.

Endpoint: https://api.lever.co/v0/postings/{token}?mode=json
Public, unauthenticated JSON. `descriptionPlain` is already plain text;
structured requirement bullets live in `lists`.
"""
from ..comp import from_text
from .base import http_json, make_row
from .htmltext import strip_html

LIST_URL = "https://api.lever.co/v0/postings/{token}?mode=json"


def fetch(token: str) -> list:
    return http_json(LIST_URL.format(token=token))


def parse(raw: list, token: str) -> list[dict]:
    out = []
    for j in raw or []:
        if not isinstance(j, dict):
            continue
        description = (j.get("descriptionPlain") or "").strip()
        bullets = []
        for lst in j.get("lists") or []:
            content = lst.get("content")
            if isinstance(content, list):
                # Some boards: [{"content": "text"}, ...]
                bullets.extend(
                    x.get("content", "") for x in content if isinstance(x, dict)
                )
            elif isinstance(content, str):
                # Other boards: one HTML blob per list.
                bullets.append(content)
        if bullets:
            # Append as list items so qual_score can count them.
            description = description + "\n\n" + "\n".join(
                f"- {strip_html(b)}" for b in bullets if b
            )
        comp = from_text(description)
        out.append(make_row(
            source="lever",
            source_job_id=str(j.get("id", "")),
            company=token,
            title=j.get("text", ""),
            url=j.get("hostedUrl", ""),
            location=(j.get("categories") or {}).get("location", ""),
            workplace=j.get("workplaceType"),
            description=description,
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
