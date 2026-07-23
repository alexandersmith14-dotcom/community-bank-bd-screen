"""
08_cu_screen.py  --  Screen the credit-union universe into RAS BD targets.

Mirrors 02_screen.py but for credit-union ratios and NCUA-specific rules:
  * capital  = net worth ratio (not equity/assets)
  * credit   = delinquency + net charge-offs (no ALLL coverage in NCUA basics)
  * FDICIA   -> the NCUA analog: the $500M CPA financial-statement audit trigger
  * no SEC/EDGAR (credit unions are member-owned, not publicly traded)

Writes output/cu_targets.csv with the same shared columns as the bank targets
(plus INST_TYPE="Credit Union") so the dashboard can show both in one list.
"""

import numpy as np
import pandas as pd

PCTL_HIGH, PCTL_XHIGH, PCTL_LOW = 0.80, 0.85, 0.15
LTS_ABS = 100.0            # loan-to-share stretched
# Credit unions grow far slower than banks (p90 ~11% YoY), so these sit below the
# bank thresholds (15%/20%) to stay comparably selective.
GROWTH_FAST, GROWTH_BSA = 0.10, 0.13
NEAR_10B_LOW, NEAR_10B_HIGH = 8_000_000, 10_000_000        # thousands
# With the $500M universe floor, this flags CUs that JUST crossed $500M and are
# newly subject to the NCUA Part 715 CPA financial-statement audit.
AUDIT_LOW, AUDIT_HIGH = 500_000, 650_000                    # thousands

BAND_EDGES = [0, 250_000, 1_000_000, 3_000_000, 10 ** 12]
BAND_LABELS = ["<$250M", "$250M-$1B", "$1B-$3B", "$3B+"]

SERVICE = {
    "near_10b_threshold":   (22, "KR RAS: $10B readiness — CFPB supervision + NCUA stress testing, Internal Audit"),
    "bsa_aml_scaling":      (20, "KR RAS: BSA/AML program enhancement + independent testing (AML & Sanctions / OFAC)"),
    "near_500m_audit":      (18, "KR RAS: NCUA Part 715 CPA financial-statement audit / supervisory committee support"),
    "rapid_growth":         (18, "KR RAS: BSA/AML scaling, Internal Audit, enterprise risk assessment"),
    "credit_deterioration": (18, "KR RAS: Internal Audit loan review + CECL model validation"),
    "weak_efficiency":      (15, "KR RAS: Robotic Process Automation (RPA) + Internal Audit process review"),
    "funding_liquidity":    (10, "KR RAS (partial): Internal Audit of liquidity/funding risk controls"),
    "excess_capital":       (5,  "Refer: capital deployment / strategy (other KR practice)"),
    "weak_profitability":   (5,  "Refer: earnings / margin advisory (other KR practice)"),
}


def main():
    df = pd.read_csv("data/cu_current.csv")
    pri = pd.read_csv("data/cu_prior.csv")
    df = df.merge(pri, on="CU_NUMBER", how="left")

    for c in ["ASSET", "NW_RATIO", "DELINQ", "NCO", "LOAN_TO_SHARE", "ROA",
              "EXP_RATIO", "ASSET_PRIOR"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["asset_band"] = pd.cut(df["ASSET"], bins=BAND_EDGES, labels=BAND_LABELS, right=False)
    df["asset_musd"] = (df["ASSET"] / 1000).round(1)
    df["asset_growth_yoy"] = np.where(df["ASSET_PRIOR"] > 0,
                                      (df["ASSET"] - df["ASSET_PRIOR"]) / df["ASSET_PRIOR"], np.nan)

    for c in ["NW_RATIO", "DELINQ", "NCO", "LOAN_TO_SHARE", "ROA", "EXP_RATIO"]:
        df[c + "_pct"] = df.groupby("asset_band", observed=True)[c].rank(pct=True)

    p_hi, p_xhi, p_lo = PCTL_HIGH, PCTL_XHIGH, PCTL_LOW
    sig = {
        "excess_capital":       df["NW_RATIO_pct"] >= p_hi,
        "credit_deterioration": (df["DELINQ_pct"] >= p_xhi) | (df["NCO_pct"] >= p_xhi),
        "weak_efficiency":      df["EXP_RATIO_pct"] >= p_hi,
        "funding_liquidity":    (df["LOAN_TO_SHARE"] >= LTS_ABS) | (df["LOAN_TO_SHARE_pct"] >= p_xhi),
        "rapid_growth":         df["asset_growth_yoy"] >= GROWTH_FAST,
        "weak_profitability":   (df["ROA_pct"] <= p_lo) | (df["ROA"] < 0),
        "bsa_aml_scaling":      df["asset_growth_yoy"] >= GROWTH_BSA,
        "near_10b_threshold":   (df["ASSET"] >= NEAR_10B_LOW) & (df["ASSET"] < NEAR_10B_HIGH),
        "near_500m_audit":      (df["ASSET"] >= AUDIT_LOW) & (df["ASSET"] < AUDIT_HIGH),
    }
    for k, v in sig.items():
        df[k] = v.fillna(False).astype(bool)
    signal_cols = list(sig.keys())

    df["_m"] = df.apply(lambda r: [s for s in signal_cols if r[s]], axis=1)
    df["signals"] = df["_m"].apply("; ".join)
    df["service_lines"] = df["_m"].apply(lambda xs: "; ".join(dict.fromkeys(SERVICE[s][1] for s in xs)))
    df["n_signals"] = df["_m"].apply(len)
    df["score"] = df["_m"].apply(lambda xs: sum(SERVICE[s][0] for s in xs))
    df["INST_TYPE"] = "Credit Union"
    df["CERT"] = df["CU_NUMBER"]

    out_cols = [
        "INST_TYPE", "CERT", "NAME", "CITY", "STALP", "asset_band", "asset_musd",
        "n_signals", "score", "signals",
        "NW_RATIO", "NW_RATIO_pct", "DELINQ", "NCO", "LOAN_TO_SHARE", "ROA",
        "ROA_pct", "EXP_RATIO", "MEMBERS", "asset_growth_yoy",
    ]
    ranked = df[df["n_signals"] > 0].sort_values(["score", "n_signals", "asset_musd"], ascending=False)
    ranked[out_cols].round(3).to_csv("output/cu_targets.csv", index=False)

    print(f"Credit unions screened:  {len(df):,}")
    print(f"CU targets (>=1 signal): {len(ranked):,}")
    print(f"CU targets with 3+:      {int((df['n_signals'] >= 3).sum()):,}")
    for s in signal_cols:
        print(f"  {s:<22} {int(df[s].sum()):>5,}")


if __name__ == "__main__":
    main()
