"""Tests for source parsers, run against inline fixtures (no network)."""
import unittest
import xml.etree.ElementTree as ET

from src.jobber.criteria import load_criteria
from src.jobber.rank import enrich
from src.jobber.sources import (arbeitnow, ashby, greenhouse, himalayas,
                                hn_whoishiring, jobicy, lever, remoteok,
                                remotive, themuse, workingnomads, wwr)

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

class Remotive(unittest.TestCase):
    def test_parse_salary_text_and_location(self):
        raw = [{
            "id": 2091101,
            "url": "https://remotive.com/remote-jobs/sdev/x-2091101",
            "title": "Senior Backend Engineer",
            "company_name": "Lemon.io",
            "candidate_required_location": "LATAM, Europe, USA, Canada",
            "salary": "$100k - $140k",
            "description": "<p>Build APIs.</p><h2>Requirements</h2><ul><li>Go</li></ul>",
        }, {"00-warning": "legal"}]
        rows = _score(remotive.parse(raw))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_job_id"], "2091101")
        self.assertEqual(r["company"], "Lemon.io")
        self.assertEqual(r["comp_currency"], "USD")
        self.assertEqual(r["comp_min"], 100000)
        self.assertEqual(r["comp_max"], 140000)
        self.assertEqual(r["workplace"], "Remote")
        self.assertEqual(r["location_eligible"], "yes")

    def test_description_comp_fallback(self):
        raw = [{
            "id": 1, "title": "Backend Engineer", "company_name": "Acme",
            "candidate_required_location": "Worldwide",
            "salary": "", "description": "<p>Pays $120,000 - $150,000.</p>",
        }]
        r = remotive.parse(raw)[0]
        self.assertEqual(r["comp_min"], 120000)
        self.assertEqual(r["comp_max"], 150000)


class Jobicy(unittest.TestCase):
    def test_parse_yearly_comp(self):
        raw = [{
            "id": 152397,
            "url": "https://jobicy.com/jobs/152397-director-sales-engineering",
            "jobTitle": "Director, Sales Engineering",
            "companyName": "Veeam Software",
            "jobGeo": "USA",
            "jobDescription": "<p>Lead the team.</p>",
            "salaryMin": 219600, "salaryMax": 468800,
            "salaryCurrency": "USD", "salaryPeriod": "yearly",
        }]
        rows = _score(jobicy.parse(raw))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["comp_min"], 219600)
        self.assertEqual(r["comp_max"], 468800)
        self.assertEqual(r["comp_currency"], "USD")
        self.assertEqual(r["comp_confidence"], "listed")
        self.assertEqual(r["location"], "USA")

    def test_monthly_period_not_trusted_as_annual(self):
        raw = [{
            "id": 1, "jobTitle": "Engineer", "companyName": "Acme",
            "jobGeo": "Worldwide",
            "salaryMin": 18000, "salaryMax": 22000,
            "salaryCurrency": "USD", "salaryPeriod": "monthly",
        }]
        r = jobicy.parse(raw)[0]
        self.assertIsNone(r["comp_min"])
        self.assertEqual(r["comp_confidence"], "unknown")


class Arbeitnow(unittest.TestCase):
    def test_parse_remote_flag_and_text_comp(self):
        raw = [{
            "slug": "backend-engineer-429045",
            "company_name": "Founders Factory",
            "title": "Founding Lead Engineer",
            "remote": True,
            "url": "https://www.arbeitnow.com/jobs/x",
            "location": "Berlin",
            "description": "<h1>Role</h1><p>Salary: $130,000 - $160,000.</p>",
        }, {
            "slug": "onsite-1", "company_name": "Shop", "title": "Barista",
            "remote": False, "url": "https://www.arbeitnow.com/jobs/y",
            "location": "Berlin", "description": "<p>Coffee.</p>",
        }]
        rows = arbeitnow.parse(raw)
        self.assertEqual(rows[0]["workplace"], "Remote")
        self.assertEqual(rows[0]["comp_min"], 130000)
        self.assertIsNone(rows[1]["workplace"])
        self.assertIsNone(rows[1]["comp_min"])


class Himalayas(unittest.TestCase):
    def test_parse_annual_comp_and_restrictions(self):
        raw = [{
            "title": "Strategic Account Executive",
            "companyName": "Kong",
            "minSalary": 140000, "maxSalary": 180000,
            "currency": "USD", "salaryPeriod": "annual",
            "locationRestrictions": ["United Kingdom"],
            "applicationLink":
                "https://himalayas.app/companies/kong/jobs/strategic-account-executive",
        }, {
            "title": "Engineer", "companyName": "Acme",
            "minSalary": 3000, "maxSalary": 4000,
            "currency": "USD", "salaryPeriod": "monthly",
            "locationRestrictions": [],
            "applicationLink": "https://himalayas.app/companies/acme/jobs/engineer",
        }]
        rows = himalayas.parse(raw)
        self.assertEqual(rows[0]["source_job_id"], "strategic-account-executive")
        self.assertEqual(rows[0]["comp_min"], 140000)
        self.assertEqual(rows[0]["comp_currency"], "USD")
        self.assertEqual(rows[0]["location"], "United Kingdom")
        self.assertIsNone(rows[1]["comp_min"])
        self.assertEqual(rows[1]["comp_confidence"], "unknown")

