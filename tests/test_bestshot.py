import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.jobber import db
from src.jobber.bestshot import REPOST_COSINE, _norm_company, seed_counts
from src.jobber.bestshot import bestshot
from src.jobber.criteria import Criteria

C = Criteria(
    title_include=["engineer"], title_exclude=[],
    comp_min_usd=35000, degree_penalty=0.75,
    loc_accept=["worldwide"], loc_reject=["usa"],
    desc_exclude=[],
    bestshot_focus=["python"],
    bestshot_priority=["customer success"],
    bestshot_priority_boost=2.0,
)

RESUME = "Skills: python automation agentic systems LLM\n"


def _job(rowid, company, title, description, *, eligible="yes",
        status="new", hard_block=0, last_seen="2026-09-01"):
    return {
        "source": "test", "source_job_id": str(rowid),
        "company": company, "title": title,
        "url": f"https://example.com/{rowid}", "location": "Worldwide",
        "workplace": "remote", "location_eligible": eligible,
        "comp_min": 90000, "comp_max": 120000, "comp_currency": "USD",
        "comp_confidence": "high", "description": description,
        "qual_score": 5.0, "degree_flag": "none", "ratio": 100.0,
        "first_seen": last_seen, "last_seen": last_seen,
        "gate_flags": "{}", "hard_block": hard_block, "status": status,
    }


def _seed_db(jobs):
    conn = db.connect(":memory:")
    # :memory: needs an explicit rowid we control; insert directly.
    for j in jobs:
        cols = ", ".join(j.keys())
        marks = ", ".join(f":{k}" for k in j)
        rid = j["source_job_id"]
        conn.execute(
            f"INSERT INTO jobs (rowid, {cols}) VALUES ({rid}, {marks})", j)
    conn.commit()
    return conn


class Norm(unittest.TestCase):
    def test_company_legal_forms_collapse(self):
        self.assertEqual(_norm_company("SAPSOL Technologies Inc."),
                         _norm_company("sapsol technologies"))

    def test_seed_counts_weight_focus(self):
        c = seed_counts("python", ["agentic llm"])
        self.assertEqual(c["python"], 1)
        self.assertEqual(c["agentic"], 3)
        self.assertEqual(c["llm"], 3)


