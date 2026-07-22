"""
03_dashboard.py  --  Build a self-contained interactive dashboard.

Reads ./output/targets.csv and writes ./output/dashboard.html: a single file
with the data embedded, no internet required. Open it in any browser.

Filter by signal / state / asset band / search, watch the per-signal bar chart
recompute on the filtered set, sort the table, and click any bank to drill into
the ratios behind its flags.
"""

import json
import pandas as pd

def current_repdte():
    try:
        return open("data/repdte.txt").read().strip()
    except FileNotFoundError:
        return "20260331"

COLS = [
    "CERT", "NAME", "CITY", "STALP", "asset_band", "asset_musd", "n_signals",
    "score", "signals", "EQV", "EQV_pct", "RBC1AAJ", "RBCT1CER", "ROA",
    "ROA_pct", "ROE", "NIMY", "EEFFR", "EEFFR_pct", "NCLNLSR", "NPERFV",
    "ELNANTR", "LNLSDEPR", "brokered_pct", "asset_growth_yoy",
]


def main():
    df = pd.read_csv("output/targets.csv")[COLS].copy()
    df["signals"] = df["signals"].fillna("")
    records = df.where(pd.notnull(df), None).to_dict(orient="records")

    rep = current_repdte()
    meta = {
        "quarter": f"Q{(int(rep[4:6]) - 1) // 3 + 1} {rep[:4]}",
        "date": f"{rep[4:6]}/{rep[:4]}",
        "flagged": len(df),
    }

    html = (
        TEMPLATE
        .replace("/*__DATA__*/", json.dumps(records))
        .replace("/*__META__*/", json.dumps(meta))
    )
    with open("output/dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote output/dashboard.html  ({len(df):,} banks)")

    # Artifact-ready fragment: the claude.ai Artifact host supplies its own
    # <!doctype>/<head>/<body>, so we emit only the <style> block + body inner
    # + <script> (no doctype/html/head/body tags of our own).
    style = html[html.index("<style>"): html.index("</style>") + len("</style>")]
    inner = html[html.index("<body>") + len("<body>"): html.index("</body>")]
    fragment = style + "\n" + inner
    with open("output/dashboard_artifact.html", "w", encoding="utf-8") as f:
        f.write(fragment)
    print("Wrote output/dashboard_artifact.html  (for private Artifact publishing)")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Community-Bank BD Screen</title>
