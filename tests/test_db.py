"""Tests for SQLite storage: schema, upsert dedupe, status preservation."""
import tempfile
import unittest
from pathlib import Path

from src.jobber import db


def _row(job_id="1", company="acme", status=None):
    return {
        "source": "greenhouse", "source_job_id": job_id, "company": company,
        "title": "Backend Developer", "url": "https://example.com/1",
        "location": "Remote", "workplace": None, "description": "desc",
        "comp_min": 100000, "comp_max": 120000, "comp_currency": "USD",
        "comp_confidence": "parsed", "location_eligible": "unknown",
        "qual_score": 3.0, "degree_flag": "none", "ratio": 36666.7,
    }


class Db(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.conn = db.connect(Path(self.tmp.name))

    def tearDown(self):
        self.conn.close()
        Path(self.tmp.name).unlink()

    def test_upsert_dedupes(self):
        db.upsert_jobs(self.conn, [_row()], "2026-09-02T10:00:00+00:00")
        db.upsert_jobs(self.conn, [_row()], "2026-09-02T11:00:00+00:00")
        rows = self.conn.execute("SELECT * FROM jobs").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["last_seen"], "2026-09-02T11:00:00+00:00")

    def test_manual_status_survives_reharvest(self):
        db.upsert_jobs(self.conn, [_row()], "2026-09-02T10:00:00+00:00")
        self.conn.execute("UPDATE jobs SET status='queued'")
        db.upsert_jobs(self.conn, [_row()], "2026-09-02T11:00:00+00:00")
        status = self.conn.execute("SELECT status FROM jobs").fetchone()[0]
        self.assertEqual(status, "queued")

    def test_answers_roundtrip(self):
        self.conn.execute(
            "INSERT INTO answers (question, answer, kind, updated_at) VALUES (?,?,?,?)",
            ("years_of_python", "6", "text", "2026-09-02"),
        )
        a = self.conn.execute("SELECT answer FROM answers WHERE question=?",
                              ("years_of_python",)).fetchone()[0]
        self.assertEqual(a, "6")


if __name__ == "__main__":
    unittest.main()
