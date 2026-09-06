"""Dashboard served straight from the standard library.

A read-only status page plus one action does not justify a web framework in
the image, so this is http.server with a hand-written handler.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import bench, config, storage
from .daemon import Runner
from .stats import PARTS, aggregate, best, coverage

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CDN probe</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ctext y='14' font-size='14'%3E%F0%9F%93%A1%3C/text%3E%3C/svg%3E">
<style>
/* Light is the base; dark redefines only the tokens, so a colour is never
   defined solely inside a media query. data-theme wins over both, which is
   what makes the toggle work in either direction. */
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#12151a; --muted:#6b7280; --line:#e5e7eb;
  --good:#0f7b3f; --warn:#a86400; --bad:#b3261e; --accent:#1f5fd0;
  --live:#1f5fd0; --live-bg:rgba(31,95,208,.10);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0f1115; --card:#171a21; --ink:#e8eaed; --muted:#9aa0aa; --line:#272b34;
  --good:#4ade80; --warn:#fbbf24; --bad:#f87171; --accent:#7aa2f7;
  --live:#7aa2f7; --live-bg:rgba(122,162,247,.12);
}}
:root[data-theme="dark"]{
  --bg:#0f1115; --card:#171a21; --ink:#e8eaed; --muted:#9aa0aa; --line:#272b34;
  --good:#4ade80; --warn:#fbbf24; --bad:#f87171; --accent:#7aa2f7;
  --live:#7aa2f7; --live-bg:rgba(122,162,247,.12);
}
*{box-sizing:border-box}
/* Author styles beat the browser's [hidden] rule regardless of specificity,
   so a class with display:flex would keep a hidden element visible. */
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1140px;margin:0 auto;padding:24px 16px 60px}
.top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--muted);margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:16px;margin-bottom:16px}
.row{display:flex;flex-wrap:wrap;gap:12px}
.stat{flex:1 1 140px}
.stat .k{color:var(--muted);font-size:12px;text-transform:uppercase;
  letter-spacing:.04em}
.stat .v{font-size:17px;font-weight:600;margin-top:2px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;
  font-weight:600;background:color-mix(in srgb,var(--muted) 18%,transparent);
  color:var(--muted)}
.pill.running,.pill.measuring{background:color-mix(in srgb,var(--accent) 18%,transparent);
  color:var(--accent)}
.pill.sleeping,.pill.waiting,.pill.cooldown,.pill.propagating,.pill.switching,
.pill\\.outside{background:color-mix(in srgb,var(--warn) 20%,transparent);
  color:var(--warn)}
.pill.error{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
.now{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px;
  padding:12px;border-radius:8px;background:var(--live-bg);
  border:1px solid color-mix(in srgb,var(--live) 30%,transparent)}
.now .dot{width:8px;height:8px;border-radius:50%;background:var(--live);
  animation:pulse 1.4s ease-in-out infinite;flex:none}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
.now b{color:var(--live)}
.now .what{color:var(--muted)}
.tag{font-size:11px;font-weight:600;padding:1px 7px;border-radius:999px;
  border:1px solid var(--warn);color:var(--warn)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:7px 8px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
th{color:var(--muted);font-size:12px;text-transform:uppercase;
  letter-spacing:.04em;font-weight:600}
th[data-key]{cursor:pointer;user-select:none;white-space:nowrap}
th[data-key]:hover{color:var(--ink)}
th[data-key]::after{content:'';opacity:.35;margin-left:4px}
th[data-key]:hover::after{content:'\\2195'}
th.sorted{color:var(--ink)}
th.sorted::after,th.sorted:hover::after{content:attr(data-arrow);opacity:1}
tbody tr:last-child td{border-bottom:0}
tr.is-live td{background:var(--live-bg)}
tr.is-live td:nth-child(2){font-weight:700;color:var(--live)}
tr.is-benched td{opacity:.45}
.v-solid{color:var(--good);font-weight:600}
.v-jumpy{color:var(--warn)}
.v-drops{color:var(--bad)}
.v-thin{color:var(--muted)}
.pick{border-left:3px solid var(--good);padding-left:12px;margin-top:14px}
button{font:inherit;font-weight:600;padding:8px 16px;border-radius:8px;
  border:1px solid var(--line);background:var(--accent);color:#fff;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
button.ghost{background:transparent;color:var(--muted);border-color:var(--line);
  padding:6px 12px;font-size:13px}
button.ghost:hover{color:var(--ink)}
pre{margin:0;max-height:280px;overflow:auto;font-size:12px;color:var(--muted);
  white-space:pre-wrap}
.scroll{overflow-x:auto}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tabs button{background:transparent;color:var(--muted);border-color:var(--line);
  padding:5px 12px;font-size:13px;font-weight:500}
.tabs button.on{background:var(--accent);color:#fff;border-color:var(--accent);
  font-weight:600}
.tabs button:disabled{opacity:.4}
.tabs .count{opacity:.7;font-weight:400;margin-left:5px}
.legend{color:var(--muted);font-size:12px;margin-top:10px}
.benched{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:7px 0;
  border-bottom:1px solid var(--line)}
.benched:last-child{border-bottom:0}
.benched .name{font-weight:600;min-width:180px}
.benched .why{color:var(--muted);font-size:12px;flex:1}
.benched button{padding:4px 12px;font-size:12px;background:transparent;
  color:var(--accent);border-color:var(--accent)}
</style></head><body><div class="wrap">

<div class="top">
  <div>
    <h1>CDN probe</h1>
    <div class="sub">Which CDN actually keeps the stream fed</div>
  </div>
  <button class="ghost" id="theme">theme: system</button>
</div>

<div class="card">
  <div class="row">
    <div class="stat"><div class="k">Status</div>
      <div class="v"><span id="status" class="pill">-</span></div></div>
    <div class="stat"><div class="k">Round</div><div class="v" id="round">-</div></div>
    <div class="stat"><div class="k">Selected CDN</div>
      <div class="v" id="selected">-</div></div>
    <div class="stat"><div class="k">Between rounds</div>
      <div class="v" id="pause">-</div></div>
    <div class="stat"><div class="k">Active hours</div>
      <div class="v" id="hours">-</div></div>
    <div class="stat"><div class="k">Auto-apply</div>
      <div class="v" id="auto">-</div></div>
    <div class="stat"><div class="k">Measurements</div>
      <div class="v" id="total">-</div></div>
  </div>

  <div class="now" id="now" hidden>
    <span class="dot"></span>
    <b id="now-cdn">-</b>
    <span id="now-parole" class="tag" hidden>parole re-test</span>
    <span class="what" id="now-what"></span>
    <span class="what" id="now-pos" style="margin-left:auto"></span>
  </div>

  <div class="sub" id="detail" style="margin:12px 0 0"></div>
  <div style="margin-top:12px"><button id="run">Run round now</button></div>
</div>

<div class="card">
  <div class="tabs" id="tabs"></div>
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
    Click any column to sort.
  </div>
</div>

<div class="card" id="bench-card" hidden>
  <div style="color:var(--muted);font-size:12px;text-transform:uppercase;
    letter-spacing:.04em;margin-bottom:8px">Benched &mdash; skipped to keep rounds short</div>
  <div id="bench"></div>
  <div class="legend">One benched CDN is re-tested each round, oldest check
    first, and released automatically if it now passes. New CDNs the provider
    adds are always measured; the account\'s automatic option is never benched.</div>
</div>

<div class="card"><pre id="log"></pre></div>
</div>
<script>
const THEMES = ['system', 'light', 'dark'];
let theme = localStorage.getItem('theme') || 'system';
function applyTheme(){
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
  document.getElementById('theme').textContent = 'theme: ' + theme;
  localStorage.setItem('theme', theme);
}
document.getElementById('theme').onclick = () => {
  theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  applyTheme();
};
applyTheme();

const cls = v => v === 'solid' ? 'v-solid'
  : v === 'good but jumpy' ? 'v-jumpy'
  : v === 'drops out' ? 'v-drops' : 'v-thin';

const PHASES = {
  switching:   'asking the panel to switch',
  cooldown:    'waiting out the provider cooldown',
  propagating: 'switched, waiting for the edge pool to turn over',
  measuring:   'downloading segments from every edge',
  starting:    'starting',
};

let rows = [], benched = new Set(), live = '', part = '';
const PART_LABELS = {'': 'All day', night: 'Night 00-06', morning: 'Morning 06-12',
  afternoon: 'Afternoon 12-18', evening: 'Evening 18-24'};
// Default order is the server\'s: median first, ties broken by worst round.
let sortKey = null, sortDir = -1;

function render(){
  const data = rows.slice();
  if (sortKey) data.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    const cmp = typeof x === 'string' ? x.localeCompare(y, 'en') : x - y;
    return cmp * sortDir;
  });
  document.getElementById('rows').innerHTML = data.map((x,i) => {
    const klass = [x.cdn === live ? 'is-live' : '',
                   benched.has(x.cdn) ? 'is-benched' : ''].filter(Boolean).join(' ');
    return `<tr class="${klass}"><td>${i+1}</td><td>${x.cdn}</td><td>${x.runs}</td>
      <td>${x.median.toFixed(2)}x</td><td>${x.worst_run.toFixed(2)}x</td>
      <td>${x.best_run.toFixed(2)}x</td><td>${x.spread.toFixed(2)}</td>
      <td>${(x.risk_share*100).toFixed(0)}%</td>
      <td style="text-align:left" class="${cls(x.verdict)}">${x.verdict}</td></tr>`;
  }).join('');
}

document.querySelectorAll('th[data-key]').forEach(th => {
  th.onclick = () => {
    const key = th.dataset.key;
    if (sortKey === key) sortDir = -sortDir;
    else { sortKey = key; sortDir = (key === 'cdn' || key === 'verdict') ? 1 : -1; }
    document.querySelectorAll('th[data-key]').forEach(o => {
      o.classList.remove('sorted'); o.removeAttribute('data-arrow');
    });
    th.classList.add('sorted');
    th.setAttribute('data-arrow', sortDir === 1 ? '\\u2191' : '\\u2193');
    render();
  };
});

function drawTabs(cov){
  const total = Object.values(cov).reduce((a, b) => a + b, 0);
  document.getElementById('tabs').innerHTML = Object.keys(PART_LABELS).map(k => {
    const n = k === '' ? total : cov[k];
    // An empty slice is disabled rather than hidden: "not measured yet" is
    // information, and hiding it would read as a verdict about the CDNs.
    return `<button data-part="${k}" class="${k === part ? 'on' : ''}"
      ${n === 0 && k !== '' ? 'disabled' : ''}>${PART_LABELS[k]}
      <span class="count">${n}</span></button>`;
  }).join('');
  document.querySelectorAll('#tabs button').forEach(b => {
    b.onclick = () => { part = b.dataset.part; refresh(); };
  });
}

async function refresh(){
  const d = await (await fetch('api/state' + (part ? '?part=' + part : ''))).json();
  const s = d.state;

  const st = document.getElementById('status');
  st.textContent = s.phase || s.status;
  st.className = 'pill ' + (s.phase || s.status).replace(/\\s+/g, '-');

  document.getElementById('round').textContent = s.round || '-';
  document.getElementById('selected').textContent = s.selected_cdn || '-';
  document.getElementById('pause').textContent = s.pause;
  document.getElementById('hours').textContent = s.active_hours;
  document.getElementById('auto').textContent = s.auto_apply
    ? (s.applied_cdn ? 'on \\u2192 ' + s.applied_cdn : 'on') : 'off';
  document.getElementById('total').textContent = d.measurements;
  document.getElementById('detail').textContent = s.detail || '';
  document.getElementById('log').textContent = s.log.join('\\n');

  live = s.cdn || '';
  const now = document.getElementById('now');
  now.hidden = !live;
  if (live) {
    document.getElementById('now-cdn').textContent = live;
    document.getElementById('now-parole').hidden = !s.on_parole;
    document.getElementById('now-what').textContent =
      PHASES[s.phase] || s.detail || '';
    document.getElementById('now-pos').textContent =
      s.cdn_total ? `${s.cdn_index} of ${s.cdn_total}` : '';
  }

  rows = d.stats;
  benched = new Set(d.benched.map(b => b.cdn));
  drawTabs(d.coverage);
  render();

  const card = document.getElementById('bench-card');
  card.hidden = d.benched.length === 0;
  document.getElementById('bench').innerHTML = d.benched.map(b => `
    <div class="benched">
      <span class="name">${b.cdn}</span>
      <span class="why">${b.reason} &middot; since ${b.since.slice(5,16).replace('T',' ')}
        ${b.checks ? '&middot; re-tested ' + b.checks + 'x' : ''}</span>
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
       steady ${part ? 'in the ' + PART_LABELS[part].toLowerCase() : 'yet'}
       &mdash; each CDN needs at least two rounds${part ? ' in this slot' : ''}.</div>`;
}
document.getElementById('run').onclick = async e => {
  e.target.disabled = true;
  await fetch('api/run', {method:'POST'});
  setTimeout(() => { e.target.disabled = false; refresh(); }, 1500);
};
refresh(); setInterval(refresh, 3000);
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
            query = parse_qs(urlparse(self.path).query)
            part = (query.get("part") or [""])[0]
            part = part if part in PARTS else ""
            table = aggregate(records, part=part)
            pick = best(table)
            payload = {
                "state": self.runner.snapshot(),
                "stats": [s.as_dict() for s in table],
                "pick": pick.as_dict() if pick else None,
                "measurements": len(records),
                "part": part,
                "coverage": coverage(records),
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
