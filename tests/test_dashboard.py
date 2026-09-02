"""Tests for the dashboard's JSON payload queries."""
import tempfile
import unittest
from pathlib import Path

from src.jobber import db
from src.jobber.dashboard import _job_payload, _jobs_payload


class DashboardPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.conn = db.connect(Path(self.tmp.name))
        db.upsert_jobs(self.conn, [{
            "source": "greenhouse", "source_job_id": "a", "company": "acme",
            "title": "Backend Developer", "url": "u", "location": "Remote",
            "workplace": None, "description": "<p>hello</p>",
            "comp_min": 100000, "comp_max": 120000, "comp_currency": "USD",
            "comp_confidence": "parsed", "location_eligible": "unknown",
            "qual_score": 3.0, "degree_flag": "none", "ratio": 36666.7,
        }], "2026-09-02T10:00:00+00:00")

    def tearDown(self):
        self.conn.close()
        Path(self.tmp.name).unlink()

    def test_jobs_payload_has_safe_fields(self):
        rows = _jobs_payload(self.tmp.name)
        r = rows[0]
        self.assertEqual(r["rowid"], 1)
        self.assertEqual(r["comp_min"], 100000)
        # descriptions are served per-job, never in the queue payload
        self.assertNotIn("description", r)

    def test_job_payload_includes_description(self):
        r = _job_payload(self.tmp.name, 1)
        self.assertEqual(r["description"], "<p>hello</p>")
        self.assertIsNone(_job_payload(self.tmp.name, 999))


if __name__ == "__main__":
    unittest.main()
