"""
02_screen.py  --  Turn the raw FDIC pull into a ranked BD target list.

Reads ./data/*.csv (from 01_fetch.py) and writes ./output/:
  targets.csv          one row per bank, matched signals + service lines + score
  signal_summary.csv   how many banks tripped each signal

The signal definitions and thresholds are documented in METHODOLOGY.md, which
lives in the project root alongside this script.

Design notes
------------
* Peer-relative where "compared to similar banks" is the right question
  (capital, efficiency, profitability, asset quality). Percentiles are computed
  WITHIN an asset band so a $200M bank is judged against other small banks.
* Absolute where a regulatory / structural line matters (the $10B tier, a
  100%+ loan-to-deposit ratio, a negative ROA).
* Nothing here is investment advice or a conclusion about a bank. It flags
  financial *symptoms* that map to advisory conversations, with the stat to
  cite. A human decides whether the story actually fits.
"""

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Tunable thresholds  --  edit these, re-run, no re-download needed.
# --------------------------------------------------------------------------- #
PCTL_HIGH = 0.80          # "top of peer group" cutoff
PCTL_XHIGH = 0.85         # "clearly an outlier vs peers"
PCTL_LOW = 0.15           # "bottom of peer group"

EFF_ABS = 70.0            # efficiency ratio (%) above which costs are heavy
LTD_ABS = 100.0           # loan-to-deposit (%) above which funding is stretched
BROKERED_ABS = 0.10       # brokered deposits >= 10% of total deposits
GROWTH_FAST = 0.15        # 15%+ YoY asset growth
GROWTH_BSA = 0.20         # 20%+ growth -> BSA/AML scaling note
NEAR_10B_LOW = 8_000_000  # $8B  (thousands)
NEAR_10B_HIGH = 10_000_000  # $10B (thousands)
# FDICIA Part 363 thresholds — updated by FDIC final rule effective Jan 1, 2026:
#   $1B  -> annual independent audit + audit-committee independence (was $500M)
#   $5B  -> ICFR management assessment + auditor attestation (was $1B)
FDICIA_1B_LOW = 850_000     # approaching/crossing $1B (thousands)
FDICIA_1B_HIGH = 1_150_000
FDICIA_5B_LOW = 4_250_000   # approaching/crossing $5B (thousands)
FDICIA_5B_HIGH = 5_500_000

# Interagency CRE concentration guidance supervisory criteria:
#   (1) construction & development >= 100% of total risk-based capital, or
#   (2) total CRE >= 300% of total risk-based capital AND CRE grew >= 50% in 36 months.
# "CRE" per the guidance = construction/land development + multifamily +
# NON-owner-occupied nonfarm nonresidential (owner-occupied is excluded).
CD_CONC = 100.0
CRE_CONC = 300.0
# Simplified reverse stress test: well-capitalized = total risk-based capital
# ratio >= 10% of RWA. The cushion above that, divided by the CRE book, is the
# CRE loss rate that would breach well-capitalized.
WELL_CAP_TRBC = 0.10
THIN_CUSHION = 10.0        # breach at a <=10% CRE loss = thin cushion
UNDERRESERVED = 40.0      # allowance < 40% of noncurrent loans

# Asset bands (in $thousands) for peer grouping.
# Top band is open-ended ("$3B+") so the community banks over $10B still land in
# a peer group and get percentile-ranked rather than dropped.
BAND_EDGES = [0, 250_000, 1_000_000, 3_000_000, 10 ** 12]
BAND_LABELS = ["<$250M", "$250M-$1B", "$1B-$3B", "$3B+"]

