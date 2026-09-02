"""Scoring: qualification load, degree flags, and the comp/qual ratio.

The ratio is the user's stated preference: least qualifications for the
highest compensation ranks first. Qualification load is approximated by
counting bullets in the requirements section plus "N years" mentions —
crude, but consistent, and the human curates the queue anyway.
"""
import re

from .comp import from_ashby, from_text
from .criteria import Criteria
from .eligibility import location_eligible

_HEADING = re.compile(
    r"^\W*(requirements?|qualifications?|what you.?ll need|what we.?re looking for"
    r"|about you|who you are|must.?haves?|nice to haves?|skills required"
    r"|experience required|your profile)\b",
    re.I,
)
_BULLET = re.compile(r"^\s*(?:[-*\u2022\u2013]|\d+[.)])\s+\S")
_YEARS = re.compile(r"\d+\+?\s*years", re.I)
_DEGREE = re.compile(r"\b(bachelor'?s?|master'?s?|ph\.?d|b\.?s\.?c?|b\.?a\.|m\.?s\.?|degree)\b", re.I)


def qual_score(text: str) -> float:
    if not text:
        return 0.0
    lines = text.splitlines()
    start = next(
        (i + 1 for i, ln in enumerate(lines) if _HEADING.match(ln.strip())), None
    )
    if start is None:
        bullets = sum(1 for ln in lines if _BULLET.match(ln))
        return float(max(1, min(bullets, 5)))
    count = 0
    for ln in lines[start:]:
        if _HEADING.match(ln.strip()):
            break
        if _BULLET.match(ln):
            count += 1
    years = len(_YEARS.findall(text))
    return float(max(1, min(count, 15) + min(years, 3)))


def degree_flag(text: str) -> str:
    if not text or not _DEGREE.search(text):
        return "none"
    for m in _DEGREE.finditer(text):
        window = text[max(0, m.start() - 120):m.end() + 120].lower()
        if re.search(r"required|must|or equivalent", window):
            return "required"
    return "preferred"


def ratio(comp_min, comp_max, currency, qual, degree, criteria: Criteria) -> float | None:
    """comp midpoints per required bullet. None = unknown comp (ranks last),
    0.0 = comp below the floor."""
    if comp_min is None or currency != "USD":
        return None
    mid = (comp_min + (comp_max or comp_min)) / 2
    if mid < criteria.comp_min_usd:
        return 0.0
    if degree == "required":
        mid *= criteria.degree_penalty
    return round(mid / max(qual, 1.0), 1)


def enrich(rows: list[dict], criteria: Criteria) -> None:
    """Fill derived fields (eligibility, qual, degree, ratio) in place.
    Ashby rows carry structured comp; everything else parses description text."""
    for r in rows:
        r["location_eligible"] = location_eligible(r.get("location"), criteria)
        text = r.get("description") or ""
        r["qual_score"] = qual_score(text)
        r["degree_flag"] = degree_flag(text)
        if r.get("comp_min") is None and r.get("source") == "ashby":
            parsed = from_ashby(r.get("comp_raw") or {})
            if parsed:
                r["comp_min"], r["comp_max"], r["comp_currency"], r["comp_confidence"] = parsed
        elif r.get("comp_min") is None:
            parsed = from_text(text)
            if parsed:
                r["comp_min"], r["comp_max"], r["comp_currency"], r["comp_confidence"] = parsed
        r["ratio"] = ratio(
            r.get("comp_min"), r.get("comp_max"), r.get("comp_currency"),
            r["qual_score"], r["degree_flag"], criteria,
        )
        # comp_raw is a source-shape artifact, never stored.
        r.pop("comp_raw", None)
