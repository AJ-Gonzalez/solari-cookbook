"""Answers bank: the human's reusable words for recurring form questions.

The application driver consults the bank before asking the human anything;
every answer the human dictates gets stored here and matched thereafter.
Matching is deliberately conservative: exact normalized match first, then
a containment match (stored question contained in the asked question or
vice versa) — fuzzy guessing on an application form is how wrong answers
get submitted under the human's name.
"""
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/whitespace — for match keys only."""
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class BankEntry:
    question: str
    answer: str
    kind: str | None


class AnswersBank:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def learn(self, question: str, answer: str, kind: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO answers (question, answer, kind, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(question) DO UPDATE SET
                answer=excluded.answer, kind=excluded.kind,
                updated_at=excluded.updated_at
            """,
            (question, answer, kind,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def lookup(self, question: str) -> BankEntry | None:
        """Exact normalized match, then containment match. None = ask.

        Containment needs a multi-word stored key (or a toggle seed):
        single generic words like "country" would otherwise inject their
        answer into every question containing that word.
        """
        q = normalize(question)
        if not q:
            return None
        row = self.conn.execute(
            "SELECT question, answer, kind FROM answers WHERE question = ?",
            (q,),
        ).fetchone()
        if row is None:
            rows = self.conn.execute(
                "SELECT question, answer, kind FROM answers"
            ).fetchall()
            for r in rows:
                rq = normalize(r["question"])
                broad = r["kind"] == "toggle"
                if rq and len(rq.split()) >= 2 and (rq in q or q in rq):
                    row = r
                    break
                if rq and broad and rq in q:
                    row = r
                    break
        if row is None:
            return None
        return BankEntry(row["question"], row["answer"], row["kind"])

    def all_entries(self) -> list[BankEntry]:
        rows = self.conn.execute(
            "SELECT question, answer, kind FROM answers ORDER BY question"
        ).fetchall()
        return [BankEntry(r["question"], r["answer"], r["kind"]) for r in rows]


def seed_from_file(bank: AnswersBank, path) -> int:
    """Load human-editable TOML seeds into the bank. File entries win over
    previously-learned sqlite answers (the file is the curated source).
    Format: [slug] with `question` and `answer` keys."""
    import tomllib

    p = Path(path)
    if not p.exists():
        return 0
    data = tomllib.loads(p.read_text())
    count = 0

    toggles = data.get("toggles", {})
    toggle_seeds = []
    if toggles.get("no_sponsorship"):
        toggle_seeds.append(("sponsorship", "No"))
    if toggles.get("no_relocation"):
        toggle_seeds.append(
            ("relocate", "No — I am not willing to relocate"))
    if toggles.get("no_clearance"):
        toggle_seeds.append(("clearance", "No"))
        toggle_seeds.append(("top secret", "No"))
    for q, a in toggle_seeds:
        bank.learn(q, a, kind="toggle")
        count += 1

    for section, values in data.items():
        if section == "toggles":
            continue
        q = values.get("question")
        a = values.get("answer")
        if q and a:
            bank.learn(q, a, kind="file")
            count += 1
    return count
