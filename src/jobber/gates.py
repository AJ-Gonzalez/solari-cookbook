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
