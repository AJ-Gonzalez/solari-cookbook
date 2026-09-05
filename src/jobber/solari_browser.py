"""Solari stealth browser sessions (REST; stdlib urllib).

Sessions give the apply driver a real-fingerprint Chromium with managed
captcha solving (Turnstile included) — the path for sites that block the
local headless run. One session per job, released right after: the batch
contract is a fresh context per job anyway (Ashby draft leak, LESSONS.md).

The API key comes from the environment first, then .env at the repo root
(batch runs as a subprocess with the repo as cwd; the dashboard never
exports .env).
"""
import json
import os
from pathlib import Path
from urllib import request as _request

BASE_URL = "https://api.getsolari.com"


def api_key() -> str:
    key = os.environ.get("SOLARI_API_KEY")
    if key:
        return key
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("SOLARI_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("no SOLARI_API_KEY in env or .env")


def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = _request.Request(
        BASE_URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        })
    with _request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read() or b"{}")


def create_session(stealth: bool = True, captcha: bool = True) -> dict:
    """Create a session; returns sessionId + wsEndpoint + cdpEndpoint.

    captcha requires stealth (API 400 otherwise); a 402 means the plan
    lacks the feature — surface that, it's a config problem not a retry.
    """
    return _call("POST", "/sessions",
                 {"stealth": stealth, "captcha": captcha})


def release_session(session_id: str) -> dict:
    """Release without waiting; the next job never races the old browser."""
    return _call("DELETE", f"/sessions/{session_id}")
