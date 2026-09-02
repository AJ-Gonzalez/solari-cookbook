"""Tests for location eligibility classification."""
import unittest

from src.jobber.criteria import load_criteria
from src.jobber.eligibility import location_eligible

C = load_criteria()


class Eligibility(unittest.TestCase):
    def test_worldwide(self):
        self.assertEqual(location_eligible("Worldwide", C), "yes")

    def test_mexico(self):
        self.assertEqual(location_eligible("Remote, Mexico", C), "yes")

    def test_latam(self):
        self.assertEqual(location_eligible("Remote - Latin America", C), "yes")

    def test_us_only(self):
        self.assertEqual(location_eligible("Remote (US only)", C), "no")

    def test_europe_region(self):
        self.assertEqual(location_eligible("Remote - European Union", C), "no")

    def test_country(self):
        self.assertEqual(location_eligible("Remote, Italy", C), "no")

    def test_worldwide_beats_us_exclusion_parenthetical(self):
        self.assertEqual(location_eligible("Anywhere (no US sponsorship)", C), "yes")

    def test_bare_remote_unknown(self):
        self.assertEqual(location_eligible("Remote", C), "unknown")

    def test_empty_unknown(self):
        self.assertEqual(location_eligible("", C), "unknown")


if __name__ == "__main__":
    unittest.main()
