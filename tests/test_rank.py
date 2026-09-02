"""Tests for scoring: qualification load, degree flags, ratio, enrichment."""
import unittest

from src.jobber.criteria import load_criteria
from src.jobber.rank import degree_flag, enrich, qual_score, ratio

C = load_criteria()

REQUIREMENTS = """About the role

You will build things.

Requirements
- 3+ years of Python
- Experience with SQL databases
- Comfortable with ambiguity
- Written communication skills

Nice to have
- Docker
"""


class QualScore(unittest.TestCase):
    def test_counts_bullets_in_requirements_section(self):
        # 4 bullets + one "years" mention.
        self.assertEqual(qual_score(REQUIREMENTS), 5.0)

    def test_no_section_falls_back_to_bullet_count_capped(self):
        text = "\n".join(f"- item {i}" for i in range(9))
        self.assertEqual(qual_score(text), 5.0)

    def test_empty_is_zero(self):
        self.assertEqual(qual_score(""), 0.0)


class DegreeFlag(unittest.TestCase):
    def test_required(self):
        self.assertEqual(degree_flag("Bachelor's degree required"), "required")

    def test_or_equivalent(self):
        self.assertEqual(degree_flag("Degree or equivalent experience"), "required")

    def test_preferred(self):
        self.assertEqual(degree_flag("BS in CS preferred"), "preferred")

    def test_none(self):
        self.assertEqual(degree_flag("no formal education mentioned"), "none")

    def test_empty(self):
        self.assertEqual(degree_flag(""), "none")


class Ratio(unittest.TestCase):
    def test_comp_per_qualification(self):
        self.assertEqual(ratio(120000, 160000, "USD", 5.0, "none", C), 28000.0)

    def test_below_floor_is_zero(self):
        self.assertEqual(ratio(20000, 30000, "USD", 5.0, "none", C), 0.0)

    def test_unknown_comp_is_none(self):
        self.assertIsNone(ratio(None, None, None, 5.0, "none", C))

    def test_non_usd_is_unknown(self):
        self.assertIsNone(ratio(50000, 60000, "EUR", 5.0, "none", C))

    def test_degree_required_penalized(self):
        plain = ratio(120000, 120000, "USD", 5.0, "none", C)
        penal = ratio(120000, 120000, "USD", 5.0, "required", C)
        self.assertAlmostEqual(penal, plain * 0.75)


class Enrich(unittest.TestCase):
    def test_fills_derived_fields_and_drops_comp_raw(self):
        rows = [{
            "source": "ashby", "source_job_id": "1", "company": "x",
            "title": "Backend Developer", "url": "u",
            "location": "Remote - Worldwide", "workplace": "Remote",
            "description": REQUIREMENTS,
            "comp_min": None, "comp_max": None, "comp_currency": None,
            "comp_confidence": "unknown",
            "comp_raw": {"summaryComponents": [
                {"compensationType": "Salary", "currencyCode": "USD",
                 "minValue": 144000, "maxValue": 144000, "interval": "1 YEAR"},
            ]},
        }]
        enrich(rows, C)
        r = rows[0]
        self.assertEqual(r["location_eligible"], "yes")
        self.assertEqual(r["comp_min"], 144000)
        self.assertEqual(r["comp_confidence"], "listed")
        self.assertNotIn("comp_raw", r)
        self.assertIs(r["ratio"] is not None, True)

    def test_parses_comp_from_description_for_text_sources(self):
        rows = [{
            "source": "greenhouse", "source_job_id": "2", "company": "x",
            "title": "Python Developer", "url": "u",
            "location": "Remote, Mexico", "workplace": None,
            "description": "Pays $90,000 - $110,000\nRequirements\n- 2+ years Python",
            "comp_min": None, "comp_max": None, "comp_currency": None,
            "comp_confidence": "unknown",
        }]
        enrich(rows, C)
        self.assertEqual(rows[0]["comp_min"], 90000)
        self.assertEqual(rows[0]["comp_confidence"], "parsed")


if __name__ == "__main__":
    unittest.main()
