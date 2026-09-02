"""Browser-backed test for the fill loop mechanics (multi-page detection,
submit gating). Skipped when Playwright/Chromium is unavailable."""
import tempfile
import unittest
from pathlib import Path

try:
    from src.jobber import db
    from src.jobber.answers import AnswersBank
    from src.jobber.driver import walk_and_fill
except ImportError:
    # playwright missing (system python) — skip browser-backed tests
    raise unittest.SkipTest("playwright not installed for this interpreter")

SINGLE_PAGE = """<!doctype html><html><body>
<form id="application-form">
  <div class="field-wrapper"><label>First Name*</label>
    <input id="first_name" type="text" required></div>
  <div class="field-wrapper"><label>Email*</label>
    <input id="email" type="text" required></div>
  <button type="submit" id="submit-btn">Submit application</button>
</form></body></html>"""

MULTI_PAGE = """<!doctype html><html><body>
<form id="application-form">
  <div class="field-wrapper"><label>First Name*</label>
    <input id="first_name" type="text" required></div>
  <button type="button" id="next-btn">Continue</button>
</form>
<script>
document.getElementById('next-btn').onclick = () => {
  document.getElementById('next-btn').remove();
  const d = document.createElement('div');
  d.className = 'field-wrapper';
  d.innerHTML = '<label>Favorite project*</label>' +
    '<input id="fav" type="text" required>';
  document.getElementById('application-form').appendChild(d);
  const s = document.createElement('button');
  s.type = 'submit'; s.id = 'submit-btn';
  s.textContent = 'Submit application';
  document.getElementById('application-form').appendChild(s);
};
</script></body></html>"""

ASK_ALL = lambda fields: {f.label: "mock answer" for f in fields}


class FillLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.conn = db.connect(Path(self.tmp.name))
        self.bank = AnswersBank(self.conn)
        try:
            from playwright.sync_api import sync_playwright
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.launch(headless=True)
            self.page = self.browser.new_context().new_page()
        except Exception:
            self.pw = None
            self.addCleanup(self._teardown)
            self.skipTest("playwright/chromium unavailable")

    def _teardown(self):
        if getattr(self, "browser", None):
            self.browser.close()
        if getattr(self, "pw", None):
            self.pw.stop()
        self.conn.close()
        Path(self.tmp.name).unlink()

    tearDown = _teardown

    def test_single_page_reaches_ready(self):
        self.page.set_content(SINGLE_PAGE)
        status = walk_and_fill(self.page, self.page.main_frame,
                               Path("/dev/null"), self.bank, ASK_ALL,
                               dry_run=True)
        self.assertEqual(status, "ready")
        self.assertEqual(
            self.page.locator("#first_name").input_value(), "mock answer")

    def test_multi_page_walks_continue(self):
        self.page.set_content(MULTI_PAGE)
        status = walk_and_fill(self.page, self.page.main_frame,
                               Path("/dev/null"), self.bank, ASK_ALL,
                               dry_run=True)
        self.assertEqual(status, "ready")
        self.assertEqual(
            self.page.locator("#fav").input_value(), "mock answer")

    def test_no_form_reports(self):
        self.page.set_content("<html><body><p>nothing here</p></body></html>")
        status = walk_and_fill(self.page, self.page.main_frame,
                               Path("/dev/null"), self.bank, ASK_ALL,
                               dry_run=True)
        self.assertEqual(status, "no-form")

    def test_bank_used_before_asking(self):
        self.bank.learn("First Name", "Humanname")
        self.page.set_content(SINGLE_PAGE)

        asked = []
        def ask(fields):
            asked.extend(f.label for f in fields)
            return {f.label: "asked-answer" for f in fields}

        walk_and_fill(self.page, self.page.main_frame, Path("/dev/null"),
                      self.bank, ask, dry_run=True)
        self.assertEqual(self.page.locator("#first_name").input_value(),
                         "Humanname")
        self.assertNotIn("First Name", asked)
        self.assertIn("Email", asked)


if __name__ == "__main__":
    unittest.main()
