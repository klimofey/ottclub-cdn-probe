"""Dashboard served straight from the standard library.

A read-only status page plus one action does not justify a web framework in
the image, so this is http.server with a hand-written handler.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import bench, config, storage
from .daemon import Runner
from .stats import aggregate, best

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CDN probe</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ctext y='14' font-size='14'%3E%F0%9F%93%A1%3C/text%3E%3C/svg%3E">
<style>
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#12151a; --muted:#6b7280; --line:#e5e7eb;
  --good:#0f7b3f; --warn:#a86400; --bad:#b3261e; --accent:#1f5fd0;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f1115; --card:#171a21; --ink:#e8eaed; --muted:#9aa0aa; --line:#272b34;
  --good:#4ade80; --warn:#fbbf24; --bad:#f87171; --accent:#7aa2f7;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 60px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--muted);margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:16px;margin-bottom:16px}
.row{display:flex;flex-wrap:wrap;gap:12px}
.stat{flex:1 1 150px}
.stat .k{color:var(--muted);font-size:12px;text-transform:uppercase;
  letter-spacing:.04em}
.stat .v{font-size:17px;font-weight:600;margin-top:2px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;
  font-weight:600}
.running{background:color-mix(in srgb,var(--accent) 18%,transparent);
  color:var(--accent)}
.sleeping,.waiting,.cooldown{background:color-mix(in srgb,var(--warn) 20%,transparent);
  color:var(--warn)}
.error{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:7px 8px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
th{color:var(--muted);font-size:12px;text-transform:uppercase;
  letter-spacing:.04em;font-weight:600}
th[data-key]{cursor:pointer;user-select:none;white-space:nowrap}
th[data-key]:hover{color:var(--ink)}
th[data-key]::after{content:'';opacity:.35;margin-left:4px}
th[data-key]:hover::after{content:'\2195'}
th.sorted{color:var(--ink)}
th.sorted::after,th.sorted:hover::after{content:attr(data-arrow);opacity:1}
tbody tr:last-child td{border-bottom:0}
.v-solid{color:var(--good);font-weight:600}
.v-jumpy{color:var(--warn)}
.v-drops{color:var(--bad)}
.v-thin{color:var(--muted)}
.pick{border-left:3px solid var(--good);padding-left:12px;margin-top:14px}
button{font:inherit;font-weight:600;padding:8px 16px;border-radius:8px;
  border:1px solid var(--line);background:var(--accent);color:#fff;
  cursor:pointer}
button:disabled{opacity:.5;cursor:default}
pre{margin:0;max-height:280px;overflow:auto;font-size:12px;color:var(--muted);
  white-space:pre-wrap}
.scroll{overflow-x:auto}
.legend{color:var(--muted);font-size:12px;margin-top:10px}
.benched{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:7px 0;border-bottom:1px solid var(--line)}
.benched:last-child{border-bottom:0}
.benched .name{font-weight:600;min-width:180px}
.benched .why{color:var(--muted);font-size:12px;flex:1}
.benched button{padding:4px 12px;font-size:12px;background:transparent;
  color:var(--accent);border-color:var(--accent)}
tr.is-benched td{opacity:.45}
</style></head><body><div class="wrap">
<h1>CDN probe</h1>
<div class="sub">Which ilook.tv CDN actually keeps the stream fed</div>

<div class="card">
  <div class="row">
    <div class="stat"><div class="k">Status</div>
      <div class="v"><span id="status" class="pill">-</span></div></div>
    <div class="stat"><div class="k">Round</div><div class="v" id="round">-</div></div>
    <div class="stat"><div class="k">Now testing</div>
      <div class="v" id="cdn">-</div></div>
    <div class="stat"><div class="k">Between rounds</div>
      <div class="v" id="pause">-</div></div>
    <div class="stat"><div class="k">Active hours</div>
      <div class="v" id="hours">-</div></div>
    <div class="stat"><div class="k">Auto-apply</div>
      <div class="v" id="auto">-</div></div>
    <div class="stat"><div class="k">Measurements</div>
      <div class="v" id="total">-</div></div>
  </div>
  <div class="sub" id="detail" style="margin:12px 0 0"></div>
  <div style="margin-top:12px"><button id="run">Run round now</button></div>
</div>

<div class="card">
  <div class="scroll"><table>
    <thead><tr>
      <th>#</th>
      <th data-key="cdn">CDN</th>
      <th data-key="runs">Rounds</th>
      <th data-key="median">Median</th>
      <th data-key="worst_run">Worst</th>
      <th data-key="best_run">Best</th>
      <th data-key="spread">Spread</th>
      <th data-key="risk_share">Risk</th>
      <th data-key="verdict" style="text-align:left">Verdict</th>
    </tr></thead>
    <tbody id="rows"></tbody>
  </table></div>
  <div id="pick"></div>
  <div class="legend">
    MEDIAN typical margin, unmoved by one odd round &middot;
    WORST the worst round ever seen, where streams actually break &middot;
    SPREAD standard deviation across rounds &middot;
    RISK mean share of segments with too little margin.
  </div>
</div>

<div class="card" id="bench-card" hidden>
  <div class="k" style="color:var(--muted);font-size:12px;text-transform:uppercase;
    letter-spacing:.04em;margin-bottom:8px">Benched &mdash; not measured until you say so</div>
  <div id="bench"></div>
  <div class="legend">Benched CDNs are skipped so rounds stay short. New CDNs
    the provider adds are always measured; the account's automatic option is
    never benched.</div>
</div>

<div class="card"><pre id="log"></pre></div>
</div>
<script>
const cls = v => v === 'solid' ? 'v-solid'
  : v === 'good but jumpy' ? 'v-jumpy'
  : v === 'drops out' ? 'v-drops' : 'v-thin';

let rows = [];
let benched = new Set();
// Default order comes from the server: median first, ties broken by the
// worst round. Clicking a header overrides it until the page is reloaded.
let sortKey = null, sortDir = -1;

function render(){
  const data = rows.slice();
  if (sortKey) data.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    const cmp = typeof x === 'string' ? x.localeCompare(y, 'en') : x - y;
    return cmp * sortDir;
  });
  document.getElementById('rows').innerHTML = data.map((x,i) => `
    <tr class="${benched.has(x.cdn) ? 'is-benched' : ''}">
    <td>${i+1}</td><td>${x.cdn}</td><td>${x.runs}</td>
    <td>${x.median.toFixed(2)}x</td><td>${x.worst_run.toFixed(2)}x</td>
    <td>${x.best_run.toFixed(2)}x</td><td>${x.spread.toFixed(2)}</td>
    <td>${(x.risk_share*100).toFixed(0)}%</td>
    <td style="text-align:left" class="${cls(x.verdict)}">${x.verdict}</td></tr>`).join('');
}

document.querySelectorAll('th[data-key]').forEach(th => {
  th.onclick = () => {
    const key = th.dataset.key;
    // Same column toggles direction; a new column starts descending for
    // numbers and ascending for text, which is what people expect.
    if (sortKey === key) sortDir = -sortDir;
    else { sortKey = key; sortDir = (key === 'cdn' || key === 'verdict') ? 1 : -1; }
    document.querySelectorAll('th[data-key]').forEach(o => {
      o.classList.remove('sorted');
      o.removeAttribute('data-arrow');
    });
    th.classList.add('sorted');
    th.setAttribute('data-arrow', sortDir === 1 ? '\u2191' : '\u2193');
    render();
  };
});

async function refresh(){
  const r = await fetch('api/state');
  const d = await r.json();
  const s = d.state;
  const st = document.getElementById('status');
  st.textContent = s.status;
  st.className = 'pill ' + s.status;
  document.getElementById('round').textContent = s.round || '-';
  document.getElementById('cdn').textContent =
    s.cdn ? `${s.cdn} (${s.cdn_index}/${s.cdn_total})` : '-';
  document.getElementById('pause').textContent = s.pause;
  document.getElementById('total').textContent = d.measurements;
  document.getElementById('hours').textContent = s.active_hours;
  document.getElementById('auto').textContent = s.auto_apply
    ? (s.applied_cdn ? 'on \u2192 ' + s.applied_cdn : 'on') : 'off';
  document.getElementById('detail').textContent = s.detail || '';
  document.getElementById('log').textContent = s.log.join('\\n');

  rows = d.stats;
  benched = new Set(d.benched.map(b => b.cdn));
  render();

  const card = document.getElementById('bench-card');
  card.hidden = d.benched.length === 0;
  document.getElementById('bench').innerHTML = d.benched.map(b => `
    <div class="benched">
      <span class="name">${b.cdn}</span>
      <span class="why">${b.why || b.reason} &middot; since ${b.since.slice(5,16).replace('T',' ')}</span>
      <button data-cdn="${b.cdn}">Unbench</button>
    </div>`).join('');
  document.querySelectorAll('.benched button').forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true;
      await fetch('api/unbench', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({cdn: btn.dataset.cdn})});
      refresh();
    };
  });

  document.getElementById('pick').innerHTML = d.pick
    ? `<div class="pick"><b>Pick: ${d.pick.cdn}</b> &mdash; median
       ${d.pick.median.toFixed(2)}x over ${d.pick.runs} rounds, worst round
       ${d.pick.worst_run.toFixed(2)}x, spread &plusmn;${d.pick.spread.toFixed(2)}</div>`
    : `<div class="pick" style="border-color:var(--muted)">Nothing has proven
       steady yet &mdash; each CDN needs at least two rounds.</div>`;
}
document.getElementById('run').onclick = async e => {
  e.target.disabled = true;
  await fetch('api/run', {method:'POST'});
  setTimeout(() => { e.target.disabled = false; refresh(); }, 1500);
};
refresh(); setInterval(refresh, 5000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    runner: Runner

    def log_message(self, *args):  # keep the access log out of the way
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/state":
            records = storage.load()
            table = aggregate(records)
            pick = best(table)
            payload = {
                "state": self.runner.snapshot(),
                "stats": [s.as_dict() for s in table],
                "pick": pick.as_dict() if pick else None,
                "measurements": len(records),
                "benched": [
                    {"cdn": name, **info} for name, info in bench.load().items()
                ],
            }
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        if path == "/api/run":
            started = self.runner.request_run()
            self._send(200, json.dumps({"queued": started}).encode(),
                       "application/json")
        elif path == "/api/unbench":
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                payload = {}
            removed = bench.unbench(str(payload.get("cdn", "")))
            self._send(200, json.dumps({"unbenched": removed}).encode(),
                       "application/json")
        else:
            self._send(404, b"not found", "text/plain")


def serve(runner: Runner) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"runner": runner})
    server = ThreadingHTTPServer((config.WEB_HOST, config.WEB_PORT), handler)
    return server
