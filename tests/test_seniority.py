"""Tests for seniority classification."""
import unittest

from src.jobber.seniority import classify


class Seniority(unittest.TestCase):
    def test_c_suite(self):
        for t in ["Chief Technology Officer", "VP of Engineering",
                  "Head of Corporate Engineering", "Director, Developer GTM Finance"]:
            self.assertEqual(classify(t), "c-suite", t)

    def test_staff(self):
        for t in ["Staff Software Engineer", "Principal Engineer, Authentication",
                  "Senior Staff Engineer", "Solutions Architect"]:
            self.assertEqual(classify(t), "staff", t)

    def test_senior(self):
        for t in ["Senior Software Engineer", "Sr. Product Manager",
                  "Engineering Lead"]:
            self.assertEqual(classify(t), "senior", t)

    def test_junior(self):
        for t in ["Junior Backend Developer", "Entry Level Support",
                  "Graduate Software Engineer", "Associate Solutions Engineer"]:
            self.assertEqual(classify(t), "junior", t)

    def test_mid_default(self):
        for t in ["Software Engineer", "Backend Developer",
                  "Customer Success Engineer"]:
            self.assertEqual(classify(t), "mid", t)

    def test_order_precedence(self):
        # senior staff -> staff beats senior
        self.assertEqual(classify("Senior Staff Engineer"), "staff")
        # staff beats senior even when senior appears first
        self.assertEqual(classify("Senior Principal Engineer"), "staff")


if __name__ == "__main__":
    unittest.main()
