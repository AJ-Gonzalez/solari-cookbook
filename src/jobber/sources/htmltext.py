"""HTML to text conversion for description fields. Stdlib only.

Deliberately lossy on formatting but structure-preserving on purpose:
block tags become line breaks and <li> items become "- " bullets, because
qual_score counts requirement bullets by line. Flat single-line text
would silently zero every listing's qualification score.
"""
import re
from html import unescape

_BULLET_TAG = re.compile(r"<li[^>]*>", re.I)
_BLOCK_TAG = re.compile(r"</?(?:p|h[1-6]|ul|ol|div|tr|table|blockquote|br)[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def strip_html(html: str) -> str:
    text = unescape(html or "")  # unwrap double-escaped HTML first
    text = _BLOCK_TAG.sub("\n", text)
    text = _BULLET_TAG.sub("\n- ", text)
    text = _TAG.sub(" ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r" ?\n ?", "\n", text).strip()