# Signal -> (score weight, KR Risk Advisory Services service line).
# Mapped to Kaufman Rossin RAS's ACTUAL catalog (AML/Sanctions, OFAC, Consumer
# Compliance, FINRA/SEC, Internal Audit, Cybersecurity, RPA, Risk Intelligence
# Suite). Weights favor genuine RAS-sellable signals; signals that belong to a
# different KR practice are kept visible but scored low and tagged "Refer".
SERVICE = {
    # --- Flagship: matches the empirical pre-enforcement financial profile ---
    "pre_enforcement":      (24, "KR RAS: PRE-ENFORCEMENT READINESS — risk assessment, Internal Audit, BSA/AML & remediation-readiness before regulators act"),
    # --- Strong KR RAS fits ---------------------------------------------
    "near_10b_threshold":   (22, "KR RAS: $10B readiness — Consumer Compliance (CFPB), Durbin, expanded BSA/AML, Internal Audit, DFAST"),
    "bsa_aml_scaling":      (20, "KR RAS: BSA/AML program enhancement + independent testing (AML & Sanctions / OFAC)"),
    "thin_cre_cushion":     (22, "KR RAS: CRE stress testing + capital planning — reverse stress test shows a modest CRE loss breaches well-capitalized"),
    "cre_concentration":    (20, "KR RAS: CRE loan review, credit risk review, CECL/ALLL, CRE stress testing (>=300% of capital — supervisory concentration criteria)"),
    "cd_concentration":     (20, "KR RAS: construction & development loan review + credit risk management (>=100% of capital — supervisory concentration criteria)"),
    "near_fdicia_5b":       (20, "KR RAS: FDICIA Part 363 ICFR management assessment + auditor attestation (crossing $5B; threshold raised from $1B, effective 2026)"),
    "near_fdicia_1b":       (18, "KR RAS: FDICIA Part 363 annual independent audit + audit-committee independence (crossing $1B; threshold raised from $500M, effective 2026)"),
    "rapid_growth":         (18, "KR RAS: BSA/AML scaling, Internal Audit, enterprise risk assessment; FDICIA Part 363 audit if crossing $1B, ICFR if crossing $5B"),
    "credit_deterioration": (18, "KR RAS: Internal Audit loan review + CECL model validation + ALLL/CECL governance"),
    "weak_efficiency":      (15, "KR RAS: Robotic Process Automation (RPA) + Internal Audit process review"),
    "under_reserved":       (10, "KR RAS: CECL model validation / reserve adequacy review"),
    # --- Partial fit ----------------------------------------------------
    "funding_liquidity":    (10, "KR RAS (partial): Internal Audit of liquidity/funding risk controls; ALM advisory is another practice"),
    # --- Not RAS: surface but refer to another KR practice --------------
    "excess_capital":       (5,  "Refer: capital deployment / M&A (other KR practice); RAS angle = M&A compliance due diligence"),
    "weak_profitability":   (5,  "Refer: earnings / margin advisory (other KR practice); RAS angle = cost automation via RPA"),
}


def load():
    inst = pd.read_csv("data/institutions.csv")
    cur = pd.read_csv("data/fin_current.csv")
    pri = pd.read_csv("data/fin_prior.csv")[["CERT", "ASSET"]].rename(
        columns={"ASSET": "ASSET_PRIOR"}
    )
    # Active institutions define the universe; inner-join keeps only real,
    # currently-operating banks and attaches their financials.
    df = inst.merge(cur, on="CERT", how="inner", suffixes=("", "_fin"))
    df = df.merge(pri, on="CERT", how="left")
    return df


def add_derived(df):
    num = ["ASSET", "DEP", "EQV", "RBC1AAJ", "RBCRWAJ", "RBCT1CER", "ROA", "ROE",
           "NIMY", "EEFFR", "NCLNLSR", "NPERFV", "ELNANTR", "LNATRESR",
           "LNLSNTV", "LNLSDEPR", "BRO", "ASSET_PRIOR",
           "LNRECONS", "LNREMULT", "LNRENROT", "LNRENROW", "RBCT1J", "RBCT2", "RWAJT"]
    for c in num:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")

    # --- CRE concentration (interagency guidance definition) ---
    df["TRBC"] = df["RBCT1J"].fillna(0) + df["RBCT2"].fillna(0)      # total risk-based capital
    df["CRE_TOTAL"] = (df["LNRECONS"].fillna(0) + df["LNREMULT"].fillna(0)
                       + df["LNRENROT"].fillna(0))                    # excl. owner-occupied
    df["cre_ratio"] = np.where(df["TRBC"] > 0, df["CRE_TOTAL"] / df["TRBC"] * 100, np.nan)
    df["cd_ratio"] = np.where(df["TRBC"] > 0, df["LNRECONS"] / df["TRBC"] * 100, np.nan)

    # --- Simplified reverse stress test ---
    # Capital cushion above well-capitalized, expressed as the CRE loss rate that
    # would consume it. Mirrors the reverse-stress work paper, from public data.
    cushion = df["TRBC"] - WELL_CAP_TRBC * df["RWAJT"]
    df["cre_breach_loss_pct"] = np.where(
        (df["CRE_TOTAL"] > 0) & (cushion > 0), cushion / df["CRE_TOTAL"] * 100, np.nan)

    df["asset_band"] = pd.cut(df["ASSET"], bins=BAND_EDGES, labels=BAND_LABELS,
                              right=False)
    df["asset_musd"] = (df["ASSET"] / 1000).round(1)          # $ millions
    df["brokered_pct"] = np.where(df["DEP"] > 0, df["BRO"] / df["DEP"], np.nan)
    df["asset_growth_yoy"] = np.where(
        df["ASSET_PRIOR"] > 0,
        (df["ASSET"] - df["ASSET_PRIOR"]) / df["ASSET_PRIOR"],
        np.nan,
    )
    return df


