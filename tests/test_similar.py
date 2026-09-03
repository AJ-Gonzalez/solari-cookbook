"""Tests for similar-role matching (in-memory DB, deterministic)."""
import tempfile
import unittest
from pathlib import Path

from src.jobber import db
from src.jobber.similar import find_similar

def _row(rowid_source, title, description, **kw):
    return {
        "source": "test", "source_job_id": rowid_source, "company": kw.get(
            "company", "Acme"),
        "title": title, "url": "https://x/", "location": "Remote",
        "workplace": "Remote", "description": description,
        "comp_min": None, "comp_max": None, "comp_currency": None,
        "comp_confidence": "unknown", "comp_raw": None,
        "location_eligible": "unknown", "qual_score": 0,
        "degree_flag": "unknown", "ratio": None,
    }

class Similar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite3")
        rows = [
            _row("1", "Senior Backend Engineer (Go)",
                 "<p>Build distributed systems in Go and Kubernetes. "
                 "Postgres, gRPC, AWS.</p>"),
            _row("2", "Backend Engineer - Go",
                 "<p>Golang microservices on Kubernetes, Postgres, AWS. "
                 "Distributed systems at scale.</p>"),
            _row("3", "Senior Product Designer",
                 "<p>Figma, user research, design systems, prototyping. "
                 "You will run workshops with stakeholders.</p>"),
            _row("4", "DevOps Engineer",
                 "<p>Kubernetes and AWS infrastructure, Terraform, Go "
                 "automation. CI/CD pipelines.</p>"),
            _row("5", "Blocked Platform Engineer",
                 "<p>Go Kubernetes Postgres</p>", company="Gated Co"),
        ]
        db.upsert_jobs(self.conn, rows, "2026-09-02T00:00:00+00:00")
        # Row 5 is hard-blocked: must never appear in results.
        self.conn.execute("UPDATE jobs SET hard_block=1 WHERE source_job_id='5'")
        self.conn.commit()

    def tearDown(self):
        self.tmp.cleanup()
        self.conn.close()

    def _rowid(self, source_job_id):
        return self.conn.execute(
            "SELECT rowid FROM jobs WHERE source_job_id=?",
            (source_job_id,)).fetchone()[0]

    def test_similar_ranks_same_domain_first(self):
        hits = find_similar(self.conn, self._rowid("1"))
        top_ids = [h["rowid"] for h in hits[:2]]
        # Go/backend roles (1's kin) must outrank the designer role.
        go_row = self._rowid("2")
        designer_row = self._rowid("3")
        self.assertIn(go_row, top_ids)
        self.assertGreater(
            next(h["score"] for h in hits if h["rowid"] == go_row),
            next(h["score"] for h in hits if h["rowid"] == designer_row))

    def test_self_excluded(self):
        rid = self._rowid("1")
        self.assertNotIn(rid, [h["rowid"] for h in find_similar(self.conn, rid)])

    def test_hard_blocked_never_surface(self):
        hits = find_similar(self.conn, self._rowid("1"))
        self.assertNotIn(self._rowid("5"), [h["rowid"] for h in hits])

    def test_missing_rowid_returns_empty(self):
        self.assertEqual(find_similar(self.conn, 999999), [])

    def test_dissimilar_corpus_returns_empty(self):
        # Seed has no token overlap with anything -> no hits.
        self.conn.execute(
            "UPDATE jobs SET title='Zzz', description='qqq www eee' "
            "WHERE source_job_id='3'")
        self.conn.commit()
        hits = find_similar(self.conn, self._rowid("3"))
        self.assertTrue(all(h["rowid"] != self._rowid("3") for h in hits))


if __name__ == "__main__":
    unittest.main()
