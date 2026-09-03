"""Gate-question classification for application forms.

Location strings lie; application-form questions don't. A listing can say
"Remote" and still knock you out with "Do you live in the US or Canada?".
The scanner extracts question texts from the application form and matches
them against gate patterns; any hit means the human sees *why* a role may
not be truly global before spending an application on it.

Form HTML sources (proven 2026-09-02):
- greenhouse: server-rendered on the job page itself (plain HTTP).
- lever: server-rendered apply page (plain HTTP).
- ashby: JS-rendered — requires a real browser (Solari session).
"""
import re
import urllib.request

from .sources.base import HEADERS

GATE_PATTERNS: dict[str, list[str]] = {
    "residency": [
        r"united states or canada",
        r"live in (one of|the following|:)",
        r"are you currently located in",
        r"candidates? (?:in|located in|from) the united states",
        r"only open to",
        r"reside in",
    ],
    "relocation": [
        r"willing to relocate",
        r"relocate (?:to|near)",
        r"willing to move",
    ],
    "work_auth": [
        r"legally authorized to work",
        r"authorized to work in the united states",
        r"proof of (?:your )?(?:eligibility|authorization) to work",
    ],
    "sponsorship": [
        r"immigration sponsorship",
        r"require.*sponsorship",
        r"sponsorship for employment visa",
        r"now,? or in the future,? require",
    ],
    "onsite_or_hybrid": [
        r"days per week",
        r"from our .{0,40}office",
        r"from our .{0,40}hq",
    ],
    "clearance": [
        r"top secret|ts/?sci|security clearance",
        r"active .*clearance",
    ],
    "timezone": [
        r"time ?zone",
        r"hours (?:of|from) (?:cet|pt|est|gmt|utc)",
        r"overlap with",
    ],
    "age": [r"at least 18 years"],
}

_COMPILED = {
    cat: [re.compile(p, re.I) for p in pats]
    for cat, pats in GATE_PATTERNS.items()
}


def classify(questions: list[str]) -> dict[str, list[str]]:
    """Map gate category -> the questions that triggered it.
    Categories absent from the result = no gate found in that category."""
    gates: dict[str, list[str]] = {}
    for q in questions:
        for cat, patterns in _COMPILED.items():
            if any(p.search(q) for p in patterns):
                gates.setdefault(cat, []).append(q)
    return gates


def is_hard_block(gates: dict[str, list[str]]) -> bool:
    """Residency or relocation questions are near-certain rejections for a
    Mexico-based applicant; auth/sponsorship usually are too (no US visa
    sponsorship for remote-global roles). Timezone/onsite are soft signals."""
    return bool(set(gates) & {"residency", "relocation", "work_auth", "sponsorship"})


# Signals that a listing's pipeline screens resumes with automation.
# No public registry exists for this; these are the observable markers
# (named tools, one-way video interviews, assessments) in the listing's
# own text. Absence is weak evidence either way.
SCREENING_PATTERNS: dict[str, str] = {
    "hirevue": r"hirevue",
    "one-way video": r"one[- ]way (video|interview)|recorded (video|interview)",
    "video interview": r"video interview|virtual interview",
    "assessment": r"assessment|worksample|work sample|codility|hackerrank|"
                  r"codesignal|karat",
    "personality/psychometric": r"personality|psychometric|disc assessment|"
                                r"caliper|pymetrics",
    "ai screening": r"\bai[- ](screen|screening|resume|recruit)|"
                    r"automated (screen|screening|review|evaluation)|"
                    r"\bats\b (screen|filter)|applicant tracking",
    "game-based": r"game[- ]based|cognify|brainable",
}

_SCREENING_COMPILED = {k: re.compile(v, re.I)
                       for k, v in SCREENING_PATTERNS.items()}


def screening_signals(text: str) -> list[str]:
    """Categories of automated-screening markers found in listing text."""
    t = text or ""
    return [k for k, pat in _SCREENING_COMPILED.items() if pat.search(t)]

def extract_questions(html: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"<label[^>]*>(.*?)</label>", html, re.S):
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = re.sub(r"\s+", " ", t).strip().rstrip("*").strip()
        if len(t) > 1 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def fetch_questions(url: str, timeout: int = 30) -> list[str] | None:
    """Fetch a server-rendered application form and extract its questions.
    None = no form found at this URL (custom-hosted boards, redirects) or
    fetch failed — an inconclusive scan, never a pass."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        return None
    if "application--questions" not in html and "<form" not in html:
        return None
    questions = extract_questions(html)
    return questions or None


def scan_job(source: str, url: str, company: str, source_job_id: str):
    """Returns (questions | None, gates). None questions = inconclusive.
    Ashby needs a JS-rendering browser (Solari) and is not wired here yet."""
    if source == "greenhouse":
        questions = fetch_questions(
            f"https://job-boards.greenhouse.io/{company}/jobs/{source_job_id}"
        )
    elif source == "lever":
        questions = fetch_questions(url.rstrip("/") + "/apply")
    else:
        return None, {}
    if questions is None:
        return None, {}
    return questions, classify(questions)
