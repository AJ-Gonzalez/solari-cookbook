"""Local web dashboard for the ranked job queue. Stdlib only.

Read-only on purpose: triage decisions go through the human's mouth in
chat ("apply to 1212"), not through dashboard buttons — the dashboard
exists so the human can see ids and details side by side while talking.
Auto-refreshes the queue so status changes made by the agent appear live.

UX notes: the list is keyboard-driven (arrow keys walk rows, Enter opens
the posting), the job description lives in a bottom panel, and sorting is
ratio-first by default with comp asc/desc available. Comic Neue is loaded
per the user's dyslexia-friendly-font preference; it falls back to system
fonts offline.

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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Comic+Neue:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0d1117; --panel: #1a222b; --panel2: #202b36; --line: #42505e;
    --text: #f2f6fa; --dim: #b3c2cf; --accent: #6cb6ff;
    --yes: #4cd787; --no: #ff7b7b; --unk: #ffc857;
    --mono: ui-monospace, "JetBrains Mono", Menlo, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font: 15px/1.5 "Comic Neue", "Comic Sans MS", system-ui, sans-serif;
         display: flex; flex-direction: column; height: 100vh; }
  #bar { padding: 10px 14px; border-bottom: 1px solid var(--line);
         display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
         background: var(--panel); }
  #search { background: var(--panel2); border: 1px solid var(--line);
            color: var(--text); border-radius: 6px; padding: 6px 10px;
            width: 200px; font: inherit; }
  .chip { cursor: pointer; border: 1px solid var(--line); border-radius: 999px;
          padding: 3px 11px; color: var(--dim); user-select: none; font-size: 13px; }
  .chip.on { border-color: var(--accent); color: var(--accent);
             background: #16283c; font-weight: 700; }
  #sortbtn { border: 1px solid var(--accent); color: var(--accent); background: var(--panel2);
             border-radius: 6px; padding: 4px 12px; cursor: pointer; font: inherit;
             font-weight: 700; }
  #count { color: var(--dim); font-size: 13px; margin-left: auto; }
  #wrap { overflow-y: auto; flex: 1; }
  table { width: 100%; border-collapse: collapse; }
  th { position: sticky; top: 0; background: var(--panel); color: var(--text);
       text-align: left; font-weight: 700; font-size: 12px; text-transform: uppercase;
       letter-spacing: .06em; padding: 7px 12px; border-bottom: 2px solid var(--line); }
  td { padding: 7px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
  tr.job { cursor: pointer; }
  tr.job:hover { background: #1e2a37; }
  tr.sel { background: #24405e !important; outline: 2px solid var(--accent);
           outline-offset: -2px; }
  .id { font-family: var(--mono); color: var(--accent); font-weight: 700; }
  .num { font-family: var(--mono); text-align: right; }
  .yes { color: var(--yes); font-weight: 700; }
  .no { color: var(--no); font-weight: 700; }
  .unknown { color: var(--unk); }
  .st-queued { color: var(--accent); font-weight: 700; }
  .st-applied { color: var(--yes); font-weight: 700; }
  .st-hidden, .st-rejected { color: var(--dim); }
  .st-staged { color: #d9a8ff; font-weight: 700; }
  #bottom { height: 42%; border-top: 2px solid var(--line); background: var(--panel);
            overflow-y: auto; padding: 16px 22px; }
  .placeholder { color: var(--dim); margin-top: 8vh; text-align: center; }
  h2 { margin: 0 0 2px; font-size: 20px; }
  .co { color: var(--dim); margin-bottom: 10px; }
  .meta { font-family: var(--mono); font-size: 13px; background: var(--panel2);
          border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
          margin: 10px 0; white-space: pre-wrap; }
  .desc { white-space: pre-wrap; margin-top: 12px; max-width: 110ch; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  button.copy { background: var(--panel2); border: 1px solid var(--line);
                color: var(--accent); border-radius: 6px; padding: 2px 10px;
                cursor: pointer; font-family: var(--mono); }
  .hint { color: var(--dim); font-size: 12.5px; margin-left: 6px; }
</style>
</head>
<body>
<div id="bar">
  <input id="search" placeholder="filter title / company">
  <button id="sortbtn" title="cycle sort order">sort: ratio ↓</button>
  <span class="chip on" data-st="new">new</span>
  <span class="chip on" data-st="queued">queued</span>
  <span class="chip" data-st="staged">staged</span>
  <span class="chip" data-st="applied">applied</span>
  <span class="chip" data-st="hidden">hidden</span>
  <span class="chip" data-st="rejected">rejected</span>
  <span class="chip on" data-elg="yes">mex ok</span>
  <span class="chip on" data-elg="unknown">unknown</span>
  <span class="chip" data-elg="no">ineligible</span>
  <span class="chip on" data-deg="none">no degree</span>
  <span class="chip on" data-deg="unknown">deg ?</span>
  <span class="chip on" data-deg="preferred">pref</span>
  <span class="chip" data-deg="required">required</span>
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
<div id="bottom"><div class="placeholder">click a job or use ↑↓ arrow keys to read it here</div></div>
<script>
let JOBS = [];
let VIS = [];
let LAST = null;
let selId = null;
let SORT = "ratio";
const on = s => new Set(s);
let sts = on(["new", "queued"]);
let elgs = on(["yes", "unknown"]);
let degs = on(["none", "unknown", "preferred"]);

const SORTS = ["ratio", "comp-desc", "comp-asc"];
const SORT_LABEL = { "ratio": "sort: ratio ↓", "comp-desc": "sort: comp ↓",
                     "comp-asc": "sort: comp ↑" };
document.getElementById("sortbtn").onclick = () => {
  SORT = SORTS[(SORTS.indexOf(SORT) + 1) % SORTS.length];
  document.getElementById("sortbtn").textContent = SORT_LABEL[SORT];
  render();
};
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
document.querySelectorAll(".chip[data-deg]").forEach(c => c.onclick = () => {
  const v = c.dataset.deg;
  degs.has(v) ? degs.delete(v) : degs.add(v);
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
function compMid(r) {
  // USD midpoints only; non-USD and unknown sort as missing (kept last).
  if (r.comp_currency !== "USD" || !r.comp_min) return null;
  return (r.comp_min + (r.comp_max || r.comp_min)) / 2;
}
function ratioTxt(r) { return r.ratio === null ? "-" : Math.round(r.ratio); }

function sortRows(rows) {
  if (SORT === "ratio")
    rows.sort((a, b) => (b.ratio ?? -1) - (a.ratio ?? -1));
  else {
    const dir = SORT === "comp-desc" ? -1 : 1;
    rows.sort((a, b) => {
      const ma = compMid(a), mb = compMid(b);
      if (ma === null && mb === null) return (b.ratio ?? -1) - (a.ratio ?? -1);
      if (ma === null) return 1;
      if (mb === null) return -1;
      return dir * (ma - mb);
    });
  }
  return rows;
}

async function load() {
  JOBS = await (await fetch("/api/jobs")).json();
  render();
}
function render() {
  const q = document.getElementById("search").value.toLowerCase();
  VIS = sortRows(JOBS.filter(r =>
    sts.has(r.status) && elgs.has(r.location_eligible) && degs.has(r.degree_flag) &&
    (!q || (r.title + " " + r.company).toLowerCase().includes(q))));
  document.getElementById("count").textContent = VIS.length + " shown";
  document.getElementById("rows").innerHTML = VIS.map(r => `
    <tr class="job${r.rowid === selId ? " sel" : ""}" data-id="${r.rowid}"
        onclick="pick(${r.rowid})">
      <td class="id">${r.rowid}</td>
      <td class="num">${ratioTxt(r)}</td>
      <td class="num">${esc(comp(r))}</td>
      <td class="${r.location_eligible}">${r.location_eligible}</td>
      <td>${r.degree_flag}</td>
      <td class="st-${r.status}">${r.status}</td>
      <td>${esc(r.company)}</td>
      <td>${esc(r.title)}</td>
    </tr>`).join("");
}
function showDetail(r) {
  LAST = r;
  selId = r.rowid;
  document.querySelectorAll("tr.sel").forEach(e => e.classList.remove("sel"));
  const tr = document.querySelector(`tr[data-id="${r.rowid}"]`);
  if (tr) { tr.classList.add("sel"); tr.scrollIntoView({ block: "nearest" }); }
  document.getElementById("bottom").innerHTML = `
    <h2><span class="id">${r.rowid}</span> — ${esc(r.title)}
      <button class="copy" onclick="navigator.clipboard.writeText('${r.rowid}')">copy id</button>
      <span class="hint">↑↓ move · Enter opens the posting</span></h2>
    <div class="co">${esc(r.company)} · ${esc(r.source)}</div>
    <div class="meta">ratio      ${r.ratio === null ? "-" : Math.round(r.ratio)}
comp      ${esc(comp(r))} (${esc(r.comp_confidence)})
location  ${esc(r.location)}
eligible  ${r.location_eligible}   degree ${r.degree_flag}   qual ${r.qual_score}
status    ${r.status}
url       <a href="${esc(r.url)}" target="_blank">${esc(r.url)}</a></div>
    <div class="desc">${esc(r.description)}</div>`;
}
async function pick(id) {
  const r = await (await fetch("/api/job/" + id)).json();
  showDetail(r);
}
document.addEventListener("keydown", e => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!VIS.length) return;
    let i = VIS.findIndex(r => r.rowid === selId);
    if (i === -1) i = 0;
    else i = e.key === "ArrowDown" ? Math.min(i + 1, VIS.length - 1)
                                   : Math.max(i - 1, 0);
    pick(VIS[i].rowid);
  } else if (e.key === "Enter" && LAST) {
    window.open(LAST.url, "_blank");
  }
});
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
