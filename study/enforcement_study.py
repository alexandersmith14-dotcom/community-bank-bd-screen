"""
enforcement_study.py  --  The "pre-enforcement financial signature".

Pulls OCC + Federal Reserve enforcement orders (OpenSanctions mirrors), matches
each bank to its FDIC CERT, then looks at that bank's financials in the 8 quarters
BEFORE the order and compares them to the whole population (percentile within its
size band). Aggregating across all enforced banks reveals what consistently
deteriorated ahead of an order.

Population history comes from ../data/history.csv (the 20-quarter pull the tool
already builds). So run this from the project's 04_history step onward.

Outputs (into ./study):
  matched_orders.csv     enforced banks matched to a CERT + order date
  signature.csv          mean "distress percentile" by metric x quarters-before
  FINDINGS.md            the write-up
"""

import io
import json
import re
import requests
import numpy as np
import pandas as pd

OCC = "https://data.opensanctions.org/datasets/latest/us_occ_enfact/source.json"
FED = "https://data.opensanctions.org/datasets/latest/us_fed_enforcements/source.csv"
FDIC = "https://api.fdic.gov/banks/institutions"

STATES = {"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA",
"Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA","Hawaii":"HI",
"Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY",
"Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI",
"Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV",
"New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC",
"North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA",
"Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX",
"Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV",
"Wisconsin":"WI","Wyoming":"WY","District of Columbia":"DC"}

SUFFIX = set("""bank banks national association na company co corp corporation inc
incorporated bancorp bancshares financial group holdings holding savings ssb fsb nb
trust the of and & fkb""".split())

# metric -> whether HIGH value = more distressed
METRICS = {"NPERFV": True, "NCLNLSR": True, "EEFFR": True, "brokered": True,
           "growth": True, "EQV": False, "ROA": False}
NICE = {"NPERFV": "Noncurrent assets/assets", "NCLNLSR": "Net charge-offs/loans",
        "EEFFR": "Efficiency ratio", "brokered": "Brokered deposits/deposits",
        "growth": "Asset growth (YoY)", "EQV": "Equity/assets (capital)", "ROA": "ROA"}


def core(name):
    toks = re.sub(r"[^a-z0-9 ]", " ", str(name).lower()).split()
    return frozenset(t for t in toks if t not in SUFFIX)


def load_orders():
    rows = []
    occ = json.load(io.StringIO(requests.get(OCC, timeout=90).text))
    for r in occ:
        inst = (r.get("Institution") or "").strip()
        if not inst or not r.get("StartDate"):
            continue
        if r.get("TypeCode") not in ("C&D", "FA", "CO", "PCA", "PCAD"):
            continue
        st = ""
        loc = (r.get("Location") or "").split(",")
        if len(loc) >= 2 and len(loc[-1].strip()) == 2:
            st = loc[-1].strip().upper()
        try:
            d = pd.to_datetime(r["StartDate"], format="%m/%d/%Y")
        except Exception:
            continue
        rows.append({"name": inst, "state": st, "date": d,
                     "action": r.get("TypeDescription", "")[:40], "reg": "OCC"})
    fed = pd.read_csv(io.StringIO(requests.get(FED, timeout=90).text), dtype=str)
    for _, r in fed.iterrows():
        org = str(r.get("Banking Organization") or "").strip()
        if not org or str(r.get("Individual") or "").strip():
            continue
        act = str(r.get("Action") or "")
        if not any(k in act for k in ("Written Agreement", "Consent", "Cease", "Prompt Corrective")):
            continue
        st = ""
        for full, ab in STATES.items():
            if full in org:
                st = ab
                break
        nm = org.split(",")[0].strip()
        try:
            d = pd.to_datetime(r["Effective Date"])
        except Exception:
            continue
        rows.append({"name": nm, "state": st, "date": d, "action": act[:40], "reg": "Fed"})
    df = pd.DataFrame(rows)
    return df[df["date"] >= "2022-01-01"].copy()


def fetch_institutions():
    rows, offset = [], 0
    while True:
        r = requests.get(FDIC, params={"filters": "ACTIVE:1", "fields": "CERT,NAME,STALP",
                         "limit": 10000, "offset": offset, "format": "json"}, timeout=60)
        b = r.json().get("data", [])
        if not b:
            break
        rows += [x["data"] for x in b]
        offset += 10000
        if len(b) < 10000:
            break
    return pd.DataFrame(rows)


