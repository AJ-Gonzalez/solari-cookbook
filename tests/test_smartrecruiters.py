"""Tests for the SmartRecruiters source parser (fixtures, no network)."""
import unittest

from src.jobber.criteria import load_criteria
from src.jobber.rank import enrich
from src.jobber.sources import smartrecruiters

C = load_criteria()


def _score(rows):
    rows = [r for r in rows if C.title_matches(r["title"])]
    enrich(rows, C)
    return rows


class SmartRecruiters(unittest.TestCase):
    def test_parse_with_details(self):
        rows = smartrecruiters.parse(
            {"content": [{
                "id": "9001",
                "name": "Customer Success Engineer",
                "remote": True,
                "location": {"city": "", "region": "", "country": "Mexico"},
            }]},
            token="Wizeline",
            details={"9001": {"description":
                              "<p>Salary: $60,000 - $80,000 USD</p>"
                              "<p>Requirements: 2+ years Python</p>"}},
        )
        rows = _score(rows)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["company"], "Wizeline")
        self.assertEqual(r["comp_min"], 60000)
        self.assertIn("Mexico", r["location"])
        self.assertTrue(r["url"].startswith("https://jobs.smartrecruiters.com/Wizeline/"))

    def test_parse_without_details(self):
        rows = smartrecruiters.parse(
            {"content": [{"id": "9002", "name": "Backend Engineer",
                          "remote": True,
                          "location": {"country": "United States"}}]},
            token="acme", details=None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "")
        self.assertEqual(rows[0]["comp_confidence"], "unknown")


if __name__ == "__main__":
    unittest.main()
