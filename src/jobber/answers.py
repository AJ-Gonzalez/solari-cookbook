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
        """Exact normalized match, then containment match. None = ask."""
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
                if rq and (rq in q or q in rq):
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
    for section, values in data.items():
        q = values.get("question")
        a = values.get("answer")
        if q and a:
            bank.learn(q, a, kind="file")
            count += 1
    return count
