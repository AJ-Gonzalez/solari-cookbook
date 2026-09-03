"""Tests for batch apply orchestration and screening signals."""
import tempfile
import unittest
from pathlib import Path

from src.jobber import db
from src.jobber.batch import Cohort, record_outcome, select_cohort
from src.jobber.gates import screening_signals


def _row(job_id, title, ratio, eligible="yes", company="Acme"):
    return {
        "source": "test", "source_job_id": job_id, "company": company,
        "title": title, "url": f"https://x/{job_id}", "location": "Remote",
        "workplace": "Remote", "description": "Go Kubernetes Postgres",
        "comp_min": 100000, "comp_max": 150000, "comp_currency": "USD",
        "comp_confidence": "listed", "comp_raw": None,
        "location_eligible": eligible, "qual_score": 3.0,
        "degree_flag": "none", "ratio": ratio,
    }


class CohortSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite3")
        db.upsert_jobs(self.conn, [
            _row("a", "Senior Backend Engineer", 300),
            _row("b", "Mid-level Developer", 250),
            _row("c", "Midlevel Platform Developer", 200),
            _row("d", "Junior Developer", 150, eligible="no"),
            _row("e", "Staff Engineer", 100),
        ], "2026-09-02T00:00:00+00:00")

    def tearDown(self):
        self.tmp.cleanup()
        self.conn.close()

    def test_seniority_and_ratio_order(self):
        rows = select_cohort(self.conn, Cohort(seniority="mid", limit=10))
        # rank.enrich isn't run; seniority classification is on title.
        ids = [r["source_job_id"] for r in rows]
        self.assertIn("b", ids)
        self.assertNotIn("e", ids)  # staff

    def test_ineligible_excluded_by_default(self):
        rows = select_cohort(self.conn, Cohort(limit=10))
        self.assertNotIn("d", [r["source_job_id"] for r in rows])

    def test_query_filter(self):
        rows = select_cohort(self.conn, Cohort(query="platform", limit=10))
        self.assertEqual([r["source_job_id"] for r in rows], ["c"])

    def test_limit(self):
        rows = select_cohort(self.conn, Cohort(limit=2))
        self.assertEqual(len(rows), 2)


class OutcomeRecording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite3")
        db.upsert_jobs(self.conn, [_row("a", "Developer", 100)],
                       "2026-09-02T00:00:00+00:00")
        self.rid = self.conn.execute(
            "SELECT rowid FROM jobs").fetchone()[0]

    def tearDown(self):
        self.tmp.cleanup()
        self.conn.close()

    def test_status_map_and_run_record(self):
        for outcome, status in [("submitted", "applied"), ("ready", "staged"),
                                ("gaps", "needs_human"), ("no_form", None)]:
            record_outcome(self.conn, self.rid, outcome, ["Phone"],
                           "2026-09-03T00:00:00+00:00")
            row = self.conn.execute(
                "SELECT status FROM jobs WHERE rowid=?", (self.rid,)).fetchone()
            if status:
                self.assertEqual(row["status"], status)
        runs = self.conn.execute(
            "SELECT outcome, gaps FROM apply_runs ORDER BY started_at"
        ).fetchall()
        self.assertEqual([r["outcome"] for r in runs],
                         ["submitted", "ready", "gaps", "no_form"])
        self.assertEqual(runs[2]["gaps"], '["Phone"]')


class ScreeningSignals(unittest.TestCase):
    def test_detects_markers(self):
        text = ("We use HireVue for one-way video interviews and a "
                "HackerRank assessment.")
        self.assertIn("hirevue", screening_signals(text))
        self.assertIn("one-way video", screening_signals(text))
        self.assertIn("assessment", screening_signals(text))

    def test_clean_text_has_no_signals(self):
        self.assertEqual(screening_signals("Build APIs with Go and Postgres."),
                         [])

    def test_ai_screening_phrase(self):
        self.assertIn("ai screening",
                      screening_signals("Our AI screening reviews your resume"))


if __name__ == "__main__":
    unittest.main()
