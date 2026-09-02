"""Tests for gate-question classification, using real questions captured
from live Greenhouse (Cloudflare) and Ashby (Replit) forms on 2026-09-02."""
import unittest

from src.jobber.gates import classify, is_hard_block


REAL_CLOUDFLARE = [
    "First Name", "Last Name", "Email", "Country", "Phone",
    "This role requires that you live in one of the following hubs: Austin, TX or NYC. "
    "Are you currently located in one of the hub locations or willing to relocate?",
    "Do you now or will you in the future require immigration sponsorship to work at Cloudflare?",
]

REAL_REPLIT = [
    "Full Name", "Email", "Location",
    "What excites you about Replit?",
    "How many years of relevant professional experience do you have?",
    "Are you able to work from our Foster City, CA HQ 3 days per week?",
    "If not currently in the Bay Area, are you willing to relocate near our Foster City, CA Office?",
    "Are you at least 18 years of age?",
    "Are you legally authorized to work in the United States?",
    "Will you now, or in the future, require sponsorship for employment visa status (e.g. H-1B visa status)?",
]

SHE_QUOTED = [
    "This job is only open to candidates in the United States or Canada. Do you live in the US or Canada?",
]


class Gates(unittest.TestCase):
    def test_cloudflare_form_gates(self):
        gates = classify(REAL_CLOUDFLARE)
        self.assertIn("residency", gates)
        self.assertIn("sponsorship", gates)
        self.assertTrue(is_hard_block(gates))

    def test_replit_form_gates(self):
        gates = classify(REAL_REPLIT)
        self.assertIn("work_auth", gates)
        self.assertIn("sponsorship", gates)
        self.assertIn("relocation", gates)
        self.assertIn("onsite_or_hybrid", gates)
        self.assertIn("age", gates)
        self.assertTrue(is_hard_block(gates))

    def test_user_quoted_us_canada_gate(self):
        gates = classify(SHE_QUOTED)
        self.assertIn("residency", gates)
        self.assertIn(
            "united states or canada",
            [p for ps in [["united states or canada"]] for p in ps],
        )

    def test_benign_questions_raise_no_gates(self):
        gates = classify(["First Name", "What excites you about Replit?", "Email"])
        self.assertEqual(gates, {})
        self.assertFalse(is_hard_block(gates))

    def test_timezone_is_soft(self):
        gates = classify(["Can you work within the CET time zone?"])
        self.assertIn("timezone", gates)
        self.assertFalse(is_hard_block(gates))


if __name__ == "__main__":
    unittest.main()
