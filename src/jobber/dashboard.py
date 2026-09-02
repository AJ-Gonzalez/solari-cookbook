"""Local web dashboard for the ranked job queue. Stdlib only.

Read-only on purpose: triage decisions go through the human's mouth in
chat ("apply to 1212"), not through dashboard buttons — the dashboard
exists so the human can see ids and details side by side while talking.
Auto-refreshes the queue so status changes made by the agent appear live.

Each request opens its own SQLite connection: ThreadingHTTPServer serves
requests on different threads and sqlite3 objects refuse cross-thread use.
"""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import db

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>jobber queue</title>
<style>
  :root {
    --bg: #101418; --panel: #171c22; --line: #262e37; --text: #d6dde4;
    --dim: #7d8a96; --accent: #4da3ff; --yes: #3fb96f; --no: #d15b5b;
    --unk: #b99a3f; --mono: ui-monospace, "JetBrains Mono", Menlo, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font: 14px/1.45 system-ui, sans-serif; display: flex; height: 100vh; }
  #left { width: 62%; min-width: 560px; display: flex; flex-direction: column;
          border-right: 1px solid var(--line); }
  #bar { padding: 10px 14px; border-bottom: 1px solid var(--line);
         display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  #search { background: var(--panel); border: 1px solid var(--line);
            color: var(--text); border-radius: 6px; padding: 6px 10px;
            width: 200px; }
  .chip { cursor: pointer; border: 1px solid var(--line); border-radius: 999px;
          padding: 3px 10px; color: var(--dim); user-select: none; font-size: 12px; }
  .chip.on { border-color: var(--accent); color: var(--accent); }
  #count { color: var(--dim); font-size: 12px; margin-left: auto; }
  #wrap { overflow-y: auto; flex: 1; }
  table { width: 100%; border-collapse: collapse; }
  th { position: sticky; top: 0; background: var(--panel); color: var(--dim);
       text-align: left; font-weight: 500; font-size: 11px; text-transform: uppercase;
       letter-spacing: .05em; padding: 6px 10px; border-bottom: 1px solid var(--line); }
  td { padding: 6px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
  tr.job { cursor: pointer; }
  tr.job:hover { background: #1a2029; }
  tr.sel { background: #1c2836 !important; }
  .id { font-family: var(--mono); color: var(--accent); font-weight: 700; }
  .num { font-family: var(--mono); text-align: right; }
  .yes { color: var(--yes); } .no { color: var(--no); } .unknown { color: var(--unk); }
  .st-queued { color: var(--accent); } .st-applied { color: var(--yes); }
  .st-hidden, .st-rejected { color: var(--dim); }
  .st-staged { color: #c583ff; }
  #right { flex: 1; overflow-y: auto; padding: 18px 22px; }
  .placeholder { color: var(--dim); margin-top: 40vh; text-align: center; }
  h2 { margin: 0 0 2px; }
  .co { color: var(--dim); margin-bottom: 12px; }
  .meta { font-family: var(--mono); font-size: 12.5px; background: var(--panel);
          border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
          margin: 10px 0; white-space: pre-wrap; }
  .desc { white-space: pre-wrap; margin-top: 14px; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  button { background: var(--panel); border: 1px solid var(--line); color: var(--accent);
           border-radius: 6px; padding: 2px 10px; cursor: pointer; font-family: var(--mono); }
</style>
</head>
<body>
<div id="left">
  <div id="bar">
    <input id="search" placeholder="filter title / company">
    <span class="chip on" data-st="new">new</span>
    <span class="chip on" data-st="queued">queued</span>
    <span class="chip" data-st="staged">staged</span>
    <span class="chip" data-st="applied">applied</span>
    <span class="chip" data-st="hidden">hidden</span>
    <span class="chip" data-st="rejected">rejected</span>
    <span class="chip on" data-elg="yes">mex ok</span>
    <span class="chip on" data-elg="unknown">unknown</span>
    <span class="chip" data-elg="no">ineligible</span>
    <span id="count"></span>
  </div>
  <div id="wrap">
    <table>
      <thead><tr>
        <th>id</th><th class="num">ratio</th><th class="num">comp usd</th>
        <th>elg</th><th>deg</th><th>st</th><th>company</th><th>title</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
</div>
<div id="right"><div class="placeholder">click a job to read it here</div></div>
<script>
let JOBS = [];
const on = s => new Set(s);
let sts = on(["new", "queued"]);
let elgs = on(["yes", "unknown"]);

document.querySelectorAll(".chip[data-st]").forEach(c => c.onclick = () => {
  const v = c.dataset.st;
  sts.has(v) ? sts.delete(v) : sts.add(v);
  c.classList.toggle("on");
  render();
});
document.querySelectorAll(".chip[data-elg]").forEach(c => c.onclick = () => {
  const v = c.dataset.elg;
  elgs.has(v) ? elgs.delete(v) : elgs.add(v);
  c.classList.toggle("on");
  render();
});
document.getElementById("search").oninput = render;

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}
function comp(r) {
  if (r.comp_currency === "USD" && r.comp_min)
    return r.comp_min / 1000 + "-" + (r.comp_max || r.comp_min) / 1000 + "k";
  if (r.comp_currency && r.comp_min) return r.comp_min + " " + r.comp_currency;
  return "?";
}
function ratio(r) { return r.ratio === null ? "-" : Math.round(r.ratio); }

async function load() {
  JOBS = await (await fetch("/api/jobs")).json();
  render();
}
function render() {
  const q = document.getElementById("search").value.toLowerCase();
  const rows = JOBS.filter(r =>
    sts.has(r.status) && elgs.has(r.location_eligible) &&
    (!q || (r.title + " " + r.company).toLowerCase().includes(q)));
  document.getElementById("count").textContent = rows.length + " shown";
  document.getElementById("rows").innerHTML = rows.map(r => `
    <tr class="job" data-id="${r.rowid}" onclick="pick(${r.rowid}, this)">
      <td class="id">${r.rowid}</td>
      <td class="num">${ratio(r)}</td>
      <td class="num">${esc(comp(r))}</td>
      <td class="${r.location_eligible}">${r.location_eligible}</td>
      <td>${r.degree_flag}</td>
      <td class="st-${r.status}">${r.status}</td>
      <td>${esc(r.company)}</td>
      <td>${esc(r.title)}</td>
    </tr>`).join("");
}
async function pick(id, tr) {
  document.querySelectorAll("tr.sel").forEach(e => e.classList.remove("sel"));
  tr.classList.add("sel");
  const r = await (await fetch("/api/job/" + id)).json();
  document.getElementById("right").innerHTML = `
    <h2><span class="id">${r.rowid}</span> — ${esc(r.title)}
      <button onclick="navigator.clipboard.writeText('${r.rowid}')">copy id</button></h2>
    <div class="co">${esc(r.company)} · ${esc(r.source)}</div>
    <div class="meta">ratio      ${r.ratio === null ? "-" : Math.round(r.ratio)}
comp      ${esc(comp(r))} (${esc(r.comp_confidence)})
location  ${esc(r.location)}
eligible  ${r.location_eligible}   degree ${r.degree_flag}   qual ${r.qual_score}
status    ${r.status}
url       <a href="${esc(r.url)}" target="_blank">${esc(r.url)}</a></div>
    <div class="desc">${esc(r.description)}</div>`;
}
load();
setInterval(load, 20000);
</script>
</body>
</html>
"""

_JOB_ROUTE = re.compile(r"^/api/job/(\d+)$")


def _jobs_payload(path: str) -> list[dict]:
    conn = db.connect(Path(path))
    try:
        rows = db.ranked_rows(
            conn,
            statuses=("new", "queued", "staged", "hidden", "applied", "rejected"),
            eligible_only=False,
        )
    finally:
        conn.close()
    fields = ("rowid", "ratio", "comp_min", "comp_max", "comp_currency",
              "comp_confidence", "location_eligible", "degree_flag", "status",
              "company", "title", "source")
    return [{f: r[f] for f in fields} for r in rows]


def _job_payload(path: str, rowid: int) -> dict | None:
    conn = db.connect(Path(path))
    try:
        r = conn.execute("SELECT rowid, * FROM jobs WHERE rowid=?", (rowid,)).fetchone()
    finally:
        conn.close()
    if r is None:
        return None
    return {k: r[k] for k in r.keys()}


def make_handler(path: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route == "/":
                self._send(200, _PAGE.encode(), "text/html; charset=utf-8")
            elif route == "/api/jobs":
                body = json.dumps(_jobs_payload(path)).encode()
                self._send(200, body, "application/json")
            elif m := _JOB_ROUTE.match(route):
                job = _job_payload(path, int(m.group(1)))
                if job is None:
                    self._send(404, b"{}", "application/json")
                else:
                    self._send(200, json.dumps(job).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *args) -> None:
            pass  # keep the service log clean; nothing here needs auditing

    return Handler


def serve(port: int = 8799, db_path: str = str(db.DEFAULT_DB)) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(db_path))
    print(f"dashboard on http://127.0.0.1:{port}")
    httpd.serve_forever()
