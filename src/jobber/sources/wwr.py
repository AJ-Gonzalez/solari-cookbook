"""We Work Remotely RSS feeds. Every listing is remote by definition.

Feeds: https://weworkremotely.com/categories/<category>.rss — no key,
no pagination (current postings only, ~100 per feed). Titles are
"Company: Role" — split on the first colon. The apply flow is two-hop
(RSS links to the WWR job page; the real application lives there), so
the stored URL is the WWR page itself; the company-site URL from the
description's "URL:" line is prepended for later resolution.
"""
import re
import urllib.request
import xml.etree.ElementTree as ET

from ..comp import from_text
from .base import HEADERS, make_row
from .htmltext import strip_html

CATEGORIES = [
    "remote-programming-jobs",
    "remote-devops-sysadmin-jobs",
]
# First "URL: <a ...>" anchor in the raw description = company site.
_COMPANY_URL = re.compile(r'URL:.*?<a href="([^"]+)"', re.I | re.S)

def fetch(token: str | None = None) -> list:
    out = []
    for cat in CATEGORIES:
        url = f"https://weworkremotely.com/categories/{cat}.rss"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            out.extend(ET.parse(resp).getroot().findall(".//item"))
    return out


def parse(raw: list, token: str | None = None) -> list[dict]:
    out = []
    for item in raw or []:
        if not isinstance(item, ET.Element):
            continue
        def text(tag):
            return (item.findtext(tag) or "").strip()
        title_full = text("title")
        company, sep, role = title_full.partition(": ")
        if not sep:
            company, role = "", title_full
        raw_description = text("description")
        m = _COMPANY_URL.search(raw_description)
        description = strip_html(raw_description)
        if m:
            description = f"Company site: {m.group(1)}\n\n{description}"
        comp = from_text(description)
        link = text("link")
        out.append(make_row(
            source="wwr",
            source_job_id=link.rsplit("/", 1)[-1] or title_full,
            company=company,
            title=role,
            url=link,
            location=text("region"),
            workplace="Remote",
            description=description,
            comp_min=comp[0] if comp else None,
            comp_max=comp[1] if comp else None,
            comp_currency=comp[2] if comp else None,
            comp_confidence=comp[3] if comp else "unknown",
        ))
    return out