<style>
  :root {
    color-scheme: light dark;
    --surface-1:#fcfcfb; --page:#f9f9f7;
    --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
    --grid:#e1e0d9; --baseline:#c3c2b7; --border:rgba(11,11,11,0.10);
    --series-1:#2a78d6; --series-soft:#cde2fb;
    --good:#006300; --warn:#b9770a; --crit:#c0392b;
    --chip-bg:#f0efec; --chip-active:#2a78d6;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface-1:#1a1a19; --page:#0d0d0d;
      --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,0.10);
      --series-1:#3987e5; --series-soft:#184f95;
      --good:#0ca30c; --warn:#fab219; --crit:#e66767;
      --chip-bg:#26262400; --chip-bg:#262624; --chip-active:#3987e5;
    }
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--page); color:var(--text-primary);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif; font-size:14px;
    line-height:1.45;
  }
  .wrap { max-width:1240px; margin:0 auto; padding:24px 20px 64px; }
  header h1 { margin:0 0 2px; font-size:22px; letter-spacing:-0.01em; }
  header p { margin:0; color:var(--text-secondary); }
  .tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:20px 0; }
  .tile {
    background:var(--surface-1); border:1px solid var(--border); border-radius:10px;
    padding:14px 16px;
  }
  .tile .k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .tile .v { font-size:26px; font-weight:600; margin-top:4px; }
  .tile .s { color:var(--text-secondary); font-size:12px; }
  .panel {
    background:var(--surface-1); border:1px solid var(--border); border-radius:10px;
    padding:16px; margin-bottom:16px;
  }
  .panel h2 { margin:0 0 12px; font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
  .filters { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-end; }
  .field { display:flex; flex-direction:column; gap:4px; }
  .field label { font-size:12px; color:var(--muted); }
  select, input[type=text] {
    background:var(--page); color:var(--text-primary); border:1px solid var(--baseline);
    border-radius:8px; padding:7px 10px; font:inherit; min-width:150px;
  }
  .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:2px; }
  .chip {
    border:1px solid var(--baseline); background:var(--chip-bg); color:var(--text-secondary);
    border-radius:999px; padding:5px 12px; font-size:12.5px; cursor:pointer; user-select:none;
  }
  .chip.on { background:var(--chip-active); color:#fff; border-color:var(--chip-active); }
  .chip .n { opacity:.7; margin-left:5px; font-variant-numeric:tabular-nums; }
  .barrow { display:grid; grid-template-columns:210px 1fr 46px; align-items:center; gap:10px; margin:6px 0; }
  .barrow .lab { font-size:12.5px; color:var(--text-secondary); text-align:right; }
  .bartrack { background:var(--grid); border-radius:5px; height:18px; overflow:hidden; }
  .barfill { background:var(--series-1); height:100%; border-radius:0 4px 4px 0; min-width:2px; transition:width .2s; }
  .barrow .cnt { font-size:12.5px; font-variant-numeric:tabular-nums; color:var(--text-primary); }
  .tablewrap { overflow-x:auto; }
  table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--grid); white-space:nowrap; }
  th { font-size:12px; color:var(--muted); cursor:pointer; user-select:none; position:sticky; top:0; background:var(--surface-1); }
  th.num, td.num { text-align:right; }
  tbody tr { cursor:pointer; }
  tbody tr:hover { background:color-mix(in srgb, var(--series-1) 7%, transparent); }
  .sigtags { display:flex; flex-wrap:wrap; gap:4px; white-space:normal; }
  .sigtag { font-size:11px; background:var(--chip-bg); border:1px solid var(--border); border-radius:5px; padding:1px 6px; color:var(--text-secondary); }
  .detail td { background:var(--page); }
  .detail-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:10px 20px; padding:6px 2px; }
  .metric { display:flex; justify-content:space-between; gap:10px; border-bottom:1px dotted var(--grid); padding:3px 0; }
  .metric .m { color:var(--text-secondary); }
  .metric .mv { font-variant-numeric:tabular-nums; }
  .hi { color:var(--crit); font-weight:600; }
  .lo { color:var(--warn); font-weight:600; }
  .gd { color:var(--good); font-weight:600; }
  .count-note { color:var(--muted); font-size:12px; margin:4px 2px 10px; }
  a.reset { color:var(--series-1); cursor:pointer; font-size:12px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Community-Bank BD Screen</h1>
    <p id="sub"></p>
  </header>

  <div class="tiles" id="tiles"></div>

  <div class="panel">
    <h2>Filters &nbsp; <a class="reset" onclick="resetAll()">reset</a></h2>
    <div class="filters">
      <div class="field">
        <label>Search name / city</label>
        <input type="text" id="q" placeholder="e.g. Republic, Miami" oninput="render()">
      </div>
      <div class="field">
        <label>State</label>
        <select id="state" onchange="render()"></select>
      </div>
      <div class="field">
        <label>Asset band</label>
        <select id="band" onchange="render()">
          <option value="">All sizes</option>
          <option>&lt;$250M</option><option>$250M-$1B</option>
          <option>$1B-$3B</option><option>$3B-$10B</option>
        </select>
      </div>
      <div class="field">
        <label>Min. signals</label>
        <select id="minsig" onchange="render()">
          <option value="1">1+</option><option value="2">2+</option>
          <option value="3">3+</option><option value="4">4+</option><option value="5">5+</option>
        </select>
      </div>
      <div class="field">
        <label>Signal match</label>
        <select id="mode" onchange="render()">
          <option value="any">Any selected</option>
          <option value="all">All selected</option>
        </select>
      </div>
    </div>
    <div class="chips" id="sigchips"></div>
  </div>

  <div class="panel">
    <h2>Banks flagged per signal <span id="barnote" style="text-transform:none;color:var(--text-secondary)"></span></h2>
    <div id="bars"></div>
  </div>

  <div class="panel">
    <h2>Target list</h2>
    <div class="count-note" id="cnote"></div>
    <div class="tablewrap"><table id="tbl">
      <thead><tr id="hrow"></tr></thead>
      <tbody id="tbody"></tbody>
    </table></div>
  </div>
</div>

<script>
const DATA = /*__DATA__*/;
const META = /*__META__*/;

const SIGNALS = [
  ["excess_capital","Excess capital","opportunity"],
  ["credit_deterioration","Credit deterioration","stress"],
  ["under_reserved","Under-reserved","stress"],
  ["weak_efficiency","Weak efficiency","stress"],
  ["funding_liquidity","Funding / liquidity","stress"],
  ["rapid_growth","Rapid growth","opportunity"],
  ["near_10b_threshold","Approaching $10B","opportunity"],
  ["weak_profitability","Weak profitability","stress"],
  ["bsa_aml_scaling","BSA/AML scaling","stress"],
];
const SIGLAB = Object.fromEntries(SIGNALS.map(s => [s[0], s[1]]));

const COLDEFS = [
  ["NAME","Bank",false], ["STALP","St",false], ["CITY","City",false],
  ["asset_musd","Assets $M",true], ["asset_band","Band",false],
  ["score","Score",true], ["n_signals","#",true], ["signals","Signals",false],
];
const METRICS = [
  ["EQV","Equity / assets","%",1], ["RBC1AAJ","Tier 1 leverage","%",1],
  ["RBCT1CER","CET1 ratio","%",1], ["ROA","ROA","%",2], ["ROE","ROE","%",1],
  ["NIMY","Net interest margin","%",2], ["EEFFR","Efficiency ratio","%",1],
  ["NCLNLSR","Net charge-offs / loans","%",2], ["NPERFV","Noncurrent assets / assets","%",2],
  ["ELNANTR","Reserve coverage of noncurrent","%",0],
  ["LNLSDEPR","Loan / deposit","%",1], ["brokered_pct","Brokered / deposits","pct",1],
  ["asset_growth_yoy","Asset growth YoY","pct",1],
];

let selected = new Set();
let sortKey = "score", sortDir = -1;

function fmt(v, kind, dec) {
  if (v === null || v === undefined || v === "" || Number.isNaN(v)) return "—";
  if (kind === "pct") return (v*100).toFixed(dec) + "%";
  if (kind === "%") return Number(v).toFixed(dec) + "%";
  return Number(v).toLocaleString(undefined,{maximumFractionDigits:dec});
}
function sigList(r){ return r.signals ? r.signals.split("; ") : []; }

function passes(r) {
  const q = document.getElementById("q").value.trim().toLowerCase();
  if (q && !((r.NAME||"").toLowerCase().includes(q) || (r.CITY||"").toLowerCase().includes(q))) return false;
  const st = document.getElementById("state").value;
  if (st && r.STALP !== st) return false;
  const bd = document.getElementById("band").value;
  if (bd && r.asset_band !== bd) return false;
  if (r.n_signals < +document.getElementById("minsig").value) return false;
  if (selected.size) {
    const s = sigList(r), mode = document.getElementById("mode").value;
    const arr = [...selected];
    if (mode === "all" ? !arr.every(x=>s.includes(x)) : !arr.some(x=>s.includes(x))) return false;
  }
  return true;
}

function render() {
  const rows = DATA.filter(passes);
  renderTiles(rows);
  renderChips(rows);
  renderBars(rows);
  renderTable(rows);
}

function renderTiles(rows) {
  const ge3 = rows.filter(r=>r.n_signals>=3).length;
  const near = rows.filter(r=>sigList(r).includes("near_10b_threshold")).length;
  const cap  = rows.filter(r=>sigList(r).includes("excess_capital")).length;
  const t = [
    ["Banks in view", rows.length.toLocaleString(), "match current filters"],
    ["3+ signals", ge3.toLocaleString(), "stacked opportunities"],
    ["Excess capital", cap.toLocaleString(), "deployment / M&A conversations"],
    ["Approaching $10B", near.toLocaleString(), "$8B–$10B, tier-readiness"],
  ];
  document.getElementById("tiles").innerHTML = t.map(x=>
    `<div class="tile"><div class="k">${x[0]}</div><div class="v">${x[1]}</div><div class="s">${x[2]}</div></div>`).join("");
}

function renderChips(rows) {
  const counts = {};
  SIGNALS.forEach(s=>counts[s[0]]=0);
  rows.forEach(r=>sigList(r).forEach(s=>{ if(s in counts) counts[s]++; }));
  document.getElementById("sigchips").innerHTML = SIGNALS.map(s=>
    `<span class="chip ${selected.has(s[0])?"on":""}" onclick="toggle('${s[0]}')">${s[1]}<span class="n">${counts[s[0]]}</span></span>`
  ).join("");
}

function renderBars(rows) {
  const counts = {};
  SIGNALS.forEach(s=>counts[s[0]]=0);
  rows.forEach(r=>sigList(r).forEach(s=>{ if(s in counts) counts[s]++; }));
  const max = Math.max(1, ...Object.values(counts));
  const ordered = SIGNALS.slice().sort((a,b)=>counts[b[0]]-counts[a[0]]);
  document.getElementById("bars").innerHTML = ordered.map(s=>{
    const c = counts[s[0]], w = (c/max*100).toFixed(1);
    return `<div class="barrow"><div class="lab">${s[1]}</div>`+
           `<div class="bartrack"><div class="barfill" style="width:${w}%" title="${s[1]}: ${c} banks"></div></div>`+
           `<div class="cnt">${c}</div></div>`;
  }).join("");
  document.getElementById("barnote").textContent = ` — within the ${rows.length.toLocaleString()} banks in view`;
}

function renderTable(rows) {
  rows.sort((a,b)=>{
    let x=a[sortKey], y=b[sortKey];
    if (typeof x==="string"||typeof y==="string"){ x=(x||"");y=(y||""); return sortDir*(x<y?-1:x>y?1:0); }
    return sortDir*((x||0)-(y||0));
  });
  document.getElementById("hrow").innerHTML = COLDEFS.map(c=>{
    const arrow = sortKey===c[0] ? (sortDir<0?" ▾":" ▴") : "";
    return `<th class="${c[2]?"num":""}" onclick="sortBy('${c[0]}')">${c[1]}${arrow}</th>`;
  }).join("");
  const cap = 400;
  const show = rows.slice(0, cap);
  document.getElementById("cnote").innerHTML =
    `Showing ${show.length.toLocaleString()} of ${rows.length.toLocaleString()} banks` +
    (rows.length>cap?` (top ${cap} by current sort — narrow the filters to see the rest)`:"");
  document.getElementById("tbody").innerHTML = show.map((r,i)=>{
    const tags = sigList(r).map(s=>`<span class="sigtag">${SIGLAB[s]||s}</span>`).join("");
    return `<tr onclick="expand(${i})" data-i="${i}">`+
      `<td>${r.NAME||""}</td><td>${r.STALP||""}</td><td>${r.CITY||""}</td>`+
      `<td class="num">${fmt(r.asset_musd,"num",0)}</td><td>${r.asset_band||""}</td>`+
      `<td class="num">${r.score}</td><td class="num">${r.n_signals}</td>`+
      `<td><div class="sigtags">${tags}</div></td></tr>`;
  }).join("");
  window._show = show;
}

function expand(i) {
  const r = window._show[i];
  const existing = document.querySelector(`tr.detail[data-for="${i}"]`);
  document.querySelectorAll("tr.detail").forEach(e=>e.remove());
  if (existing) return;
  const fired = new Set(sigList(r));
  const cells = METRICS.map(m=>{
    let cls="mv";
    if (m[0]==="EQV" && fired.has("excess_capital")) cls="mv gd";
    if (["NCLNLSR","NPERFV"].includes(m[0]) && fired.has("credit_deterioration")) cls="mv hi";
    if (m[0]==="EEFFR" && fired.has("weak_efficiency")) cls="mv hi";
    if (m[0]==="ROA" && fired.has("weak_profitability")) cls="mv lo";
    if (["LNLSDEPR","brokered_pct"].includes(m[0]) && fired.has("funding_liquidity")) cls="mv hi";
    if (m[0]==="asset_growth_yoy" && fired.has("rapid_growth")) cls="mv gd";
    return `<div class="metric"><span class="m">${m[1]}</span><span class="${cls}">${fmt(r[m[0]],m[2],m[3])}</span></div>`;
  }).join("");
  const svc = sigList(r).map(s=>SIGLAB[s]).join(" · ");
  const tr = document.createElement("tr");
  tr.className="detail"; tr.dataset.for=i;
  tr.innerHTML = `<td colspan="8"><div style="padding:4px 2px 10px">`+
    `<div style="color:var(--text-secondary);margin-bottom:8px">FDIC CERT ${r.CERT} &nbsp;•&nbsp; flagged: ${svc}</div>`+
    `<div class="detail-grid">${cells}</div></div></td>`;
  const rowEl = document.querySelector(`tr[data-i="${i}"]`);
  rowEl.after(tr);
}

function toggle(s){ selected.has(s)?selected.delete(s):selected.add(s); render(); }
function sortBy(k){ if(sortKey===k) sortDir*=-1; else {sortKey=k; sortDir=(k==="NAME"||k==="CITY"||k==="STALP"||k==="asset_band")?1:-1;} render(); }
function resetAll(){ selected.clear(); document.getElementById("q").value="";
  ["state","band"].forEach(id=>document.getElementById(id).value="");
  document.getElementById("minsig").value="1"; document.getElementById("mode").value="any"; render(); }

function init(){
  document.getElementById("sub").textContent =
    `${META.flagged.toLocaleString()} banks flagged of the U.S. community-bank universe (under $10B) — FDIC data, ${META.quarter}.`;
  const states = [...new Set(DATA.map(r=>r.STALP).filter(Boolean))].sort();
  document.getElementById("state").innerHTML =
    '<option value="">All states</option>' + states.map(s=>`<option>${s}</option>`).join("");
  render();
}
init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
