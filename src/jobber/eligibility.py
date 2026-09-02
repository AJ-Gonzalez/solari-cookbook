"""Location eligibility: remote + Mexico/global, per criteria tokens."""
from .criteria import Criteria


def location_eligible(text: str, criteria: Criteria) -> str:
    """Classify a location/eligibility string as 'yes', 'no', or 'unknown'.

    An explicit accept token (mexico/latam/worldwide/...) wins over reject
    tokens, so "Worldwide (US excluded)" stays eligible. Bare "Remote" with
    no region info stays 'unknown' for human review rather than a guess.
    """
    t = (text or "").lower()
    for r in criteria.loc_reject:
        if r in t:
            for a in criteria.loc_accept:
                if a in t:
                    return "yes"
            return "no"
    for a in criteria.loc_accept:
        if a in t:
            return "yes"
    return "unknown"
