"""
10_cu_trajectory.py  --  5-year trajectory for credit unions (parity with banks).

Downloads ~20 quarters of NCUA Call Reports, builds per-CU time series for net
worth ratio, assets, and delinquency, computes trend flags, and writes:
  output/cu_spark.json      per-CU sparkline series (for the dashboard drill-down)
  output/cu_targets.csv     REWRITTEN with capital_building / credit_turning /
                            growth_accelerating flags merged into signals + score

Reuses the same trajectory signal keys as banks so the dashboard needs no new
signals. Only credit unions already in cu_targets.csv are tracked.
"""

import io
import json
import zipfile
import numpy as np
import pandas as pd
import requests

BASE = "https://ncua.gov/files/publications/analysis/call-report-data-{}.zip"
N_QUARTERS = 20
QM = ["03", "06", "09", "12"]

# same-named trajectory signals as banks -> (weight, service) already in dashboard
TSERVICE = {
    "growth_accelerating": (16, "KR RAS: BSA/AML scaling, Internal Audit, risk assessment"),
    "credit_turning":      (16, "KR RAS: early Internal Audit loan review + CECL validation"),
    "capital_building":    (5,  "Refer: capital deployment / strategy (other KR practice)"),
}


def quarters(latest_tag, n):
    y, m = int(latest_tag[:4]), int(latest_tag[5:7])
    q = (m - 1) // 3
    out = []
    for _ in range(n):
        out.append(f"{y}-{QM[q]}")
        q -= 1
        if q < 0:
            q, y = 3, y - 1
    return out


def read_quarter(tag):
    try:
        r = requests.get(BASE.format(tag), timeout=120)
        if r.status_code != 200:
            return None
    except Exception:
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        def load(name):
            with z.open(name) as f:
                d = pd.read_csv(f, dtype=str, low_memory=False)
                d.columns = d.columns.str.upper()
                return d
        fs, fsa = load("FS220.txt"), load("FS220A.txt")
    d = fs[["CU_NUMBER", "ACCT_010", "ACCT_025B", "ACCT_041B"]].merge(
        fsa[["CU_NUMBER", "ACCT_997"]], on="CU_NUMBER", how="left")
    for c in ["ACCT_010", "ACCT_025B", "ACCT_041B", "ACCT_997"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["nw"] = d["ACCT_997"] / d["ACCT_010"] * 100
    d["assets_m"] = d["ACCT_010"] / 1e6
    d["delinq"] = np.where(d["ACCT_025B"] > 0, d["ACCT_041B"] / d["ACCT_025B"] * 100, np.nan)
    return d[["CU_NUMBER", "nw", "assets_m", "delinq"]].set_index("CU_NUMBER")


def slope_per_year(y):
    y = pd.Series(y, dtype="float64").reset_index(drop=True)
    ok = y.notna()
    if ok.sum() < 6:
        return np.nan
    t = np.arange(len(y))[ok] / 4.0
    return float(np.polyfit(t, y[ok].values, 1)[0])


def main():
    tags = quarters("2026-03", N_QUARTERS)          # newest first
    print(f"Pulling {len(tags)} NCUA quarters: {tags[-1]} .. {tags[0]}")
    frames = {}
    for t in tags:
        d = read_quarter(t)
        if d is not None:
            frames[t] = d
            print(f"  {t}: {len(d):,}")
    order = [t for t in reversed(tags) if t in frames]   # oldest -> newest

    targets = pd.read_csv("output/cu_targets.csv")
    certs = targets["CU_NUMBER"].astype(str).tolist() if "CU_NUMBER" in targets.columns \
        else targets["CERT"].astype(str).tolist()

    spark, feats = {}, []
    for cu in certs:
        nw = [frames[t]["nw"].get(cu, np.nan) if cu in frames[t].index else np.nan for t in order]
        aset = [frames[t]["assets_m"].get(cu, np.nan) if cu in frames[t].index else np.nan for t in order]
        dq = [frames[t]["delinq"].get(cu, np.nan) if cu in frames[t].index else np.nan for t in order]
        spark[str(cu)] = {
            "nw": [None if pd.isna(v) else round(v, 2) for v in nw],
            "assets": [None if pd.isna(v) else round(v, 1) for v in aset],
            "delinq": [None if pd.isna(v) else round(v, 2) for v in dq],
        }
        nw_slope = slope_per_year(nw)
        dq_slope = slope_per_year(dq)
        # asset growth acceleration (last yr vs prior yr)
        av = pd.Series(aset, dtype="float64")
        recent = (av.iloc[-1] / av.iloc[-5] - 1) if len(av) >= 5 and av.iloc[-5] > 0 else np.nan
        prior = (av.iloc[-5] / av.iloc[-9] - 1) if len(av) >= 9 and av.iloc[-9] > 0 else np.nan
        feats.append({
            "CU": cu, "nw_slope": nw_slope, "dq_slope": dq_slope,
            "capital_building": (nw_slope is not np.nan) and (nw_slope >= 0.30),
            "credit_turning": (dq_slope is not np.nan) and (dq_slope >= 0.10),
            "growth_accelerating": (recent == recent and prior == prior
                                    and recent >= 0.08 and (recent - prior) >= 0.03),
        })

    with open("output/cu_spark.json", "w") as f:
        json.dump({"quarters": order, "series": spark}, f)

    tf = pd.DataFrame(feats).set_index("CU")
    id_col = "CU_NUMBER" if "CU_NUMBER" in targets.columns else "CERT"
    targets["_id"] = targets[id_col].astype(str)

    def enrich(r):
        add = [k for k in TSERVICE if bool(tf.loc[r["_id"], k]) if r["_id"] in tf.index]
        sigs = [s for s in str(r["signals"]).split("; ") if s] if pd.notnull(r["signals"]) else []
        sigs = sigs + [k for k in add if k not in sigs]
        return pd.Series({"signals": "; ".join(sigs), "n_signals": len(sigs),
                          "score": int(r["score"]) + sum(TSERVICE[k][0] for k in add)})

    m = targets.apply(enrich, axis=1)
    targets["signals"], targets["n_signals"], targets["score"] = m["signals"], m["n_signals"], m["score"]
    targets.drop(columns="_id").to_csv("output/cu_targets.csv", index=False)

    print(f"Wrote output/cu_spark.json + enriched cu_targets.csv")
    for k in TSERVICE:
        print(f"  {k:<22} {int(tf[k].sum()):>4}")


if __name__ == "__main__":
    main()
