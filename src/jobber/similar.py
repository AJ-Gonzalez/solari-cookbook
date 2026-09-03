"""Similar-role search: TF-IDF cosine over title + description tokens.

Stdlib-only, deliberately boring. Title tokens count triple (the title
carries intent; the description carries stack and domain). IDF is
computed over the stored corpus at query time — 3k docs is fast enough
that no index or cache is warranted. Excludes the seed row and
hard-blocked rows (gated listings never surface as suggestions).
"""
import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{2,}")

_STOP = frozenset("""
a an and are as at be but by for from has have in is it its job jobs
join looking new of on or our you your we with will work working team
role roles opportunity company us us-based about they their them this
that these those to was were who what when where why how all any can
could should would may might must not no nor so than then there here
more most other some such only own same too very just also both each
few had her his him she the their ours yours myself itself being been
am if because while during before after above below up down out off
over under again further once do does did doing have has had having
""".split())


def _tokens(title: str, description: str) -> Counter:
    counts = Counter()
    for tok in _TOKEN.findall((title or "").lower()):
        if tok not in _STOP:
            counts[tok] += 3  # title weight
    for tok in _TOKEN.findall((description or "").lower()):
        if tok not in _STOP:
            counts[tok] += 1
    return counts


def find_similar(conn, rowid: int, top: int = 12) -> list[dict]:
    """Return up to `top` jobs ranked by cosine similarity to `rowid`."""
    seed = conn.execute(
        "SELECT rowid, title, description FROM jobs WHERE rowid = ?",
        (rowid,)).fetchone()
    if seed is None:
        return []
    rows = conn.execute(
        """
        SELECT rowid, company, title, source, comp_min, comp_max,
               comp_currency, comp_confidence, location, location_eligible,
               status, description
        FROM jobs
        WHERE rowid != ? AND hard_block = 0
        """,
        (rowid,)).fetchall()

    docs = {r["rowid"]: _tokens(r["title"], r["description"]) for r in rows}
    seed_vec = _tokens(seed["title"], seed["description"])
    if not seed_vec:
        return []

    # IDF over the corpus actually present in this query (seed excluded).
    df = Counter()
    for counts in docs.values():
        for tok in counts:
            df[tok] += 1
    n = len(docs)
    idf = {t: math.log(1 + n / d) for t, d in df.items()}

    def weighted(counts: Counter) -> dict:
        return {t: c * idf[t] for t, c in counts.items() if t in idf}

    def norm(vec: dict) -> float:
        return math.sqrt(sum(v * v for v in vec.values())) or 1.0

    seed_w, seed_n = weighted(seed_vec), norm(weighted(seed_vec))
    scored = []
    for r in rows:
        vec = weighted(docs[r["rowid"]])
        if not vec:
            continue
        dot = sum(seed_w.get(t, 0.0) * w for t, w in vec.items())
        score = dot / (seed_n * norm(vec))
        if score > 0:
            scored.append({"rowid": r["rowid"], "score": round(score, 4),
                           **{k: r[k] for k in (
                               "company", "title", "source", "comp_min",
                               "comp_max", "comp_currency",
                               "comp_confidence", "location",
                               "location_eligible", "status")}})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top]
