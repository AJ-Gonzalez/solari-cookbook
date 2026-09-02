"""SQLite storage: harvested jobs plus the human's answer bank.

The answers table exists from day one because the application driver
(next milestone) fills form fields from it; the schema is cheap to land
now and keeps the design coherent.
"""
import json
import sqlite3
from pathlib import Path

DEFAULT_DB = Path("jobber.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    source            TEXT NOT NULL,
    source_job_id     TEXT NOT NULL,
    company           TEXT NOT NULL,
    title             TEXT NOT NULL,
    url               TEXT NOT NULL,
    location          TEXT,
    workplace         TEXT,
    location_eligible TEXT NOT NULL DEFAULT 'unknown',
    comp_min          INTEGER,
    comp_max          INTEGER,
    comp_currency     TEXT,
    comp_confidence   TEXT NOT NULL DEFAULT 'unknown',
    description       TEXT,
    qual_score        REAL NOT NULL DEFAULT 0,
    degree_flag       TEXT NOT NULL DEFAULT 'unknown',
    ratio             REAL,
    status            TEXT NOT NULL DEFAULT 'new',
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    PRIMARY KEY (source, source_job_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_ratio ON jobs(ratio DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS answers (
    question   TEXT PRIMARY KEY,
    answer     TEXT NOT NULL,
    kind       TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reputation (
    company    TEXT PRIMARY KEY,
    rating     REAL,
    reviews    INTEGER,
    signals    TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    checked_at TEXT
);
 """


def _migrate(conn: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS never alters existing tables; add the
    # gate-scanner columns here when they're missing.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "gate_flags" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN gate_flags TEXT")
    if "hard_block" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN hard_block INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def upsert_jobs(conn: sqlite3.Connection, rows: list[dict], now: str) -> None:
    """Insert or refresh job rows. Never touches `status` or the gate
    columns: manual triage and scan results survive re-harvests."""
    for r in rows:
        conn.execute(
            """
            INSERT INTO jobs (source, source_job_id, company, title, url, location,
                workplace, location_eligible, comp_min, comp_max, comp_currency,
                comp_confidence, description, qual_score, degree_flag, ratio,
                first_seen, last_seen)
            VALUES (:source, :source_job_id, :company, :title, :url, :location,
                :workplace, :location_eligible, :comp_min, :comp_max, :comp_currency,
                :comp_confidence, :description, :qual_score, :degree_flag, :ratio,
                :now, :now)
            ON CONFLICT(source, source_job_id) DO UPDATE SET
                title=excluded.title,
                url=excluded.url,
                location=excluded.location,
                workplace=excluded.workplace,
                location_eligible=excluded.location_eligible,
                comp_min=excluded.comp_min,
                comp_max=excluded.comp_max,
                comp_currency=excluded.comp_currency,
                comp_confidence=excluded.comp_confidence,
                description=excluded.description,
                qual_score=excluded.qual_score,
                degree_flag=excluded.degree_flag,
                ratio=excluded.ratio,
                last_seen=excluded.last_seen
            """,
            {**r, "now": now},
        )
    conn.commit()


VALID_STATUSES = ("new", "queued", "hidden", "staged", "applied", "rejected")


def set_status(conn: sqlite3.Connection, rowid: int, status: str) -> bool:
    if status not in VALID_STATUSES:
        return False
    cur = conn.execute("UPDATE jobs SET status=? WHERE rowid=?", (status, rowid))
    conn.commit()
    return cur.rowcount > 0


def set_gate_result(conn: sqlite3.Connection, rowid: int, gates: dict) -> bool:
    """Store scan outcome. Empty gates = scanned clean; hard_block is
    derived and excludes the job from default queue views."""
    from .gates import is_hard_block

    cur = conn.execute(
        "UPDATE jobs SET gate_flags=?, hard_block=? WHERE rowid=?",
        (json.dumps(gates), int(is_hard_block(gates)), rowid),
    )
    conn.commit()
    return cur.rowcount > 0


def ranked_rows(
    conn: sqlite3.Connection,
    statuses: tuple[str, ...] = ("new", "queued"),
    eligible_only: bool = True,
    include_gated: bool = False,
):
    sql = (
        "SELECT rowid, * FROM jobs WHERE status IN (%s)"
        % ",".join("?" * len(statuses))
    )
    if not include_gated:
        sql += " AND hard_block=0"
    rows = conn.execute(sql, statuses).fetchall()
    if eligible_only:
        rows = [r for r in rows if r["location_eligible"] in ("yes", "unknown")]
    # ratio DESC, unknown-comp last
    return sorted(
        rows,
        key=lambda r: (r["ratio"] is not None, r["ratio"] or 0),
        reverse=True,
    )