def main():
    print("Loading enforcement orders ...")
    orders = load_orders()
    print(f"  bank orders since 2022: {len(orders):,}")

    inst = fetch_institutions()
    inst["core"] = inst["NAME"].apply(core)
    idx = {}
    for _, r in inst.iterrows():
        idx.setdefault((r["STALP"], r["core"]), r["CERT"])

    def match(row):
        c = core(row["name"])
        if not c:
            return np.nan
        hit = idx.get((row["state"], c))
        if hit is not None:
            return hit
        # relax: same state, core subset match
        for (st, ic), cert in idx.items():
            if st == row["state"] and c and (c <= ic or ic <= c) and len(c & ic):
                return cert
        return np.nan

    orders["CERT"] = orders.apply(match, axis=1)
    matched = orders.dropna(subset=["CERT"]).copy()
    matched["CERT"] = matched["CERT"].astype(int)
    print(f"  matched to a CERT: {len(matched):,} of {len(orders):,}")

    # ---- population history + percentiles ----
    h = pd.read_csv("../data/history.csv")
    for c in ["ASSET", "EQV", "NCLNLSR", "NPERFV", "EEFFR", "ROA", "BRO", "DEP"]:
        h[c] = pd.to_numeric(h.get(c), errors="coerce")
    h["REPDTE"] = h["REPDTE"].astype(str)
    h["brokered"] = np.where(h["DEP"] > 0, h["BRO"] / h["DEP"] * 100, np.nan)
    h = h.sort_values(["CERT", "REPDTE"])
    h["growth"] = h.groupby("CERT")["ASSET"].pct_change(4) * 100
    edges = [0, 250_000, 1_000_000, 3_000_000, 10 ** 12]
    h["band"] = pd.cut(h["ASSET"], edges, labels=False, right=False)
    for m in METRICS:
        h[m + "_p"] = h.groupby(["REPDTE", "band"], observed=True)[m].rank(pct=True)
    hp = h.set_index(["CERT", "REPDTE"])

    quarters = sorted(h["REPDTE"].unique())

    def qtr_end(d):
        y, m = d.year, d.month
        q = (m - 1) // 3
        mm, dd = [("03", "31"), ("06", "30"), ("09", "30"), ("12", "31")][q]
        return f"{y}{mm}{dd}"

    def shift_q(rep, back):
        i = quarters.index(rep) if rep in quarters else None
        return quarters[i - back] if i is not None and i - back >= 0 else None

    # ---- collect pre-order distress percentiles by horizon ----
    HOR = range(1, 9)
    acc = {m: {h_: [] for h_ in HOR} for m in METRICS}
    for _, o in matched.iterrows():
        oq = qtr_end(o["date"])
        # order quarter = last completed quarter strictly before the order
        base = shift_q(oq, 1) if oq in quarters else (max([q for q in quarters if q < oq], default=None))
        if base is None:
            continue
        for hz in HOR:
            rep = shift_q(base, hz - 1)
            if rep is None or (o["CERT"], rep) not in hp.index:
                continue
            row = hp.loc[(o["CERT"], rep)]
            for m, high_bad in METRICS.items():
                p = row.get(m + "_p")
                if pd.notnull(p):
                    acc[m][hz].append(p if high_bad else 1 - p)   # distress pct

    sig = []
    for m in METRICS:
        rec = {"metric": NICE[m]}
        for hz in HOR:
            vals = acc[m][hz]
            rec[f"t-{hz}"] = round(np.mean(vals) * 100, 1) if vals else None
        rec["n_at_t-1"] = len(acc[m][1])
        sig.append(rec)
    sigdf = pd.DataFrame(sig)
    matched.to_csv("matched_orders.csv", index=False)
    sigdf.to_csv("signature.csv", index=False)

    print("\n=== Pre-enforcement distress percentile (100 = worst vs size peers) ===")
    print(sigdf.to_string(index=False))
    return matched, sigdf


if __name__ == "__main__":
    main()
