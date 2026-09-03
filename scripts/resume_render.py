#!/usr/bin/env python3
"""Render resume.md to personal/resume.pdf via Chromium print-to-PDF.

Edit resume.md, then run scripts/resume_pdf.sh. The output path is the
same file the application driver attaches.
"""
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "resume.md"
OUT = ROOT / "personal" / "resume.pdf"

CSS = """
@page { margin: 0; }
body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
       font-size: 10.5pt; line-height: 1.45; color: #1a1a1a;
       margin: 0; padding: 36px 44px; }
h1 { font-size: 21pt; margin: 0 0 6px; letter-spacing: 0.5px; }
h2 { font-size: 12.5pt; margin: 16px 0 6px; padding-bottom: 3px;
     border-bottom: 1.5px solid #2b2b2b; text-transform: uppercase;
     letter-spacing: 0.8px; }
h3 { font-size: 11pt; margin: 12px 0 2px; }
p { margin: 3px 0; }
ul { margin: 4px 0 10px; padding-left: 18px; }
li { margin: 2px 0; }
strong { font-weight: 700; }
.contact { color: #333; }
"""


def render() -> None:
    if not MD.exists():
        sys.exit(f"missing {MD}")
    md = markdown.markdown(MD.read_text(), extensions=["extra", "sane_lists"])
    # first paragraph is the contact line: dim it slightly
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>{CSS}</style></head><body>{md}</body></html>"""
    (ROOT / "personal").mkdir(exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(OUT), format="Letter",
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                 print_background=True)
        browser.close()
    print(f"rendered {OUT}")


if __name__ == "__main__":
    render()
