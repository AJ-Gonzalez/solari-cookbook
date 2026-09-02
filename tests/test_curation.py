"""Tests for queue curation: status changes, ranked query filters."""
import tempfile
import unittest
from pathlib import Path

from src.jobber import db


def _row(job_id, ratio, eligible="unknown", comp_min=100000, currency="USD"):
    return {
        "source": "greenhouse", "source_job_id": job_id, "company": "acme",
        "title": "Backend Developer", "url": "https://example.com/" + job_id,
        "location": "Remote", "workplace": None, "description": "d",
        "comp_min": comp_min, "comp_max": comp_min, "comp_currency": currency,
        "comp_confidence": "parsed", "location_eligible": eligible,
        "qual_score": 3.0, "degree_flag": "none", "ratio": ratio,
    }


class Curation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.conn = db.connect(Path(self.tmp.name))
        db.upsert_jobs(self.conn, [
            _row("a", 100.0, eligible="yes"),
            _row("b", 300.0, eligible="unknown"),
            _row("c", 200.0, eligible="no"),
            _row("d", 50.0, eligible="yes", currency="EUR"),
            _row("e", None, eligible="yes"),
        ], "2026-09-02T10:00:00+00:00")

    def tearDown(self):
        self.conn.close()
        Path(self.tmp.name).unlink()

    def _rowids(self):
        return {r["source_job_id"]: r["rowid"] for r in
                self.conn.execute("SELECT rowid, source_job_id FROM jobs")}

    def test_ratio_desc_unknown_comp_last_eligibility_filtered(self):
        rows = db.ranked_rows(self.conn)
        ids = [r["source_job_id"] for r in rows]
        self.assertEqual(ids[0], "b")          # highest ratio
        self.assertNotIn("c", ids)             # location_eligible=no filtered
        self.assertEqual(ids[-1], "e")         # unknown comp ranks last
        self.assertIn("d", ids)                # EUR keeps its stored ratio
        self.assertEqual([r["source_job_id"] for r in rows if r["ratio"] is None], ["e"])

    def test_status_filter(self):
        rowid = self._rowids()["a"]
        db.set_status(self.conn, rowid, "hidden")
        ids = [r["source_job_id"] for r in db.ranked_rows(self.conn)]
        self.assertNotIn("a", ids)
        ids_all = [r["source_job_id"] for r in
                   db.ranked_rows(self.conn, statuses=("hidden",))]
        self.assertEqual(ids_all, ["a"])

    def test_status_survives_reharvest(self):
        rowid = self._rowids()["a"]
        db.set_status(self.conn, rowid, "queued")
        db.upsert_jobs(self.conn, [_row("a", 100.0, eligible="yes")], "2026-09-02T11:00:00+00:00")
        self.assertEqual(self.conn.execute(
            "SELECT status FROM jobs WHERE source_job_id='a'").fetchone()[0], "queued")

    def test_set_status_rejects_invalid(self):
        self.assertFalse(db.set_status(self.conn, 1, "banana"))

    def test_set_status_missing_row(self):
        self.assertFalse(db.set_status(self.conn, 99999, "queued"))


if __name__ == "__main__":
    unittest.main()
