"""Location eligibility: remote + Mexico/global, per criteria tokens."""
import re

from .criteria import Criteria


def _hit(token: str, text: str) -> bool:
    # Short tokens ("us", "uk", "eu") need word boundaries: a substring
    # match would make "consult" or "russell" look like US listings.
    if len(token) <= 3:
        return re.search(rf"\b{re.escape(token)}\b", text) is not None
    return token in text


def location_eligible(text: str, criteria: Criteria) -> str:
    """Classify a location/eligibility string as 'yes', 'no', or 'unknown'.

    An explicit accept token (mexico/latam/worldwide/...) wins over reject
    tokens, so "Worldwide (US excluded)" stays eligible. Bare "Remote" with
    no region info stays 'unknown' for human review rather than a guess.
    """
    t = (text or "").lower()
    for r in criteria.loc_reject:
        if _hit(r, t):
            for a in criteria.loc_accept:
                if _hit(a, t):
                    return "yes"
            return "no"
    for a in criteria.loc_accept:
        if _hit(a, t):
            return "yes"
    return "unknown"
