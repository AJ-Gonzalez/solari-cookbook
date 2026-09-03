"""Compensation normalization.

v1 decisions (documented in DESIGN.md):
- Only USD figures are floor-checked. EUR/GBP/MXN are recorded as-is and
  rank as unknown-comp (conversion is a later problem, not a wrong-answer
  problem).
- Text-parsed comp assumes annual unless the adjacent text says MXN/pesos
  (a real trap: "$35,000 MXN" is monthly pesos, ~$2k USD).
- Structured (Ashby) comp annualizes by its interval field.
"""
import re

# $175K, $120,000 - $160,000, €50,000–60,000, USD 35,000
_RANGE = re.compile(
    r"(?P<cur>[$€£]|USD|EUR|GBP|MXN)\s?"
    r"(?P<lo>\d[\d,.]*)\s?(?P<k1>[kK])?"
    r"(?:\s*(?:[\u2013\u2014-]|to)\s*(?:[$€£]|USD|EUR|GBP|MXN)?\s*"
    r"(?P<hi>\d[\d,.]*)\s?(?P<k2>[kK])?)?"
)

_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP"}
_AFTER = {"USD": "USD", "EUR": "EUR", "GBP": "GBP", "MXN": "MXN"}

_ASHBY_INTERVAL = {"1 YEAR": 1, "1 MONTH": 12, "1 WEEK": 52, "1 DAY": 260}


def _num(raw: str, k: str | None) -> int | None:
    v = float(raw.replace(",", "").rstrip("."))
    if k:
        v *= 1000
    return int(v)


def _currency(match: re.Match, text: str) -> str:
    sym = match.group("cur")
    if sym in _SYMBOL:
        # "$35,000 MXN" trap: an explicit MXN/pesos mention right after wins.
        tail = text[match.end():match.end() + 14].lower()
        if re.search(r"mxn|pesos", tail):
            return "MXN"
        return _SYMBOL[sym]
    return _AFTER.get(sym, sym)


def _valid(v: int | None) -> bool:
    # Below 10k the number is almost certainly hourly/monthly, not annual.
    return v is not None and v >= 10_000


def from_text(text: str) -> tuple[int, int, str, str] | None:
    if not text:
        return None
    for m in _RANGE.finditer(text):
        # "$70-120K": one k-suffix on the range applies to both ends.
        k1, k2 = m.group("k1"), m.group("k2")
        if k2 and not k1:
            k1 = k2
        lo = _num(m.group("lo"), k1)
        hi_raw = m.group("hi")
        hi = _num(hi_raw, k2) if hi_raw else lo
        if _valid(lo) and _valid(hi):
            if lo > hi:
                lo, hi = hi, lo
            return lo, hi, _currency(m, text), "parsed"
    return None


def from_ashby(comp_obj: dict) -> tuple[int, int, str, str] | None:
    """Ashby structured compensation. Conservative: min tier wins for the
    floor (tiers vary by country), currency must be uniform to be used."""
    if not comp_obj:
        return None
    salaries = [
        c for c in comp_obj.get("summaryComponents", [])
        if c.get("compensationType") == "Salary" and c.get("minValue") is not None
    ]
    if not salaries:
        return None
    currencies = {c.get("currencyCode") for c in salaries}
    if len(currencies) != 1:
        return None
    currency = currencies.pop()
    if currency != "USD":
        return None
    factor = _ASHBY_INTERVAL.get(salaries[0].get("interval", ""), 1)
    if factor == 1 and salaries[0].get("interval", "") not in _ASHBY_INTERVAL:
        return None  # hourly or unknown periodicity: not trustworthy
    lo = min(int(c["minValue"]) for c in salaries) * factor
    hi = max(int(c.get("maxValue") or c["minValue"]) for c in salaries) * factor
    return lo, hi, "USD", "listed"