class Bestshot(unittest.TestCase):
    def setUp(self):
        self.jobs = [
            # strong fit, reposted across two boards (same title, same text)
            _job(1, "Acme Inc", "Senior Python Engineer",
                 "python automation LLM agents\n" * 20,
                 last_seen="2026-09-02"),
            _job(2, "Acme", "Senior Python Engineer",
                 "python automation LLM agents\n" * 20,
                 last_seen="2026-09-01"),
            # distinct role, weaker fit
            _job(3, "Acme", "Backend Python Engineer",
                 "python flask api services\n" * 10),
            # priority title: low shared vocabulary but boosted
            _job(4, "Beta Co", "Customer Success Engineer",
                 "support customers building python integrations\n" * 10),
            # higher raw cosine than job 4, no priority
            _job(5, "Beta Co", "Python Automation Engineer",
                 "python automation LLM agents pipelines\n" * 10),
            # gates: never scored
            _job(6, "Gamma", "Python Engineer", "python\n" * 30,
                 eligible="no"),
            _job(7, "Delta", "Python Engineer", "python\n" * 30,
                 hard_block=1),
            _job(8, "Epsilon", "Python Engineer", "python\n" * 30,
                 status="applied"),
        ]

    def test_gates_exclude_before_scoring(self):
        conn = _seed_db(self.jobs)
        try:
            out = bestshot(conn, RESUME, C, min_fit=0.0, limit=50)
            ids = {r["rowid"] for r in out}
            self.assertFalse({6, 7, 8} & ids)
        finally:
            conn.close()

    def test_repost_collapses_to_one_role(self):
        conn = _seed_db(self.jobs)
        try:
            out = bestshot(conn, RESUME, C, per_company=3, min_fit=0.0,
                           limit=50)
            acme = [r for r in out if r["rowid"] in (1, 2)]
            self.assertEqual(len(acme), 1)
            self.assertEqual(acme[0]["rowid"], 1)  # newest last_seen wins ties
            self.assertEqual(acme[0]["reposts"], 1)
        finally:
            conn.close()

    def test_unknown_location_gets_title_second_look(self):
        # location "London Office" parses as unknown at harvest time, but
        # the title carries the geo — bestshot must drop it. A genuinely
        # ambiguous "Distributed" posting stays in.
        from dataclasses import replace
        jobs = [
            _job(11, "Replit", "Premium Support Engineer",
                 "python automation support\n" * 10,
                 eligible="unknown"),
            _job(12, "Cloudflare", "Distributed Systems Engineer",
                 "python distributed systems\n" * 10,
                 eligible="unknown"),
        ]
        jobs[0]["location"] = "London Office"
        jobs[1]["location"] = "Distributed"
        crit = replace(C, loc_reject=["usa", "london"])
        conn = _seed_db(jobs)
        try:
            out = bestshot(conn, RESUME, crit, min_fit=0.0, limit=50)
            self.assertEqual([r["rowid"] for r in out], [12])
        finally:
            conn.close()

    def test_per_company_cap(self):
        conn = _seed_db(self.jobs)
        try:
            out = bestshot(conn, RESUME, C, per_company=1, min_fit=0.0,
                           limit=50)
            acme = [r for r in out if _norm_company(r["company"])
                    == "acme"]
            self.assertEqual(len(acme), 1)
        finally:
            conn.close()

    def test_priority_boost_reorders(self):
        # mechanism test: the boost must be able to reorder, independent
        # of any particular knob value — so the corpus gap (3.3x here) is
        # deliberately overwhelmed with a 4x boost.
        from dataclasses import replace
        conn = _seed_db(self.jobs)
        try:
            out = bestshot(conn, RESUME, replace(C, bestshot_priority_boost=4.0),
                           per_company=3, min_fit=0.0, limit=50)
            beta = {r["rowid"]: r for r in out if r["rowid"] in (4, 5)}
            self.assertLess(beta[4]["fit"], beta[5]["fit"])
            self.assertGreater(beta[4]["score"], beta[5]["score"])
            self.assertEqual(beta[4]["screening"], [])
        finally:
            conn.close()

    def test_min_fit_floor_applies_to_raw_fit(self):
        conn = _seed_db(self.jobs)
        try:
            out = bestshot(conn, RESUME, C, min_fit=0.9, limit=50)
            self.assertEqual(out, [])
        finally:
            conn.close()

    def test_boost_cannot_rescue_below_floor(self):
        jobs = [_job(4, "Beta Co", "Customer Success Engineer",
                     "We help customers adopt our platform.\n" * 10)]
        conn = _seed_db(jobs)
        try:
            # zero shared vocabulary with the resume seed: raw fit < floor
            out = bestshot(conn, RESUME, C, min_fit=0.06, limit=50)
            self.assertEqual([r["rowid"] for r in out], [])
        finally:
            conn.close()

    def test_hn_rows_excluded_no_form(self):
        jobs = [
            _job(51, "AtsCo", "Python Engineer",
                 "python automation LLM agents\n" * 10),
            _job(52, "HnCo", "Python Engineer",
                 "python automation LLM agents\n" * 10),
        ]
        jobs[1]["source"] = "hnwhoishiring"
        conn = _seed_db(jobs)
        try:
            out = bestshot(conn, RESUME, C, per_company=5, min_fit=0.0,
                           limit=50)
            self.assertEqual([r["rowid"] for r in out], [51])
        finally:
            conn.close()

    def test_needs_human_demoted_with_gap_labels(self):
        conn = _seed_db([
            _job(21, "CleanCo", "Python Engineer",
                 "python automation LLM agents\n" * 10),
            _job(22, "StuckCo", "Python Engineer",
                 "python automation LLM agents\n" * 10,
                 status="needs_human"),
        ])
        conn.execute(
            "INSERT INTO apply_runs (job_rowid, started_at, outcome, gaps) "
            "VALUES (22, '2026-09-03T10:00:00', 'needs_human', ?)",
            ('["phone number", "work auth"]',))
        conn.commit()
        try:
            out = bestshot(conn, RESUME, C, per_company=5, min_fit=0.0,
                           limit=50)
            by_id = {r["rowid"]: r for r in out}
            self.assertGreater(by_id[21]["score"], by_id[22]["score"])
            self.assertEqual(by_id[22]["gaps"],
                             ["phone number", "work auth"])
            self.assertEqual(by_id[21]["gaps"], [])
        finally:
            conn.close()

    def test_screening_flag_demotes_but_keeps(self):
        conn = _seed_db([
            _job(31, "CleanCo", "Python Engineer",
                 "python automation LLM agents\n" * 10),
            _job(32, "FlagCo", "Python Engineer",
                 "python automation LLM agents\n"
                 "One-way video interview required.\n" * 10),
        ])
        try:
            out = bestshot(conn, RESUME, C, per_company=5, min_fit=0.0,
                           limit=50)
            by_id = {r["rowid"]: r for r in out}
            self.assertIn(32, by_id)                      # kept, not hidden
            self.assertGreater(by_id[31]["score"], by_id[32]["score"])
            self.assertTrue(by_id[32]["screening"])
        finally:
            conn.close()


class BestshotCohort(unittest.TestCase):
    def test_from_bestshot_orders_by_fit(self):
        from src.jobber.batch import Cohort, select_cohort
        conn = _seed_db([
            _job(41, "HighFit", "Python Automation Engineer",
                 "python automation LLM agents pipelines\n" * 10),
            _job(42, "LowFit", "Python Engineer",
                 "python systems\n" * 3),
            _job(43, "OffList", "Java Engineer", "java spring\n" * 10),
        ])
        try:
            rows = select_cohort(conn, Cohort(limit=10, from_bestshot=True),
                                 resume_text=RESUME)
            ids = [r["rowid"] for r in rows]
            self.assertNotIn(43, ids)           # zero fit with the seed
            self.assertEqual(ids.index(41), 0)  # fit order, not ratio
        finally:
            conn.close()


class RepostCosine(unittest.TestCase):
    def test_threshold_separates_repost_from_distinct_role(self):
        repost_a = "python automation LLM agents\n" * 20
        distinct = "kitchen staff, full time, on site\n" * 20
        from src.jobber import similar
        idf = similar.corpus_idf({
            1: similar._tokens("T", repost_a),
            2: similar._tokens("T", repost_a),
            3: similar._tokens("T", distinct),
        })
        t1 = similar._tokens("T", repost_a)
        self.assertGreaterEqual(
            similar.cosine_pair(t1, similar._tokens("T", repost_a), idf),
            REPOST_COSINE)
        self.assertLess(
            similar.cosine_pair(t1, similar._tokens("T", distinct), idf),
            REPOST_COSINE)


if __name__ == "__main__":
    unittest.main()