class TheMuse(unittest.TestCase):
    def test_parse(self):
        raw = [{
            "id": 18054997,
            "name": "Senior Backend Engineer",
            "contents": "<p>Great role.</p><p>Salary: $140,000 - $180,000.</p>",
            "locations": [{"name": "Seattle, WA"}, {"name": "Remote"}],
            "refs": {"landing_page":
                     "https://www.themuse.com/jobs/cleanharbors/x-ff84b8"},
            "company": {"id": 15000557, "short_name": "cleanharbors",
                        "name": "Clean Harbors"},
        }, {"model_type": "junk"}]
        rows = _score(themuse.parse(raw))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_job_id"], "18054997")
        self.assertEqual(r["company"], "Clean Harbors")
        self.assertEqual(r["comp_min"], 140000)
        self.assertEqual(r["comp_max"], 180000)
        self.assertEqual(r["location"], "Seattle, WA; Remote")
        self.assertEqual(r["url"],
                         "https://www.themuse.com/jobs/cleanharbors/x-ff84b8")


class WWR(unittest.TestCase):
    @staticmethod
    def _item(title, region, description, link):
        item = ET.Element("item")
        for tag, value in [("title", title), ("region", region),
                           ("description", description), ("link", link)]:
            ET.SubElement(item, tag).text = value
        return item

    def test_parse_company_title_split(self):
        raw = [self._item(
            "Proxify AB: Senior Ruby Developer",
            "Anywhere in the World",
            '<p><strong>URL:</strong> '
            '<a href="http://career.proxify.io">http://career.proxify.io'
            '</a></p><p>Salary: $90,000 - $120,000.</p>',
            "https://weworkremotely.com/remote-jobs/proxify-senior-ruby")]
        rows = wwr.parse(raw)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["company"], "Proxify AB")
        self.assertEqual(r["title"], "Senior Ruby Developer")
        self.assertEqual(r["source_job_id"], "proxify-senior-ruby")
        self.assertEqual(r["workplace"], "Remote")
        self.assertTrue(r["description"].startswith(
            "Company site: http://career.proxify.io"))
        self.assertEqual(r["comp_min"], 90000)

    def test_no_colon_falls_back_to_full_title(self):
        raw = [self._item("Just A Title", "USA", "<p>text</p>",
                          "https://weworkremotely.com/remote-jobs/x")]
        r = wwr.parse(raw)[0]
        self.assertEqual(r["company"], "")
        self.assertEqual(r["title"], "Just A Title")


class WorkingNomads(unittest.TestCase):
    def test_parse(self):
        raw = [{
            "id": 1826864,
            "url": "https://www.workingnomads.com/job/go/1826864/",
            "title": "Agentic Python Engineer",
            "company_name": "Evaboot",
            "description": "<p>REMOTE | Full-time | $70-120K USD</p>",
            "location": "WORLDWIDE",
            "category_name": "Development",
        }]
        rows = _score(workingnomads.parse(raw))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_job_id"], "1826864")
        self.assertEqual(r["company"], "Evaboot")
        self.assertEqual(r["comp_min"], 70000)
        self.assertEqual(r["comp_max"], 120000)
        self.assertEqual(r["workplace"], "Remote")


class HNWhoIsHiring(unittest.TestCase):
    def test_parse_pipe_convention(self):
        raw = [{
            "objectID": 41771000,
            "comment_text":
                "Acme Corp | Senior Backend Engineer | Remote (LATAM) | "
                "$150-200k&lt;p&gt;We build things.&lt;/p&gt;",
        }, {
            "objectID": 41771001, "comment_text": None,
        }, {
            "objectID": 41771002,
            "comment_text": "Onsite Robotics | Field Tech | Austin TX",
        }]
        rows = hn_whoishiring.parse(raw)
        self.assertEqual(len(rows), 2)
        r = rows[0]
        self.assertEqual(r["company"], "Acme Corp")
        self.assertEqual(r["title"], "Senior Backend Engineer")
        self.assertEqual(r["location"], "Remote (LATAM), $150-200k")
        self.assertEqual(r["comp_min"], 150000)
        self.assertEqual(r["comp_max"], 200000)
        self.assertEqual(r["workplace"], "Remote")
        self.assertEqual(r["url"],
                         "https://news.ycombinator.com/item?id=41771000")
        self.assertEqual(rows[1]["workplace"], None)
        self.assertEqual(rows[1]["company"], "Onsite Robotics")
        self.assertEqual(rows[1]["title"], "Field Tech")


if __name__ == "__main__":
    unittest.main()
