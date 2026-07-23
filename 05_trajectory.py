"""
05_trajectory.py  --  Turn 20 quarters of history into direction-of-travel.

Reads data/history.csv (from 04_history.py) and output/all_banks.csv (from
02_screen.py). Produces:
  output/trajectory.csv   per-bank trend features + trajectory flags
  output/spark.json       compact per-quarter series for dashboard sparklines
  output/targets.csv      REWRITTEN: snapshot signals + trajectory flags merged,
                          score/rank recomputed  (banks with >=1 signal of any kind)

Why trajectory matters: a snapshot says a bank *is* well-capitalized; a trend says
it is *becoming* so (capital building for 8 straight quarters) — a much warmer BD
reason to call. And a rising charge-off trend flags credit turning before the
level itself looks alarming.
"""

import json
import numpy as np
import pandas as pd

# ---- Tunable trajectory thresholds -----------------------------------------
CAP_SLOPE = 0.40       # equity/assets rising >= 0.40 pts per year (~top quartile)
CAP_DELTA2Y = 0.75     #   and up >= 0.75 pts over two years
CREDIT_SLOPE = 0.15    # charge-offs / noncurrent rising (pts/yr, ~top decile)
GROWTH_RECENT = 0.10   # last-year asset growth >= 10%
GROWTH_ACCEL = 0.03    #   and >= 3 pts faster than the year before
RUNWAY_MIN_ASSET = 5_000_000   # $5B (thousands): only banks close enough to matter
RUNWAY_QUARTERS = 12   # flag if projected to cross $10B within 3 years
ROA_SLOPE = -0.10      # ROA clearly falling
EFF_SLOPE = 2.5        #   and efficiency ratio clearly rising (worsening)
MIN_POINTS = 6         # need >= 6 quarters to trust a slope

TEN_B = 10_000_000     # $10B in thousands

SERIES = ["ASSET", "EQV", "RBC1AAJ", "NCLNLSR", "NPERFV", "EEFFR", "ROA", "LNLSDEPR"]

# trajectory signal -> (score weight, KR RAS service line). Same calibration as
# the snapshot map in 02_screen.py: RAS-sellable signals weighted up; non-RAS
# tagged "Refer".
TSERVICE = {
    "runway_to_10b":        (20, "KR RAS: $10B runway — Consumer Compliance (CFPB), BSA/AML, Internal Audit readiness"),
    "growth_accelerating":  (16, "KR RAS: BSA/AML scaling, Internal Audit, risk assessment as growth outpaces controls"),
    "credit_turning":       (16, "KR RAS: early Internal Audit loan review / credit-risk controls before losses surface"),
    "margin_eroding":       (10, "KR RAS (partial): RPA cost automation; broader margin advisory is another practice"),
    "capital_building":     (5,  "Refer: capital deployment / M&A (other KR practice)"),
}


def slope_per_year(y):
    """OLS slope in units per YEAR over available (non-NaN) quarters."""
    y = pd.Series(y, dtype="float64").reset_index(drop=True)
    ok = y.notna()
    if ok.sum() < MIN_POINTS:
        return np.nan
    t = np.arange(len(y))[ok] / 4.0          # quarters -> years
    return float(np.polyfit(t, y[ok].values, 1)[0])


def delta_2yr(y):
    """Latest value minus the value ~8 quarters earlier."""
    y = pd.Series(y, dtype="float64").reset_index(drop=True)
    if y.notna().sum() < 2 or pd.isna(y.iloc[-1]):
        return np.nan
    past = y.iloc[-9] if len(y) >= 9 else y.dropna().iloc[0]
    return np.nan if pd.isna(past) else float(y.iloc[-1] - past)


def yoy(y, back):
    """Growth from `back` quarters ago to the value 4 quarters after that."""
    y = pd.Series(y, dtype="float64").reset_index(drop=True)
    if len(y) < back + 1:
        return np.nan
    now = y.iloc[-1 - (back - 4)] if back > 4 else y.iloc[-1]
    prev = y.iloc[-1 - back]
    if pd.isna(now) or pd.isna(prev) or prev <= 0:
        return np.nan
    return float((now - prev) / prev)


