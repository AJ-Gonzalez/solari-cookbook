"""Tests for the answers bank and the fill-loop mechanics."""
import tempfile
import unittest
from pathlib import Path

from src.jobber.answers import AnswersBank as AnswersBankImpl, normalize


class Normalize(unittest.TestCase):
    def test_strips_punctuation_and_case(self):
        self.assertEqual(normalize("What's your 5+ years' experience?"),
                         "what s your 5 years experience")
        self.assertEqual(normalize("  EMAIL * "), "email")


class BankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        from src.jobber import db
        self.conn = db.connect(Path(self.tmp.name))
        self.bank = AnswersBankImpl(self.conn)

    def tearDown(self):
        self.conn.close()
        Path(self.tmp.name).unlink()

    def test_learn_and_exact_lookup(self):
        self.bank.learn("How did you hear about this job?",
                        "An automated test harness", "text")
        entry = self.bank.lookup("How did you hear about this job?")
        self.assertEqual(entry.answer, "An automated test harness")

    def test_containment_hits_partial_question(self):
        self.bank.learn("salary expectation", "$1")
        entry = self.bank.lookup("What is your salary expectation?!")
        self.assertIsNotNone(entry)

    def test_containment_match(self):
        self.bank.learn("years of python experience", "6")
        entry = self.bank.lookup("How many years of python experience do you have?")
        self.assertEqual(entry.answer, "6")

    def test_unknown_returns_none(self):
        self.assertIsNone(self.bank.lookup("Favorite color?"))

    def test_learn_updates_existing(self):
        self.bank.learn("notice period", "2 weeks")
        self.bank.learn("notice period", "immediate")
        self.assertEqual(self.bank.lookup("notice period").answer, "immediate")

    def test_persistence_across_connections(self):
        self.bank.learn("desired salary", "open")
        from src.jobber import db
        conn2 = db.connect(Path(self.tmp.name))
        self.assertEqual(
            AnswersBankImpl(conn2).lookup("desired salary").answer, "open")
        conn2.close()


if __name__ == "__main__":
    unittest.main()
