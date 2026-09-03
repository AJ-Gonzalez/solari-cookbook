"""Tests for the Workable source parser (fixture-based, no network)."""
import unittest

from src.jobber.criteria import load_criteria
from src.jobber.rank import enrich
from src.jobber.sources import workable

C = load_criteria()


def _score(rows):
    rows = [r for r in rows if C.title_matches(r["title"])]
    enrich(rows, C)
    return rows


class Workable(unittest.TestCase):
    def test_parse(self):
        raw = {"results": [{
            "id": "A1B2C3",
            "title": "Backend Developer (Remote - LatAm)",
            "shortlink": "https://apply.workable.com/acme/j/A1B2C3",
            "remote": True,
            "location": {"city": "", "country": "Mexico"},
            "description": "<p>Salary: $70,000 - $90,000</p>"
                           "<h2>Requirements</h2><ul><li>2+ years Python</li></ul>",
        }]}
        rows = _score(workable.parse(raw, "acme"))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_job_id"], "A1B2C3")
        self.assertEqual(r["comp_min"], 70000)
        self.assertEqual(r["comp_currency"], "USD")
        self.assertEqual(r["location"], "Mexico")
        self.assertEqual(r["workplace"], "Remote")

    def test_empty_results(self):
        self.assertEqual(workable.parse({"results": []}, "acme"), [])


if __name__ == "__main__":
    unittest.main()
