"""Seniority classification from job titles.

Buckets (per AJ's taxonomy): junior, mid, senior, staff, c-suite.
Leadership titles (vp/director/head of) land in c-suite — the closest
bucket for "who's the job reporting to" filtering. Checked in descending
seniority order so "Senior Staff" resolves to staff, not senior.
"""
import re

_C_SUITE = re.compile(
    r"\b(chief|c[- ]?level|c[eto]o|vp\b|vice[- ]president|head of|director)\b", re.I)
_STAFF = re.compile(r"\b(staff|principal|architect|distinguished)\b", re.I)
_SENIOR = re.compile(r"\b(senior|sr\.?|lead)\b", re.I)
_JUNIOR = re.compile(
    r"\b(junior|jr\.?|entry[- ]?level|graduate|intern|apprentice|associate)\b", re.I)

LEVELS = ["junior", "mid", "senior", "staff", "c-suite"]


def classify(title: str) -> str:
    t = title or ""
    if _C_SUITE.search(t):
        return "c-suite"
    if _STAFF.search(t):
        return "staff"
    if _SENIOR.search(t):
        return "senior"
    if _JUNIOR.search(t):
        return "junior"
    return "mid"
