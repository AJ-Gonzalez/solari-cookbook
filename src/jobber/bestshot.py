"""Best-shot queue: resume-seeded fit, repost dedup, per-company cap.

Pipeline (design from 2026-09-04):
  gates  — hard_block=0, location_eligible != 'no', status in window;
           eligibility runs BEFORE scoring because a perfect-cosine job
           criteria.toml rejects is a wasted application, not a lead.
  fit    — TF-IDF cosine between resume seed and each JD, reusing
           similar.py tokenization/scoring so vocabulary handling lives
           in one place. Focus tokens from criteria [bestshot] are seeded
           at title weight to steer fit toward direction, not history.
  boost  — titles containing a priority phrase get score * priority_boost;
           cosine under-ranks titles with little shared vocabulary.
  dedup  — reposts across boards collapse (same normalized title, or
           intra-company cosine >= REPOST_COSINE); keeps the higher-fit,
           then newer-last_seen variant.
  cap    — top N distinct roles per company, then global fit ranking.

  viable — needs_human rows demoted (NEEDS_HUMAN_PENALTY) but kept, with
           their latest apply_runs gap labels attached; screening-flagged
           rows demoted (SCREENING_PENALTY), never hidden. Both show in
           the payload so the human decides with full information.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import similar
from .criteria import Criteria
from .eligibility import location_eligible
from .gates import screening_signals

REPOST_COSINE = 0.7  # reposts share near-identical JDs; distinct roles don't

# Viability demotions (stage 4). Both are multiplicative on the boosted
# score, never filters: needs_human jobs still surface (with their gap
# labels) because banking the answers pulls them up the queue, and
# screening-flagged jobs stay visible for an informed human choice.
NEEDS_HUMAN_PENALTY = 0.5
SCREENING_PENALTY = 0.8


def seed_counts(resume_text: str, focus: list[str]) -> Counter:
    counts = similar._tokens("", resume_text or "")
    for phrase in focus:
        for tok in similar._TOKEN.findall(phrase.lower()):
            counts[tok] += 3
    return counts


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


_LEGAL_FORM = re.compile(
    r"\s+(inc|llc|corp|ltd|gmbh|co|incorporated|limited)\.?$", re.I)


def _norm_company(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).strip()
    # One trailing legal form is noise ("SAPSOL Technologies Inc." vs
    # "SAPSOL"); two would eat real names ("Amazon com").
    return _LEGAL_FORM.sub("", n).strip()


def bestshot(
    conn,
    resume_text: str,
    criteria: Criteria,
    per_company: int = 2,
    min_fit: float = 0.06,
    limit: int = 40,
    statuses: tuple[str, ...] = ("new", "queued", "needs_human"),
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT rowid, source, company, title, url, location,
               location_eligible,
               comp_min, comp_max, comp_currency, status,
               first_seen, last_seen, description
        FROM jobs
        WHERE hard_block = 0 AND location_eligible != 'no'
          AND status IN (%s)
        """ % ",".join("?" * len(statuses)),
        statuses).fetchall()
    # TEMPORARY: HN "who is hiring" rows carry no ATS form, so batch apply
    # burns a browser cycle per row and lands no_form. Out until HN rows
    # get a form path.
    rows = [r for r in rows if r["source"] != "hnwhoishiring"]
    if not rows:
        return []

    # 'unknown' eligibility gets a second look: job titles carry reliable
    # geo ("Premium Support Engineer (London)") that the location field
    # missed at harvest time. Explicit yes/no stored values are trusted.
    rows = [r for r in rows
            if r["location_eligible"] != "unknown" or location_eligible(
                (r["location"] or "") + " " + (r["title"] or ""),
                criteria) == "unknown"]
    if not rows:
        return []

    seed = seed_counts(resume_text, criteria.bestshot_focus)
    docs = {r["rowid"]: similar._tokens(r["title"], r["description"])
            for r in rows}
    idf = similar.corpus_idf(docs)
    scores = similar.cosine_scores(seed, docs, idf)

    kept = []
    for r in rows:
        fit = scores.get(r["rowid"], 0.0)
        if fit < min_fit:
            continue
        title_low = (r["title"] or "").lower()
        penalty = 1.0
        if r["status"] == "needs_human":
            penalty *= NEEDS_HUMAN_PENALTY
        screening = screening_signals(
            (r["title"] or "") + "\n" + (r["description"] or ""))
        if screening:
            penalty *= SCREENING_PENALTY
        fit_boosted = fit * criteria.bestshot_priority_boost if any(
            p in title_low for p in criteria.bestshot_priority) else fit
        boosted = fit_boosted * penalty
        kept.append({
            "rowid": r["rowid"], "source": r["source"],
            "company": r["company"],
            "title": r["title"], "url": r["url"], "location": r["location"],
            "location_eligible": r["location_eligible"],
            "comp_min": r["comp_min"], "comp_max": r["comp_max"],
            "comp_currency": r["comp_currency"], "status": r["status"],
            "fit": round(fit, 4), "score": round(boosted, 4),
            "penalty": round(penalty, 2), "screening": screening,
            "last_seen": r["last_seen"],
            "_counts": docs[r["rowid"]],
            "_cokey": _norm_company(r["company"]),
        })
    if not kept:
        return []

    # Latest gap labels for needs_human rows, so the human sees exactly
    # what the answer bank is missing before deciding to bank them.
    nh_ids = [r["rowid"] for r in kept if r["status"] == "needs_human"]
    gaps_by_row: dict = {}
    if nh_ids:
        for g in conn.execute(
                "SELECT job_rowid, gaps FROM apply_runs WHERE job_rowid "
                "IN (%s) ORDER BY started_at" % ",".join("?" * len(nh_ids)),
                nh_ids):
            gaps_by_row[g["job_rowid"]] = json.loads(g["gaps"])
    for r in kept:
        r["gaps"] = gaps_by_row.get(r["rowid"], [])
    # Group by company, collapse reposts, cap distinct roles.
    by_co: dict[str, list[dict]] = defaultdict(list)
    for r in kept:
        by_co[r["_cokey"]].append(r)

    capped: list[dict] = []
    for group in by_co.values():
        # two-pass stable sort: score desc, ties newest last_seen first
        group.sort(key=lambda r: r["last_seen"], reverse=True)
        group.sort(key=lambda r: -r["score"])
        seen: list[dict] = []
        for cand in group:
            keeper = None
            for k in seen:
                if (_norm_title(cand["title"]) == _norm_title(k["title"])
                        or similar.cosine_pair(
                            cand["_counts"], k["_counts"], idf)
                        >= REPOST_COSINE):
                    keeper = k
                    break
            if keeper is not None:
                keeper["reposts"] += 1
                continue
            cand["reposts"] = 0
            seen.append(cand)
            if len(seen) == per_company:
                break
        capped.extend(seen)

    capped.sort(key=lambda r: -r["score"])
    for r in capped:
        r.pop("_counts", None)
        r.pop("_cokey", None)
    return capped[:limit]
