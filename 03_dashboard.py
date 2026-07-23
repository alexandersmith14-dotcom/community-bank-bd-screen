"""
03_dashboard.py  --  Build a self-contained interactive dashboard.

Reads ./output/targets.csv and writes ./output/dashboard.html: a single file
with the data embedded, no internet required. Open it in any browser.

Filter by signal / state / asset band / search, watch the per-signal bar chart
recompute on the filtered set, sort the table, and click any bank to drill into
the ratios behind its flags.
"""

import json
import os
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
# Trajectory columns present only when 05_trajectory.py has run; embedded when found.
TRAJ_COLS = [
    "EQV_slope", "EQV_d2y", "ROA_slope", "asset_yoy", "asset_accel",
    "runway_q", "n_quarters",
]
# Credit-union financial columns (present only when 08_cu_screen.py has run).
CU_COLS = [
    "NW_RATIO", "NW_RATIO_pct", "DELINQ", "NCO", "LOAN_TO_SHARE",
    "EXP_RATIO", "MEMBERS",
]
# Fintech columns (present only when 09_fintech.py has run).
FT_COLS = ["FT_STATES", "FT_ACTIVITIES", "FT_BRANCHES", "FT_DBA", "FT_KNOWN"]


def main():
    banks = pd.read_csv("output/targets.csv")
    banks["INST_TYPE"] = "Bank"
    frames = [banks]
    if os.path.exists("output/cu_targets.csv"):
        frames.append(pd.read_csv("output/cu_targets.csv"))
    if os.path.exists("output/ft_targets.csv"):
        frames.append(pd.read_csv("output/ft_targets.csv"))
    raw = pd.concat(frames, ignore_index=True, sort=False)

    has_trend = all(c in raw.columns for c in TRAJ_COLS)
    embed = ["INST_TYPE"] + COLS + CU_COLS + FT_COLS + (TRAJ_COLS if has_trend else [])
    cols = [c for c in dict.fromkeys(embed) if c in raw.columns]
    df = raw[cols].copy()
    df["signals"] = df["signals"].fillna("")
    records = df.where(pd.notnull(df), None).to_dict(orient="records")

    # Bank CERTs only — sparklines and EDGAR are bank-side (avoid CU id collisions).
    bank_certs = {str(int(c)) for c, t in zip(df["CERT"], df["INST_TYPE"])
                  if t == "Bank" and pd.notnull(c)}

    spark = {"quarters": [], "series": {}}
    if os.path.exists("output/spark.json"):
        full = json.load(open("output/spark.json"))
        spark = {"quarters": full["quarters"],
                 "series": {k: v for k, v in full["series"].items() if k in bank_certs}}

    edgar = {}
    if os.path.exists("output/edgar_officers.json"):
        full = json.load(open("output/edgar_officers.json"))
        edgar = {k: v for k, v in full.items() if k in bank_certs}

    cu_certs = {str(int(c)) for c, t in zip(df["CERT"], df["INST_TYPE"])
                if t == "Credit Union" and pd.notnull(c)}
    cu_spark = {"quarters": [], "series": {}}
    if os.path.exists("output/cu_spark.json"):
        full = json.load(open("output/cu_spark.json"))
        cu_spark = {"quarters": full["quarters"],
                    "series": {k: v for k, v in full["series"].items() if k in cu_certs}}

    rep = current_repdte()
    n_bank = int((df["INST_TYPE"] == "Bank").sum())
    n_cu = int((df["INST_TYPE"] == "Credit Union").sum())
    n_ft = int((df["INST_TYPE"] == "Fintech").sum())
    meta = {
        "quarter": f"Q{(int(rep[4:6]) - 1) // 3 + 1} {rep[:4]}",
        "date": f"{rep[4:6]}/{rep[:4]}",
        "flagged": len(df),
        "nBank": n_bank,
        "nCU": n_cu,
        "nFT": n_ft,
        "hasTrend": has_trend,
    }

    html = (
        TEMPLATE
        .replace("/*__DATA__*/", json.dumps(records))
        .replace("/*__META__*/", json.dumps(meta))
        .replace("/*__SPARK__*/", json.dumps(spark))
        .replace("/*__EDGAR__*/", json.dumps(edgar))
        .replace("/*__CU_SPARK__*/", json.dumps(cu_spark))
    )
    with open("output/dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote output/dashboard.html  ({n_bank:,} banks + {n_cu:,} credit unions + {n_ft:,} fintechs)")

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
  .tile.clickable { cursor:pointer; transition:border-color .12s, transform .12s; }
  .tile.clickable:hover { border-color:var(--series-1); transform:translateY(-1px); }
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
  .chiplead { font-size:12px; color:var(--muted); margin:14px 2px 8px; }
  #sigchips { display:flex; flex-direction:column; gap:12px; }
  .chipgroup { display:grid; grid-template-columns:210px 1fr; gap:12px; align-items:start; }
  .chipgroup-lab { font-size:11.5px; font-weight:600; color:var(--text-secondary); text-transform:uppercase; letter-spacing:.03em; padding-top:6px; }
  @media (max-width:640px){ .chipgroup { grid-template-columns:1fr; gap:4px; } .chipgroup-lab { padding-top:0; } }
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
  .chip.trend { border-style:dashed; }
  .chip.trend.on { border-style:solid; }
  .detail td { background:var(--page); }
  .detail-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:10px 20px; padding:6px 2px; }
  .svcmap { display:flex; flex-direction:column; gap:5px; padding:2px; }
  .svcrow { display:grid; grid-template-columns:150px 1fr; align-items:center; gap:10px; }
  .svc { font-size:12.5px; color:var(--text-primary); }
  .svc.refer { color:var(--muted); font-style:italic; }
  .trendhdr { margin:14px 2px 8px; font-size:13px; font-weight:600; }
  .trendhdr .muted { font-weight:400; }
  .muted { color:var(--muted); }
  .sparkgrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px 18px; padding:2px; }
  .sparkbox { border:1px solid var(--border); border-radius:8px; padding:8px 10px; background:var(--surface-1); }
  .sparklab { font-size:12px; color:var(--text-secondary); margin-bottom:4px; }
  svg.spark { width:100%; height:30px; display:block; }
  .sparkval { font-size:13px; font-variant-numeric:tabular-nums; margin-top:2px; }
  .metric { display:flex; justify-content:space-between; gap:10px; border-bottom:1px dotted var(--grid); padding:3px 0; }
  .metric .m { color:var(--text-secondary); }
  .metric .mv { font-variant-numeric:tabular-nums; }
  .hi { color:var(--crit); font-weight:600; }
  .lo { color:var(--warn); font-weight:600; }
  .gd { color:var(--good); font-weight:600; }
  .count-note { color:var(--muted); font-size:12px; margin:4px 2px 10px; }
  .ovgrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:22px; }
  .ovh { font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; margin-bottom:8px; }
  #overview .barrow { grid-template-columns:150px 1fr 40px; }
  a.reset { color:var(--series-1); cursor:pointer; font-size:12px; }
  #tip { position:fixed; z-index:1000; max-width:300px; background:var(--text-primary); color:var(--page);
         padding:8px 11px; border-radius:8px; font-size:12px; line-height:1.4; pointer-events:none;
         opacity:0; transition:opacity .1s; box-shadow:0 6px 20px rgba(0,0,0,.28); }
  [data-tip] { cursor:help; }
  .chip[data-tip], .tile[data-tip] { cursor:pointer; }
  a.ldlink { display:inline-block; color:#fff; background:var(--series-1); text-decoration:none;
             font-size:13px; font-weight:600; padding:7px 14px; border-radius:8px; }
  a.ldlink:hover { filter:brightness(1.08); }
  .pub { font-size:10.5px; font-weight:600; color:var(--good); border:1px solid var(--good); border-radius:4px; padding:0 4px; vertical-align:middle; }
  .cu { font-size:10.5px; font-weight:600; color:var(--series-1); border:1px solid var(--series-1); border-radius:4px; padding:0 4px; vertical-align:middle; }
  .ft { font-size:10.5px; font-weight:600; color:#7b5cff; border:1px solid #7b5cff; border-radius:4px; padding:0 4px; vertical-align:middle; }
  .offlist { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:3px 18px; padding:2px 2px 6px; }
  .offrow { display:flex; justify-content:space-between; gap:10px; border-bottom:1px dotted var(--grid); padding:3px 0; }
  .offname { font-weight:600; font-size:12.5px; }
  .offtitle { color:var(--text-secondary); font-size:11.5px; text-align:right; }
</style>
</head>
<body>
<div id="tip"></div>
<div class="wrap">
  <header>
    <h1>Community-Bank BD Screen</h1>
    <p id="sub"></p>
  </header>

  <div class="tiles" id="tiles"></div>

  <div class="panel">
    <h2>Overview / market map &nbsp; <a class="reset" onclick="toggleOverview()" id="ovtoggle">show ▾</a></h2>
    <div id="overview" style="display:none"></div>
  </div>

  <div class="panel">
    <h2>Filters &nbsp; <a class="reset" onclick="resetAll()">reset</a></h2>
    <div class="filters">
      <div class="field">
        <label>Search name / city</label>
        <input type="text" id="q" placeholder="e.g. Republic, Miami" oninput="render()">
      </div>
      <div class="field">
        <label>Institution type</label>
        <select id="itype" onchange="render()">
          <option value="">All types</option>
          <option value="Bank">Banks only</option>
          <option value="Credit Union">Credit Unions only</option>
          <option value="Fintech">Fintechs only</option>
        </select>
      </div>
      <div class="field">
        <label>KR RAS service line</label>
        <select id="svcline" onchange="render()"></select>
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
          <option>$1B-$3B</option><option>$3B+</option>
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
    <div class="chiplead">Filter by signal — grouped by the KR RAS service line each one feeds. <b>Hover any pill for its criteria.</b></div>
    <div id="sigchips"></div>
  </div>

  <div class="panel">
    <h2>Banks flagged per signal <span id="barnote" style="text-transform:none;color:var(--text-secondary)"></span></h2>
    <div id="bars"></div>
  </div>

  <div class="panel">
    <h2>Target list &nbsp; <a class="reset" onclick="downloadCSV()">⬇ download this view (CSV)</a></h2>
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
const SPARK = /*__SPARK__*/;
const EDGAR = /*__EDGAR__*/;
const CU_SPARK = /*__CU_SPARK__*/;

const SIGNALS = [
  ["excess_capital","Excess capital","snapshot"],
  ["credit_deterioration","Credit deterioration","snapshot"],
  ["under_reserved","Under-reserved","snapshot"],
  ["weak_efficiency","Weak efficiency","snapshot"],
  ["funding_liquidity","Funding / liquidity","snapshot"],
  ["rapid_growth","Rapid growth","snapshot"],
  ["near_10b_threshold","Approaching $10B","snapshot"],
  ["near_fdicia_1b","Near $1B (FDICIA)","snapshot"],
  ["near_500m_audit","Crossed $500M (CU audit)","snapshot"],
  ["weak_profitability","Weak profitability","snapshot"],
  ["bsa_aml_scaling","BSA/AML scaling","snapshot"],
  // 5-year trajectory signals (direction of travel)
  ["capital_building","Capital building ↗","trend"],
  ["credit_turning","Credit turning ↗","trend"],
  ["growth_accelerating","Growth accelerating ↗","trend"],
  ["runway_to_10b","Runway to $10B","trend"],
  ["margin_eroding","Margin eroding ↘","trend"],
  // Fintech (MSB) regulatory-footprint signals
  ["ft_national","National transmitter (40+ st)","fintech"],
  ["ft_fullstack","Full payments stack","fintech"],
  ["ft_multistate","Multistate transmitter","fintech"],
  ["ft_prepaid","Prepaid access","fintech"],
  ["ft_fx_crypto","FX / crypto","fintech"],
];
const SIGLAB = Object.fromEntries(SIGNALS.map(s => [s[0], s[1]]));

// Signal -> KR Risk Advisory Services line (kept in step with the Python maps).
const SIGSERVICE = {
  near_10b_threshold:  "$10B readiness — Consumer Compliance (CFPB), BSA/AML, Internal Audit; ICFR / stress-testing (FDICIA banks, NCUA credit unions)",
  runway_to_10b:       "$10B runway — Consumer Compliance, BSA/AML, Internal Audit; FDICIA ICFR attestation",
  near_fdicia_1b:      "FDICIA Part 363 ICFR attestation readiness + Internal Audit (approaching/crossing $1B)",
  near_500m_audit:     "NCUA Part 715 CPA financial-statement audit / supervisory committee support (credit unions newly over $500M)",
  bsa_aml_scaling:     "BSA/AML program enhancement + independent testing",
  rapid_growth:        "BSA/AML scaling, Internal Audit, risk assessment; FDICIA ICFR if crossing $1B",
  growth_accelerating: "BSA/AML scaling + Internal Audit; FDICIA ICFR readiness if crossing $1B",
  credit_deterioration:"Internal Audit loan review + CECL model validation + ALLL/CECL governance",
  credit_turning:      "Early Internal Audit loan review + CECL model validation",
  weak_efficiency:     "Robotic Process Automation (RPA) + Internal Audit process review",
  under_reserved:      "CECL model validation / reserve adequacy review",
  funding_liquidity:   "Internal Audit of liquidity/funding risk controls (partial)",
  margin_eroding:      "RPA cost automation (partial)",
  excess_capital:      "Refer — capital deployment / M&A (other KR practice)",
  capital_building:    "Refer — capital deployment / M&A (other KR practice)",
  weak_profitability:  "Refer — earnings / margin advisory (other KR practice)",
  ft_national:         "BSA/AML program + independent testing; multistate money-transmitter licensing (40+ states)",
  ft_fullstack:        "Enterprise BSA/AML program, independent testing, SOC/audit (money transmitter + prepaid)",
  ft_multistate:       "BSA/AML program + independent testing; state MTL compliance (scaling)",
  ft_prepaid:          "BSA/AML + FinCEN prepaid-access rule compliance; consumer compliance",
  ft_fx_crypto:        "BSA/AML for virtual-currency / FX money transmission; OFAC/sanctions",
};

// Signal pills grouped under the KR RAS service line they feed.
const CHIP_GROUPS = [
  ["BSA/AML & Sanctions", ["bsa_aml_scaling","rapid_growth","growth_accelerating"]],
  ["FDICIA / audit / $10B readiness", ["near_fdicia_1b","near_500m_audit","near_10b_threshold","runway_to_10b"]],
  ["Internal Audit & CECL (credit)", ["credit_deterioration","under_reserved","credit_turning"]],
  ["Robotic Process Automation", ["weak_efficiency","margin_eroding"]],
  ["Internal Audit — liquidity", ["funding_liquidity"]],
  ["Fintech — BSA/AML & licensing", ["ft_national","ft_fullstack","ft_multistate","ft_prepaid","ft_fx_crypto"]],
  ["Refer — other KR practice", ["excess_capital","weak_profitability","capital_building"]],
];

// Plain-language criteria shown on hover.
const DESC = {
  excess_capital: "Equity/assets in the top 20% of its size peer group — well-capitalized, with a deployment question.",
  credit_deterioration: "Net charge-offs or noncurrent assets in the worst 15% of size peers.",
  under_reserved: "Credit deterioration AND loan-loss allowance under 40% of noncurrent loans.",
  weak_efficiency: "Efficiency ratio 70%+ and among the worst 20% of size peers (heavy cost base).",
  funding_liquidity: "Loan-to-deposit 100%+, or worst 15% of peers, or brokered deposits 10%+ of deposits.",
  rapid_growth: "Total assets up 15%+ year over year.",
  near_10b_threshold: "Assets between $8B and $10B — approaching the $10B regulatory tier.",
  near_fdicia_1b: "Assets between $850M and $1.15B — around the $1B FDICIA ICFR trigger.",
  near_500m_audit: "Credit unions $500M–$650M — just crossed the $500M NCUA Part 715 CPA-audit threshold (first-time audit).",
  weak_profitability: "ROA in the bottom 15% of size peers, or negative.",
  bsa_aml_scaling: "Assets up 20%+ year over year — growth outpacing the compliance program.",
  capital_building: "5-year trend: equity/assets rising 0.40+ pts per year and +0.75 pts over 2 years.",
  credit_turning: "5-year trend: charge-offs or noncurrent rising 0.15+ pts per year.",
  growth_accelerating: "5-year trend: assets 10%+ YoY and 3+ pts faster than the year before.",
  runway_to_10b: "5-year trend: $5B+ now and on pace to cross $10B within 12 quarters.",
  margin_eroding: "5-year trend: ROA falling and efficiency ratio rising (worsening margins).",
  ft_national: "Registered money transmitter operating in 40+ states — maximal BSA/AML + multistate-licensing burden.",
  ft_fullstack: "Money transmitter AND prepaid-access provider — a full payments stack (a better real-fintech signal).",
  ft_multistate: "Money transmitter operating in 10–39 states — scaling multistate compliance.",
  ft_prepaid: "Provides or sells prepaid access (cards/stored value) — FinCEN prepaid-rule + BSA/AML.",
  ft_fx_crypto: "Currency dealer / FX — often crypto or cross-border; heavy BSA/AML and sanctions exposure.",
};
const GROUP_DESC = {
  "BSA/AML & Sanctions": "KR RAS: BSA/AML program build & independent testing, OFAC/sanctions.",
  "FDICIA / audit / $10B readiness": "KR RAS: FDICIA ICFR (banks) & NCUA $500M CPA audit (credit unions); $10B-tier readiness (CFPB, stress testing).",
  "Internal Audit & CECL (credit)": "KR RAS: Internal Audit loan review, CECL model validation, ALLL governance.",
  "Robotic Process Automation": "KR RAS: automating manual compliance and back-office processes.",
  "Internal Audit — liquidity": "KR RAS: Internal Audit of liquidity and funding risk controls.",
  "Refer — other KR practice": "Not RAS — refer to capital/M&A or earnings advisory; shown for completeness.",
  "Fintech — BSA/AML & licensing": "KR RAS: BSA/AML programs & independent testing, money-transmitter licensing, prepaid/OFAC for payment fintechs (FinCEN MSB registry).",
};
const TILE_DESC = {
  all: "Reset every filter and show the full flagged list.",
  ge3: "Banks tripping 3 or more signals — the densest opportunities.",
  aml: "Banks flagged for BSA/AML scaling, rapid growth, or accelerating growth.",
  ten: "Banks approaching $10B or on a short runway to it.",
};
function esc(s){ return String(s).replace(/"/g,"&quot;"); }

// Decision-maker titles to target on LinkedIn, by service-line group.
const LD_TITLES = {
  "BSA/AML & Sanctions": ["BSA Officer","Chief Compliance Officer","AML"],
  "FDICIA / audit / $10B readiness": ["Chief Financial Officer","Controller","Chief Risk Officer","Supervisory Committee"],
  "Internal Audit & CECL (credit)": ["Chief Audit Executive","Internal Audit","Chief Risk Officer","Chief Credit Officer"],
  "Robotic Process Automation": ["Chief Operating Officer"],
  "Internal Audit — liquidity": ["Treasurer","Chief Financial Officer"],
  "Refer — other KR practice": ["President","Chief Executive Officer"],
  "Fintech — BSA/AML & licensing": ["BSA Officer","Chief Compliance Officer","Chief Risk Officer","General Counsel","Head of Compliance"],
};

// Build a LinkedIn people-search URL for this bank's relevant decision-makers.
// Just a deep link into LinkedIn's normal search UI — the user reviews and
// connects manually. No automation, no scraping.
function linkedinSearch(r) {
  const fired = new Set(sigList(r));
  const titles = new Set(["Chief Executive Officer","President"]);
  CHIP_GROUPS.forEach(g => {
    if (g[1].some(k=>fired.has(k))) (LD_TITLES[g[0]]||[]).forEach(t=>titles.add(t));
  });
  const titleStr = [...titles].slice(0,6).map(t=>`"${t}"`).join(" OR ");
  const kw = `"${r.NAME}" (${titleStr})`;
  return { url: "https://www.linkedin.com/search/results/people/?keywords=" + encodeURIComponent(kw),
           titles: [...titles].slice(0,6) };
}

const COLDEFS = [
  ["NAME","Bank",false], ["STALP","St",false], ["CITY","City",false],
  ["asset_musd","Assets $M",true], ["asset_band","Band",false],
  ["score","Score",true], ["n_signals","#",true], ["signals","Signals",false],
];
const METRICS_BANK = [
  ["EQV","Equity / assets","%",1], ["RBC1AAJ","Tier 1 leverage","%",1],
  ["RBCT1CER","CET1 ratio","%",1], ["ROA","ROA","%",2], ["ROE","ROE","%",1],
  ["NIMY","Net interest margin","%",2], ["EEFFR","Efficiency ratio","%",1],
  ["NCLNLSR","Net charge-offs / loans","%",2], ["NPERFV","Noncurrent assets / assets","%",2],
  ["ELNANTR","Reserve coverage of noncurrent","%",0],
  ["LNLSDEPR","Loan / deposit","%",1], ["brokered_pct","Brokered / deposits","pct",1],
  ["asset_growth_yoy","Asset growth YoY","pct",1],
];
const METRICS_CU = [
  ["NW_RATIO","Net worth ratio","%",2], ["ROA","ROA","%",2],
  ["DELINQ","Delinquency / loans","%",2], ["NCO","Net charge-offs / loans","%",2],
  ["LOAN_TO_SHARE","Loan / share","%",1], ["EXP_RATIO","Operating exp / assets","%",2],
  ["MEMBERS","Members","num",0], ["asset_growth_yoy","Asset growth YoY","pct",1],
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
  const it = document.getElementById("itype").value;
  if (it && r.INST_TYPE !== it) return false;
  const sl = document.getElementById("svcline").value;
  if (sl) {
    const grp = CHIP_GROUPS.find(g=>g[0]===sl);
    if (grp && !grp[1].some(k=>sigList(r).includes(k))) return false;
  }
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
  const has = (r,...ks)=>ks.some(k=>sigList(r).includes(k));
  const ge3 = rows.filter(r=>r.n_signals>=3).length;
  const aml = rows.filter(r=>has(r,"bsa_aml_scaling","rapid_growth","growth_accelerating")).length;
  const ten = rows.filter(r=>has(r,"near_10b_threshold","runway_to_10b")).length;
  const nb = rows.filter(r=>r.INST_TYPE==="Bank").length;
  const ncu = rows.filter(r=>r.INST_TYPE==="Credit Union").length;
  const nft = rows.filter(r=>r.INST_TYPE==="Fintech").length;
  const t = [
    ["Institutions in view", rows.length.toLocaleString(), `${nb.toLocaleString()} bk · ${ncu.toLocaleString()} cu · ${nft.toLocaleString()} ft`, "all"],
    ["3+ signals", ge3.toLocaleString(), "stacked RAS opportunities", "ge3"],
    ["AML / growth prospects", aml.toLocaleString(), "BSA/AML + Internal Audit", "aml"],
    ["$10B-tier prospects", ten.toLocaleString(), "Consumer Compliance + IA readiness", "ten"],
  ];
  document.getElementById("tiles").innerHTML = t.map(x=>
    `<div class="tile clickable" onclick="tileAction('${x[3]}')" data-tip="${esc(TILE_DESC[x[3]]||"")}">`+
    `<div class="k">${x[0]}</div><div class="v">${x[1]}</div><div class="s">${x[2]}</div></div>`).join("");
}

function tileAction(key) {
  const set = (id,v)=>document.getElementById(id).value=v;
  if (key==="all") { resetAll(); return; }
  if (key==="ge3") { selected.clear(); set("minsig","3"); set("mode","any"); }
  if (key==="aml") { selected = new Set(["bsa_aml_scaling","rapid_growth","growth_accelerating"]); set("mode","any"); set("minsig","1"); }
  if (key==="ten") { selected = new Set(["near_10b_threshold","runway_to_10b"]); set("mode","any"); set("minsig","1"); }
  render();
  window.scrollTo({top:document.querySelector('#tbl').offsetTop-80, behavior:'smooth'});
}

function renderChips(rows) {
  const counts = {};
  SIGNALS.forEach(s=>counts[s[0]]=0);
  rows.forEach(r=>sigList(r).forEach(s=>{ if(s in counts) counts[s]++; }));
  const cat = Object.fromEntries(SIGNALS.map(s=>[s[0], s[2]]));
  document.getElementById("sigchips").innerHTML = CHIP_GROUPS.map(g=>{
    const chips = g[1].map(k=>
      `<span class="chip ${cat[k]} ${selected.has(k)?"on":""}" data-tip="${esc(DESC[k]||"")}" onclick="toggle('${k}')">${SIGLAB[k]}<span class="n">${counts[k]}</span></span>`
    ).join("");
    return `<div class="chipgroup"><div class="chipgroup-lab" data-tip="${esc(GROUP_DESC[g[0]]||"")}">${g[0]}</div><div class="chips">${chips}</div></div>`;
  }).join("");
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
    const isBank = r.INST_TYPE==="Bank";
    const eg = isBank ? EDGAR[String(r.CERT)] : null;
    const pub = eg ? ` <span class="pub" title="Public — SEC registrant">${eg.ticker||"public"}</span>` : "";
    let tag = "";
    if (r.INST_TYPE==="Credit Union") tag = ` <span class="cu" title="Credit union (NCUA)">CU</span>`;
    else if (r.INST_TYPE==="Fintech") tag = ` <span class="ft" title="Fintech / MSB (FinCEN)">${r.FT_KNOWN?"FINTECH":"MSB"}</span>`;
    return `<tr onclick="expand(${i})" data-i="${i}">`+
      `<td>${r.NAME||""}${tag}${pub}</td><td>${r.STALP||""}</td><td>${r.CITY||""}</td>`+
      `<td class="num">${fmt(r.asset_musd,"num",0)}</td><td>${r.asset_band||""}</td>`+
      `<td class="num">${r.score}</td><td class="num">${r.n_signals}</td>`+
      `<td><div class="sigtags">${tags}</div></td></tr>`;
  }).join("");
  window._show = show;
}

// Tiny inline-SVG sparkline over the full quarter grid; nulls become gaps.
function sparkline(vals, opts) {
  opts = opts || {};
  const W=120, H=30, pad=2;
  const pts = vals.map((v,x)=>[x,v]).filter(p=>p[1]!==null && p[1]!==undefined);
  if (pts.length < 2) return `<span class="muted">—</span>`;
  const xs=pts.map(p=>p[0]), ys=pts.map(p=>p[1]);
  const x0=Math.min(...xs), x1=Math.max(...xs);
  let y0=Math.min(...ys), y1=Math.max(...ys);
  if (y0===y1){ y0-=1; y1+=1; }
  const sx=x=>pad+(x-x0)/(x1-x0)*(W-2*pad);
  const sy=y=>H-pad-(y-y0)/(y1-y0)*(H-2*pad);
  const d=pts.map((p,k)=>(k?"L":"M")+sx(p[0]).toFixed(1)+" "+sy(p[1]).toFixed(1)).join(" ");
  const last=pts[pts.length-1];
  const col = opts.color || "var(--series-1)";
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`+
    `<path d="${d}" fill="none" stroke="${col}" stroke-width="1.5"/>`+
    `<circle cx="${sx(last[0]).toFixed(1)}" cy="${sy(last[1]).toFixed(1)}" r="2.2" fill="${col}"/></svg>`;
}

function trendArrow(slope, goodUp) {
  if (slope===null || slope===undefined || Number.isNaN(slope) || Math.abs(slope)<1e-6) return "";
  const up = slope>0;
  const cls = (up===goodUp) ? "gd" : "lo";
  return `<span class="${cls}">${up?"↗":"↘"}</span>`;
}

function expand(i) {
  const r = window._show[i];
  const existing = document.querySelector(`tr.detail[data-for="${i}"]`);
  document.querySelectorAll("tr.detail").forEach(e=>e.remove());
  if (existing) return;
  const fired = new Set(sigList(r));
  const isBank = r.INST_TYPE==="Bank";
  const isCU = r.INST_TYPE==="Credit Union";
  const isFT = r.INST_TYPE==="Fintech";
  let cells, detailHdr;
  if (isFT) {
    detailHdr = "Regulatory footprint (FinCEN MSB)";
    const rows = [
      ["States of MSB activity", fmt(r.FT_STATES,"num",0)],
      ["Branches / agents", fmt(r.FT_BRANCHES,"num",0)],
      ["Also does business as", r.FT_DBA || "—"],
      ["MSB activities", r.FT_ACTIVITIES || "—"],
    ];
    cells = rows.map(x=>`<div class="metric"><span class="m">${x[0]}</span><span class="mv">${x[1]}</span></div>`).join("");
  } else {
    detailHdr = "Financials";
    const METRICS = isCU ? METRICS_CU : METRICS_BANK;
    cells = METRICS.map(m=>{
      let cls="mv";
      if (["EQV","NW_RATIO"].includes(m[0]) && fired.has("excess_capital")) cls="mv gd";
      if (["NCLNLSR","NPERFV","DELINQ","NCO"].includes(m[0]) && fired.has("credit_deterioration")) cls="mv hi";
      if (["EEFFR","EXP_RATIO"].includes(m[0]) && fired.has("weak_efficiency")) cls="mv hi";
      if (m[0]==="ROA" && fired.has("weak_profitability")) cls="mv lo";
      if (["LNLSDEPR","brokered_pct","LOAN_TO_SHARE"].includes(m[0]) && fired.has("funding_liquidity")) cls="mv hi";
      if (m[0]==="asset_growth_yoy" && (fired.has("rapid_growth")||fired.has("growth_accelerating"))) cls="mv gd";
      return `<div class="metric"><span class="m">${m[1]}</span><span class="${cls}">${fmt(r[m[0]],m[2],m[3])}</span></div>`;
    }).join("");
  }
  // KR RAS service mapping for each fired signal
  const svcRows = sigList(r).map(s=>{
    const refer = (SIGSERVICE[s]||"").startsWith("Refer");
    return `<div class="svcrow"><span class="sigtag">${SIGLAB[s]||s}</span>`+
           `<span class="svc ${refer?"refer":""}">${SIGSERVICE[s]||""}</span></div>`;
  }).join("");

  // 5-year trajectory block (banks and credit unions)
  let trendHtml = "";
  let specs = null, bits = [];
  if (isBank && SPARK.series[String(r.CERT)]) {
    const sp = SPARK.series[String(r.CERT)];
    specs = [
      ["Equity / assets", sp.eqv, r.EQV_slope, true, "%"],
      ["ROA", sp.roa, r.ROA_slope, true, "%"],
      ["Assets ($M)", sp.asset, r.asset_yoy, true, "n"],
      ["Noncurrent / assets", sp.npf, null, false, "%"],
    ];
    if (r.EQV_d2y!=null) bits.push(`capital ${r.EQV_d2y>=0?"+":""}${(+r.EQV_d2y).toFixed(1)} pts over 2yr`);
    if (r.asset_yoy!=null) bits.push(`assets ${(r.asset_yoy*100).toFixed(0)}% YoY`);
    if (fired.has("runway_to_10b") && r.runway_q!=null) bits.push(`~${Math.round(r.runway_q)} qtrs to $10B`);
  } else if (isCU && CU_SPARK.series[String(r.CERT)]) {
    const sp = CU_SPARK.series[String(r.CERT)];
    specs = [
      ["Net worth ratio", sp.nw, null, true, "%"],
      ["Assets ($M)", sp.assets, null, true, "n"],
      ["Delinquency / loans", sp.delinq, null, false, "%"],
    ];
  }
  if (specs) {
    const sparks = specs.map(s=>{
      const arr = s[1]||[];
      const last = [...arr].reverse().find(v=>v!==null && v!==undefined);
      const val = last===undefined?"—":(s[4]==="%"?last.toFixed(2)+"%":Number(last).toLocaleString());
      return `<div class="sparkbox"><div class="sparklab">${s[0]} ${trendArrow(s[2],s[3])}</div>`+
        `${sparkline(arr)}<div class="sparkval">${val}</div></div>`;
    }).join("");
    trendHtml = `<div class="trendhdr">5-year trajectory <span class="muted">${bits.join(" · ")}</span></div>`+
                `<div class="sparkgrid">${sparks}</div>`;
  }

  const tr = document.createElement("tr");
  tr.className="detail"; tr.dataset.for=i;
  const ld = linkedinSearch(r);
  const ldBlock =
    `<div class="trendhdr">Reach the decision-makers</div>`+
    `<a class="ldlink" href="${ld.url}" target="_blank" rel="noopener">Find decision-makers at ${r.NAME} on LinkedIn →</a>`+
    `<div class="muted" style="font-size:12px;margin-top:4px">Targets: ${ld.titles.join(" · ")}. Opens a LinkedIn people search — review and connect manually.</div>`;

  // Verified board & executives for public banks (SEC EDGAR; banks only)
  const eg = isBank ? EDGAR[String(r.CERT)] : null;
  let egBlock = "";
  if (eg) {
    const ppl = (eg.officers||[]).map(o=>
      `<div class="offrow"><span class="offname">${o.name}</span><span class="offtitle">${o.title||o.role}</span></div>`).join("");
    egBlock =
      `<div class="trendhdr">Board & executives — SEC filings `+
      `<span class="muted">${eg.ticker?("· "+eg.ticker+" "):""}· ${eg.sec_name}</span></div>`+
      `<div class="offlist">${ppl||'<span class="muted">No named insiders parsed</span>'}</div>`+
      `<a class="muted" style="font-size:12px" href="${eg.edgar}" target="_blank" rel="noopener">SEC filings & latest proxy (DEF 14A) →</a>`;
  }

  const idLabel = isFT ? "FinCEN MSB registrant" : isCU ? `NCUA charter ${r.CERT}` : `FDIC CERT ${r.CERT}`;
  tr.innerHTML = `<td colspan="8"><div style="padding:4px 2px 10px">`+
    `<div style="color:var(--text-secondary);margin-bottom:8px">${idLabel}</div>`+
    `<div class="trendhdr">KR RAS services to pitch</div><div class="svcmap">${svcRows}</div>`+
    ldBlock+egBlock+
    `<div class="trendhdr">${detailHdr}</div><div class="detail-grid">${cells}</div>${trendHtml}</div></td>`;
  const rowEl = document.querySelector(`tr[data-i="${i}"]`);
  rowEl.after(tr);
}

function toggle(s){ selected.has(s)?selected.delete(s):selected.add(s); render(); }
function sortBy(k){ if(sortKey===k) sortDir*=-1; else {sortKey=k; sortDir=(k==="NAME"||k==="CITY"||k==="STALP"||k==="asset_band")?1:-1;} render(); }
function resetAll(){ selected.clear(); document.getElementById("q").value="";
  ["state","band","svcline","itype"].forEach(id=>document.getElementById(id).value="");
  document.getElementById("minsig").value="1"; document.getElementById("mode").value="any"; render(); }

function toggleOverview(){
  const o=document.getElementById("overview"), t=document.getElementById("ovtoggle");
  const show = o.style.display==="none";
  o.style.display = show?"block":"none"; t.textContent = show?"hide ▴":"show ▾";
  if (show && !o.dataset.done){ renderOverview(); o.dataset.done="1"; }
}
function renderOverview(){
  const D=DATA, types=["Bank","Credit Union","Fintech"];
  // type x priority
  const rowsT = types.map(ty=>{
    const rs=D.filter(r=>r.INST_TYPE===ty);
    const hot=rs.filter(r=>priorityOf(r)==="Hot").length;
    const warm=rs.filter(r=>priorityOf(r)==="Warm").length;
    return `<tr><td>${ty}</td><td class="num">${rs.length.toLocaleString()}</td>`+
      `<td class="num gd">${hot.toLocaleString()}</td><td class="num">${warm.toLocaleString()}</td></tr>`;
  }).join("");
  const typeTbl = `<table style="width:auto"><thead><tr><th>Type</th><th class="num">Total</th><th class="num">Hot</th><th class="num">Warm</th></tr></thead><tbody>${rowsT}</tbody></table>`;
  // top states (banks + credit unions only — fintech "state" is registration
  // domicile, not a sales territory)
  const sc={}; D.forEach(r=>{ if(r.STALP && r.INST_TYPE!=="Fintech") sc[r.STALP]=(sc[r.STALP]||0)+1; });
  const top=Object.entries(sc).sort((a,b)=>b[1]-a[1]).slice(0,12);
  const mx=Math.max(...top.map(x=>x[1]),1);
  const stateBars=top.map(([s,c])=>`<div class="barrow"><div class="lab">${s}</div>`+
    `<div class="bartrack"><div class="barfill" style="width:${(c/mx*100).toFixed(0)}%"></div></div><div class="cnt">${c}</div></div>`).join("");
  // service-line group demand
  const grp=CHIP_GROUPS.map(g=>[g[0], D.filter(r=>g[1].some(k=>sigList(r).includes(k))).length]).sort((a,b)=>b[1]-a[1]);
  const gmx=Math.max(...grp.map(x=>x[1]),1);
  const grpBars=grp.map(([n,c])=>`<div class="barrow"><div class="lab">${n}</div>`+
    `<div class="bartrack"><div class="barfill" style="width:${(c/gmx*100).toFixed(0)}%"></div></div><div class="cnt">${c}</div></div>`).join("");
  document.getElementById("overview").innerHTML =
    `<div class="ovgrid">`+
    `<div><div class="ovh">By type &amp; priority</div>${typeTbl}</div>`+
    `<div><div class="ovh">Targets by state — banks &amp; CUs (top 12)</div>${stateBars}</div>`+
    `<div><div class="ovh">Demand by KR RAS service line</div>${grpBars}</div></div>`;
}

function priorityOf(r){
  if (r.INST_TYPE==="Fintech") return r.FT_KNOWN ? "Hot" : "Cool";
  return r.n_signals>=3 ? "Hot" : r.n_signals===2 ? "Warm" : "Cool";
}
function keyMetricsOf(r){
  const p=[];
  if (r.INST_TYPE==="Fintech"){
    if (r.FT_STATES!=null) p.push(`${r.FT_STATES} states of MSB activity`);
    if (r.FT_ACTIVITIES) p.push(r.FT_ACTIVITIES);
    return p.join("; ");
  }
  if (r.INST_TYPE==="Credit Union"){
    if (r.NW_RATIO!=null) p.push(`net worth ${(+r.NW_RATIO).toFixed(1)}%`);
    if (r.ROA!=null) p.push(`ROA ${(+r.ROA).toFixed(2)}%`);
    if (r.DELINQ!=null) p.push(`delinquency ${(+r.DELINQ).toFixed(2)}%`);
  } else {
    if (r.EQV!=null) p.push(`equity/assets ${(+r.EQV).toFixed(1)}%`);
    if (r.ROA!=null) p.push(`ROA ${(+r.ROA).toFixed(2)}%`);
    if (r.EEFFR!=null) p.push(`efficiency ${(+r.EEFFR).toFixed(0)}%`);
  }
  if (r.asset_musd!=null) p.push(`assets $${(+r.asset_musd/1000).toFixed(1)}B`);
  return p.join("; ");
}
function csvCell(v){ v=(v==null?"":String(v)); return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v; }
function downloadCSV(){
  const rows = DATA.filter(passes);
  const cols = ["Institution Name","Institution Type","Priority","Priority Score",
    "State","City","Assets ($B)","KR RAS Services","Signals","Key Metrics",
    "LinkedIn Decision-Maker Search"];
  const lines = [cols.join(",")];
  rows.forEach(r=>{
    const sg = sigList(r);
    const services = [...new Set(sg.map(s=>SIGSERVICE[s]).filter(Boolean))].join("; ");
    const labels = sg.map(s=>SIGLAB[s]||s).join("; ");
    const assets = r.asset_musd!=null ? (+r.asset_musd/1000).toFixed(2) : "";
    const rec = [r.NAME, r.INST_TYPE, priorityOf(r), r.score, r.STALP, r.CITY,
      assets, services, labels, keyMetricsOf(r), linkedinSearch(r).url];
    lines.push(rec.map(csvCell).join(","));
  });
  const blob = new Blob([lines.join("\n")], {type:"text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "bd_targets_filtered.csv";
  a.click(); URL.revokeObjectURL(a.href);
}

function init(){
  document.getElementById("sub").textContent =
    `${META.flagged.toLocaleString()} flagged — ${META.nBank.toLocaleString()} banks (FDIC) + ${META.nCU.toLocaleString()} credit unions (NCUA) + ${META.nFT.toLocaleString()} fintechs (FinCEN MSB), ${META.quarter}` +
    (META.hasTrend ? ". Click any institution for detail; banks include 5-year trajectory." : ".");
  const states = [...new Set(DATA.map(r=>r.STALP).filter(Boolean))].sort();
  document.getElementById("state").innerHTML =
    '<option value="">All states</option>' + states.map(s=>`<option>${s}</option>`).join("");
  document.getElementById("svcline").innerHTML =
    '<option value="">All service lines</option>' + CHIP_GROUPS.map(g=>`<option>${g[0]}</option>`).join("");

  // Shared hover tooltip: shows the data-tip of whatever the cursor is over.
  const tip = document.getElementById("tip");
  document.addEventListener("mousemove", e=>{
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (el && el.getAttribute("data-tip")) {
      tip.textContent = el.getAttribute("data-tip");
      tip.style.opacity = "1";
      const pad = 14, r = tip.getBoundingClientRect();
      let x = e.clientX + pad, y = e.clientY + pad;
      if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
      if (y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
      tip.style.left = x + "px"; tip.style.top = y + "px";
    } else { tip.style.opacity = "0"; }
  });
  render();
}
init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