def add_percentiles(df):
    """Within-band percentile rank (0-1) for each ratio that a signal uses."""
    cols = ["EQV", "RBC1AAJ", "EEFFR", "NCLNLSR", "NPERFV", "ROA", "LNLSDEPR"]
    for c in cols:
        df[c + "_pct"] = (
            df.groupby("asset_band", observed=True)[c]
            .rank(pct=True)
        )
    return df


def apply_signals(df):
    p_hi, p_xhi, p_lo = PCTL_HIGH, PCTL_XHIGH, PCTL_LOW

    sig = {}
    # 1. Excess capital: equity/assets in the top of the peer group.
    sig["excess_capital"] = df["EQV_pct"] >= p_hi

    # 2. Credit deterioration: charge-offs OR noncurrent worse than peers.
    sig["credit_deterioration"] = (
        (df["NCLNLSR_pct"] >= p_xhi) | (df["NPERFV_pct"] >= p_xhi)
    )
    # 2b. Under-reserved intensifier (only meaningful alongside deterioration).
    sig["under_reserved"] = sig["credit_deterioration"] & (df["ELNANTR"] < UNDERRESERVED)

    # 3. Weak efficiency: costs heavy in absolute AND relative terms.
    sig["weak_efficiency"] = (df["EEFFR"] >= EFF_ABS) & (df["EEFFR_pct"] >= p_hi)

    # 4. Funding / liquidity: stretched loan-to-deposit or brokered reliance.
    sig["funding_liquidity"] = (
        (df["LNLSDEPR"] >= LTD_ABS) | (df["LNLSDEPR_pct"] >= p_xhi) |
        (df["brokered_pct"] >= BROKERED_ABS)
    )

    # 5. Rapid growth (balance-sheet scaling faster than peers).
    sig["rapid_growth"] = df["asset_growth_yoy"] >= GROWTH_FAST

    # 6. Approaching the $10B regulatory tier.
    sig["near_10b_threshold"] = (
        (df["ASSET"] >= NEAR_10B_LOW) & (df["ASSET"] < NEAR_10B_HIGH)
    )

    # 6b. Approaching / just past the $1B FDICIA Part 363 audit trigger (2026).
    sig["near_fdicia_1b"] = (
        (df["ASSET"] >= FDICIA_1B_LOW) & (df["ASSET"] < FDICIA_1B_HIGH)
    )
    # 6c. Approaching / just past the $5B FDICIA Part 363 ICFR trigger (2026).
    sig["near_fdicia_5b"] = (
        (df["ASSET"] >= FDICIA_5B_LOW) & (df["ASSET"] < FDICIA_5B_HIGH)
    )

    # 7. Weak profitability: bottom of peer group or losing money.
    sig["weak_profitability"] = (df["ROA_pct"] <= p_lo) | (df["ROA"] < 0)

    # 8. BSA/AML scaling proxy: very fast growth (program must scale with risk).
    sig["bsa_aml_scaling"] = df["asset_growth_yoy"] >= GROWTH_BSA

    # 8b. CRE concentration — interagency supervisory criteria.
    sig["cd_concentration"] = df["cd_ratio"] >= CD_CONC
    # The 300% leg also requires 36-month growth >= 50%; that leg is added in
    # 05_trajectory.py (which has the history). This flags the concentration itself.
    sig["cre_concentration"] = df["cre_ratio"] >= CRE_CONC
    # 8c. Reverse stress: a modest CRE loss would breach well-capitalized.
    sig["thin_cre_cushion"] = (df["cre_breach_loss_pct"] <= THIN_CUSHION) & (df["cre_ratio"] >= 100)

    # 9. Pre-enforcement profile: matches what banks looked like ~1yr before an
    #    OCC/Fed order (see study/FINDINGS.md) — weak earnings, high cost, weak
    #    asset quality, brokered-funding reliance. Fires on 3+ of the 4 dimensions.
    d_earn = (df["ROA_pct"] <= 0.25).fillna(False)
    d_cost = (df["EEFFR_pct"] >= 0.75).fillna(False)
    d_credit = ((df["NPERFV_pct"] >= 0.75) | (df["NCLNLSR_pct"] >= 0.75)).fillna(False)
    d_fund = (df["brokered_pct"] >= 0.10).fillna(False)
    sig["pre_enforcement"] = (d_earn.astype(int) + d_cost.astype(int)
                              + d_credit.astype(int) + d_fund.astype(int)) >= 3

    for k, v in sig.items():
        df[k] = v.fillna(False).astype(bool)
    return df, list(sig.keys())


