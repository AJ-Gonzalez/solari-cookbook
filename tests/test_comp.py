"""Tests for compensation parsing and normalization."""
import unittest

from src.jobber.comp import from_ashby, from_text


class FromText(unittest.TestCase):
    def test_usd_range_with_commas(self):
        self.assertEqual(
            from_text("Compensation: $120,000 - $160,000 per year"),
            (120000, 160000, "USD", "parsed"),
        )

    def test_usd_single_k(self):
        self.assertEqual(from_text("Salary: $175K"), (175000, 175000, "USD", "parsed"))

    def test_k_range(self):
        self.assertEqual(from_text("$60k - $90k"), (60000, 90000, "USD", "parsed"))

    def test_eur_recorded_not_converted(self):
        self.assertEqual(
            from_text("€50,000–60,000"), (50000, 60000, "EUR", "parsed")
        )

    def test_mxn_trap(self):
        # "$35,000 MXN" is monthly pesos (~2k USD), not 35k USD.
        self.assertEqual(
            from_text("Sueldo: $35,000 MXN mensuales"), (35000, 35000, "MXN", "parsed")
        )

    def test_hourly_ignored(self):
        self.assertIsNone(from_text("Pays $15 - $25/hr, equity, snacks"))

    def test_empty(self):
        self.assertIsNone(from_text(""))
        self.assertIsNone(from_text(None))


def _ashby_comp(currency, lo, hi, interval="1 YEAR"):
    return {"summaryComponents": [
        {"compensationType": "Salary", "currencyCode": currency,
         "minValue": lo, "maxValue": hi, "interval": interval},
    ]}


class FromAshby(unittest.TestCase):
    def test_salary_component(self):
        self.assertEqual(
            from_ashby(_ashby_comp("USD", 144000, 189000)), (144000, 189000, "USD", "listed")
        )

    def test_tiered_takes_conservative_floor(self):
        comp = {"summaryComponents": [
            {"compensationType": "Salary", "currencyCode": "USD",
             "minValue": 115200, "maxValue": 189000, "interval": "1 YEAR"},
            {"compensationType": "Commission", "currencyCode": "USD",
             "minValue": 175000, "maxValue": 175000, "interval": "1 YEAR"},
        ]}
        self.assertEqual(from_ashby(comp), (115200, 189000, "USD", "listed"))

    def test_monthly_annualized(self):
        self.assertEqual(
            from_ashby(_ashby_comp("USD", 3000, 3000, "1 MONTH")), (36000, 36000, "USD", "listed")
        )

    def test_non_usd_rejected(self):
        self.assertIsNone(from_ashby(_ashby_comp("INR", 7952000, 10437000)))

    def test_hourly_rejected(self):
        self.assertIsNone(from_ashby(_ashby_comp("USD", 40, 60, "1 HOUR")))

    def test_empty(self):
        self.assertIsNone(from_ashby(None))
        self.assertIsNone(from_ashby({"summaryComponents": []}))


if __name__ == "__main__":
    unittest.main()
