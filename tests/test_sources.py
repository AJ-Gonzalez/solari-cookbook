"""Tests for source parsers, run against inline fixtures (no network)."""
import unittest

from src.jobber.criteria import load_criteria
from src.jobber.rank import enrich
from src.jobber.sources import ashby, greenhouse, lever, remoteok

C = load_criteria()


def _score(rows):
    rows = [r for r in rows if C.title_matches(r["title"])]
    enrich(rows, C)
    return rows


class Greenhouse(unittest.TestCase):
    def test_parse(self):
        raw = {"jobs": [{
            "id": 8503792002,
            "title": "Backend Engineer, Payments",
            "absolute_url": "https://job-boards.greenhouse.io/x/jobs/8503792002",
            "location": {"name": "Remote, Mexico"},
            "content": "<p>Salary: $90,000 - $110,000</p><h2>Requirements</h2>"
                       "<ul><li>2+ years Python</li><li>SQL</li></ul>",
        }]}
        rows = _score(greenhouse.parse(raw, "acme"))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_job_id"], "8503792002")
        self.assertEqual(r["comp_currency"], "USD")
        self.assertEqual(r["comp_min"], 90000)
        self.assertEqual(r["location_eligible"], "yes")
        self.assertEqual(r["qual_score"], 3.0)

    def test_recruiter_excluded(self):
        raw = {"jobs": [{"id": 1, "title": "Technical Recruiter",
                         "absolute_url": "u", "location": {"name": "Remote"},
                         "content": ""}]}
        self.assertEqual(len(_score(greenhouse.parse(raw, "acme"))), 0)


class Lever(unittest.TestCase):
    def test_parse_with_lists(self):
        raw = [{
            "id": "abc", "text": "Customer Success Engineer",
            "hostedUrl": "https://jobs.lever.co/acme/abc",
            "categories": {"location": "Remote, Mexico"},
            "workplaceType": "Remote",
            "descriptionPlain": "Join us\n\nRequirements\n- Support customers\n- 3+ years SQL",
            "lists": [{"content": [{"content": "Nice: REST APIs"}]}],
        }]
        rows = _score(lever.parse(raw, "acme"))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["workplace"], "Remote")
        self.assertEqual(r["location_eligible"], "yes")
        # 2 requirement bullets + 1 "years" mention + 1 appended list bullet.
        self.assertEqual(r["qual_score"], 4.0)


class Ashby(unittest.TestCase):
    def test_parse(self):
        raw = {"jobs": [{
            "id": "a759e035", "title": "Technical Writer",
            "jobUrl": "https://jobs.ashbyhq.com/acme/a759e035",
            "location": "Remote - Worldwide", "isRemote": True,
            "workplaceType": "Remote", "isListed": True,
            "descriptionHtml": "<h2>Requirements</h2><ul><li>2 years writing</li></ul>",
            "compensation": {"summaryComponents": [
                {"compensationType": "Salary", "currencyCode": "USD",
                 "minValue": 100000, "maxValue": 100000, "interval": "1 YEAR"},
            ]},
        }, {
            "id": "x2", "title": "Unlisted role", "isListed": False,
        }]}
        rows = _score(ashby.parse(raw, "acme"))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["comp_min"], 100000)
        self.assertEqual(r["comp_confidence"], "listed")
        self.assertEqual(r["location_eligible"], "yes")


class RemoteOK(unittest.TestCase):
    def test_parse_skips_legal_notice(self):
        raw = [
            {"legal": "API Terms of Service: link back please"},
            {"id": 1137253, "position": "Python Developer",
             "company": "Acme &amp; Co", "url": "https://remoteok.com/remote-jobs/1137253",
             "candidate_required_location": "Worldwide",
             "salary_min": 60000, "salary_max": 90000,
             "description": "<p>Requirements</p><ul><li>Python</li></ul>"},
        ]
        rows = _score(remoteok.parse(raw))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["company"], "Acme & Co")
        self.assertEqual(r["location_eligible"], "yes")
        self.assertEqual(r["comp_confidence"], "listed")


if __name__ == "__main__":
    unittest.main()