def assemble(df, signal_cols):
    def row_signals(r):
        return [s for s in signal_cols if r[s]]

    df["_matched"] = df.apply(row_signals, axis=1)
    df["signals"] = df["_matched"].apply(lambda xs: "; ".join(xs))
    df["service_lines"] = df["_matched"].apply(
        lambda xs: "; ".join(dict.fromkeys(SERVICE[s][1] for s in xs))
    )
    df["n_signals"] = df["_matched"].apply(len)
    df["score"] = df["_matched"].apply(lambda xs: sum(SERVICE[s][0] for s in xs))
    return df


def main():
    df = add_derived(load())
    df = add_percentiles(df)
    df, signal_cols = apply_signals(df)
    df = assemble(df, signal_cols)

    out_cols = [
        "CERT", "NAME", "CITY", "STALP", "asset_band", "asset_musd",
        "n_signals", "score", "signals", "service_lines",
        # headline stats to cite in outreach
        "EQV", "EQV_pct", "RBC1AAJ", "RBCT1CER", "ROA", "ROA_pct", "ROE",
        "NIMY", "EEFFR", "EEFFR_pct", "NCLNLSR", "NPERFV", "ELNANTR",
        "LNLSDEPR", "brokered_pct", "asset_growth_yoy",
        "cre_ratio", "cd_ratio", "cre_breach_loss_pct",
    ]
    ranked = df[df["n_signals"] > 0].sort_values(
        ["score", "n_signals", "asset_musd"], ascending=False
    )
    ranked[out_cols].round(3).to_csv("output/targets.csv", index=False)

    # Full scored universe (every bank, flagged or not) so the trajectory step
    # can enrich all of them — including banks the snapshot didn't flag but whose
    # trend is turning.
    df[out_cols].round(3).to_csv("output/all_banks.csv", index=False)

    # per-signal counts
    summ = pd.DataFrame({
        "signal": signal_cols,
        "banks_flagged": [int(df[s].sum()) for s in signal_cols],
        "service_line": [SERVICE[s][1] for s in signal_cols],
        "weight": [SERVICE[s][0] for s in signal_cols],
    }).sort_values("banks_flagged", ascending=False)
    summ.to_csv("output/signal_summary.csv", index=False)

    print(f"Universe screened:        {len(df):,} active community banks")
    print(f"Banks with >=1 signal:    {len(ranked):,}")
    print(f"Banks with >=3 signals:   {int((df['n_signals'] >= 3).sum()):,}")
    print("\nBanks flagged per signal:")
    for _, r in summ.iterrows():
        print(f"  {r['signal']:<22} {r['banks_flagged']:>5,}")


if __name__ == "__main__":
    main()