def main():
    hist = pd.read_csv("data/history.csv")
    for c in SERIES:
        hist[c] = pd.to_numeric(hist.get(c), errors="coerce")
    hist = hist.sort_values(["CERT", "REPDTE"])
    quarters = sorted(hist["REPDTE"].unique())          # ascending

    feats, spark = [], {}
    for cert, g in hist.groupby("CERT"):
        g = g.set_index("REPDTE").reindex(quarters)      # align to full grid
        asset = g["ASSET"]
        rec = {"CERT": int(cert)}

        for c in SERIES:
            rec[c + "_slope"] = slope_per_year(g[c].values)
        rec["EQV_d2y"] = delta_2yr(g["EQV"].values)
        rec["ROA_d2y"] = delta_2yr(g["ROA"].values)

        recent = yoy(asset.values, 4)                    # last year
        prior = yoy(asset.values, 8)                     # the year before
        rec["asset_yoy"] = recent
        rec["asset_accel"] = (recent - prior) if (recent == recent and prior == prior) else np.nan

        # projected quarters to $10B at the recent annual pace
        cur = asset.dropna().iloc[-1] if asset.notna().any() else np.nan
        if cur == cur and recent == recent and recent > 0 and cur < TEN_B:
            qtr_rate = (1 + recent) ** 0.25 - 1
            rec["runway_q"] = float(np.log(TEN_B / cur) / np.log(1 + qtr_rate)) if qtr_rate > 0 else np.nan
        else:
            rec["runway_q"] = np.nan
        rec["cur_asset"] = float(cur) if cur == cur else np.nan
        rec["n_quarters"] = int(g["ASSET"].notna().sum())
        feats.append(rec)

        # sparkline series (rounded, nulls preserved), only a few metrics
        spark[str(int(cert))] = {
            "asset": [None if pd.isna(v) else round(v / 1000, 1) for v in g["ASSET"]],   # $M
            "eqv":   [None if pd.isna(v) else round(v, 2) for v in g["EQV"]],
            "roa":   [None if pd.isna(v) else round(v, 2) for v in g["ROA"]],
            "npf":   [None if pd.isna(v) else round(v, 2) for v in g["NPERFV"]],
        }

    tf = pd.DataFrame(feats)

    # ---- trajectory flags ---------------------------------------------------
    tf["capital_building"] = (tf["EQV_slope"] >= CAP_SLOPE) & (tf["EQV_d2y"] >= CAP_DELTA2Y)
    tf["credit_turning"] = (
        ((tf["NCLNLSR_slope"] >= CREDIT_SLOPE) | (tf["NPERFV_slope"] >= CREDIT_SLOPE))
    )
    tf["growth_accelerating"] = (tf["asset_yoy"] >= GROWTH_RECENT) & (tf["asset_accel"] >= GROWTH_ACCEL)
    tf["runway_to_10b"] = (tf["cur_asset"] >= RUNWAY_MIN_ASSET) & (tf["runway_q"] <= RUNWAY_QUARTERS)
    tf["margin_eroding"] = (tf["ROA_slope"] <= ROA_SLOPE) & (tf["EEFFR_slope"] >= EFF_SLOPE)
    for k in TSERVICE:
        tf[k] = tf[k].fillna(False).astype(bool)

    tf.round(3).to_csv("output/trajectory.csv", index=False)
    with open("output/spark.json", "w") as f:
        json.dump({"quarters": [str(q) for q in quarters], "series": spark}, f)

    # ---- merge into the target list -----------------------------------------
    allb = pd.read_csv("output/all_banks.csv")
    allb["signals"] = allb["signals"].fillna("")
    m = allb.merge(tf, on="CERT", how="left", suffixes=("", "_tf"))

    tcols = list(TSERVICE.keys())
    for k in tcols:
        m[k] = m[k].fillna(False).astype(bool)

    def merge_row(r):
        extra = [k for k in tcols if r[k]]
        sigs = [s for s in (r["signals"].split("; ") if r["signals"] else [])]
        sigs = sigs + extra
        score = int(r["score"]) + sum(TSERVICE[k][0] for k in extra)
        return pd.Series({
            "signals": "; ".join(sigs),
            "n_signals": len(sigs),
            "score": score,
        })

    merged = m.apply(merge_row, axis=1)
    m["signals"], m["n_signals"], m["score"] = merged["signals"], merged["n_signals"], merged["score"]

    keep = [c for c in allb.columns] + tcols + [
        "EQV_slope", "EQV_d2y", "ROA_slope", "NCLNLSR_slope", "NPERFV_slope",
        "asset_yoy", "asset_accel", "runway_q", "n_quarters",
    ]
    out = m[m["n_signals"] > 0][keep].sort_values(
        ["score", "n_signals", "asset_musd"], ascending=False
    )
    out.round(3).to_csv("output/targets.csv", index=False)

    print(f"History banks:            {len(tf):,}")
    print(f"Targets (any signal):     {len(out):,}")
    print("\nTrajectory flags:")
    for k in tcols:
        print(f"  {k:<22} {int(tf[k].sum()):>5,}")


if __name__ == "__main__":
    main()
