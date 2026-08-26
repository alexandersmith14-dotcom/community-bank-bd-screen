"""
12_sod_market_share.py  --  Deposit market share and local market concentration
(FDIC Summary of Deposits), merged into the bank target list.

Pulls the FULL national branch-level SOD file (every FDIC-insured bank, not
just the community-bank universe) for the latest year and the year before, so
market totals and HHI reflect real local competition -- including branches of
big banks that never show up anywhere else in this pipeline.

For each bank already on the target list (output/targets.csv), finds its
primary county (largest branch-deposit footprint), that county's total insured
deposits and HHI, and the bank's own share there -- then flags:
  deposit_share_rising      gained 1+ pt of primary-county deposit share YoY
  deposit_share_declining   lost 1+ pt of primary-county deposit share YoY
  dominant_market_position  holds 25%+ of primary-county insured deposits

Rewrites output/targets.csv in place (adds sod_* columns, appends any newly
tripped signals to signals/score) -- same rewrite pattern as 05_trajectory.py.
Safe to re-run: strips any sod_* columns and previously appended sod signals
first, so a manual rerun without redoing the earlier steps doesn't double-count
(see the ft_targets.csv idempotency gotcha in 11_state_licenses.py).
"""

import time
import numpy as np
import pandas as pd
import requests

API = "https://api.fdic.gov/banks"
FIELDS = ["CERT", "DEPSUMBR", "STCNTYBR", "STALPBR", "CNTYNAMB", "YEAR"]

SHARE_MIN = 0.03      # only trust a share trend once the bank holds a real position
SHARE_RISE = 0.01     # +1 point YoY
SHARE_FALL = -0.01    # -1 point YoY
DOMINANT = 0.25        # 25%+ of a county's insured deposits

# signal -> (score weight, KR RAS service line). Same calibration style as the
# maps in 02_screen.py / 05_trajectory.py.
SODSERVICE = {
    "deposit_share_rising": (14, "KR RAS: BSA/AML scaling, Internal Audit, risk assessment -- gaining local deposit market share faster than the market"),
    "deposit_share_declining": (10, "Refer: strategic / M&A advisory (other KR practice); RAS angle = RPA cost automation + risk assessment before a sale or restructuring"),
    "dominant_market_position": (6, "Refer: M&A / de novo expansion advisory (other KR practice); RAS angle = readiness review before further growth"),
}


def resolve_years():
    r = requests.get(f"{API}/sod", params={
        "fields": "YEAR", "sort_by": "YEAR", "sort_order": "DESC",
        "limit": 1, "format": "json",
    }, timeout=60)
    r.raise_for_status()
    latest = int(r.json()["data"][0]["data"]["YEAR"])
    return latest, latest - 1


def fetch_year(year):
    """Page through the FULL national SOD file for one year (every insured bank)."""
    rows, offset, limit = [], 0, 5000
    while True:
        params = {
            "filters": f"YEAR:{year}",
            "fields": ",".join(FIELDS),
            "limit": limit,
            "offset": offset,
            "format": "json",
        }
        r = requests.get(f"{API}/sod", params=params, timeout=60)
        r.raise_for_status()
        batch = r.json().get("data", [])
        if not batch:
            break
        rows.extend(d["data"] for d in batch)
        offset += limit
        if len(batch) < limit:
            break
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    print(f"  SOD {year}: {len(df):,} branch records")
    return df


def market_table(sod):
    """Per (YEAR, CERT, county): the bank's deposits there, the county total
    across ALL insured banks, the bank's share, and the county's HHI."""
    sod = sod.copy()
    sod["DEPSUMBR"] = pd.to_numeric(sod["DEPSUMBR"], errors="coerce").fillna(0)
    sod["CERT"] = pd.to_numeric(sod["CERT"], errors="coerce")
    sod = sod.dropna(subset=["CERT", "STCNTYBR"])
    sod["CERT"] = sod["CERT"].astype(int)

    bank_mkt = (sod.groupby(["YEAR", "CERT", "STCNTYBR"], as_index=False)
                .agg(DEP=("DEPSUMBR", "sum"),
                     CNTYNAMB=("CNTYNAMB", "first"),
                     STALPBR=("STALPBR", "first")))
    mkt_tot = (sod.groupby(["YEAR", "STCNTYBR"])["DEPSUMBR"].sum()
               .rename("MKT_TOTAL").reset_index())
    bank_mkt = bank_mkt.merge(mkt_tot, on=["YEAR", "STCNTYBR"], how="left")
    bank_mkt["share"] = np.where(bank_mkt["MKT_TOTAL"] > 0,
                                  bank_mkt["DEP"] / bank_mkt["MKT_TOTAL"], np.nan)

    hhi = (bank_mkt.assign(sq=bank_mkt["share"] ** 2)
           .groupby(["YEAR", "STCNTYBR"])["sq"].sum() * 10000).rename("HHI").reset_index()
    bank_mkt = bank_mkt.merge(hhi, on=["YEAR", "STCNTYBR"], how="left")
    return bank_mkt


def main():
    cur_year, pri_year = resolve_years()
    print(f"Using SOD years current={cur_year} prior={pri_year}")

    print("Fetching full national SOD (all insured banks, for real market totals) ...")
    sod = pd.concat([fetch_year(cur_year), fetch_year(pri_year)], ignore_index=True)
    bank_mkt = market_table(sod)

    targets = pd.read_csv("output/targets.csv")

    # Idempotency: strip any sod_* columns / previously appended sod signals
    # (and their score weight) from a prior run before recomputing -- otherwise
    # a rerun keeps adding the same weight on top of the already-boosted score.
    sod_cols = ["sod_primary_county", "sod_primary_state", "sod_market_share",
                "sod_market_share_prior", "sod_share_delta", "sod_market_hhi"]
    targets = targets.drop(columns=[c for c in sod_cols if c in targets.columns])

    def strip_prior_sod(r):
        toks = r["signals"].split("; ") if r["signals"] else []
        removed = [t for t in toks if t in SODSERVICE]
        kept = [t for t in toks if t not in SODSERVICE]
        return pd.Series({
            "signals": "; ".join(kept),
            "score": int(r["score"]) - sum(SODSERVICE[t][0] for t in removed),
        })

    targets["signals"] = targets["signals"].fillna("")
    stripped = targets.apply(strip_prior_sod, axis=1)
    targets["signals"], targets["score"] = stripped["signals"], stripped["score"]

    cur = bank_mkt[bank_mkt["YEAR"] == cur_year]
    primary = (cur.sort_values("DEP", ascending=False)
               .drop_duplicates("CERT", keep="first")
               [["CERT", "STCNTYBR", "CNTYNAMB", "STALPBR", "share", "HHI"]]
               .rename(columns={"share": "sod_market_share", "HHI": "sod_market_hhi",
                                 "CNTYNAMB": "sod_primary_county",
                                 "STALPBR": "sod_primary_state"}))

    pri = (bank_mkt[bank_mkt["YEAR"] == pri_year][["CERT", "STCNTYBR", "share"]]
           .rename(columns={"share": "sod_market_share_prior"}))
    primary = primary.merge(pri, on=["CERT", "STCNTYBR"], how="left")
    primary["sod_share_delta"] = primary["sod_market_share"] - primary["sod_market_share_prior"]
    primary = primary.drop(columns="STCNTYBR")

    m = targets.merge(primary, on="CERT", how="left")

    sig = {
        "deposit_share_rising": ((m["sod_market_share"] >= SHARE_MIN) &
                                  (m["sod_share_delta"] >= SHARE_RISE)).fillna(False),
        "deposit_share_declining": ((m["sod_market_share"] >= SHARE_MIN) &
                                     (m["sod_share_delta"] <= SHARE_FALL)).fillna(False),
        "dominant_market_position": (m["sod_market_share"] >= DOMINANT).fillna(False),
    }
    for k, v in sig.items():
        m[k] = v

    def merge_row(r):
        extra = [k for k in SODSERVICE if r[k]]
        sigs = [s for s in r["signals"].split("; ") if s] + extra
        score = int(r["score"]) + sum(SODSERVICE[k][0] for k in extra)
        return pd.Series({"signals": "; ".join(sigs), "n_signals": len(sigs), "score": score})

    merged = m.apply(merge_row, axis=1)
    m["signals"], m["n_signals"], m["score"] = merged["signals"], merged["n_signals"], merged["score"]

    m = m.sort_values(["score", "n_signals", "asset_musd"], ascending=False)
    m.round(3).to_csv("output/targets.csv", index=False)

    n_matched = int(m["sod_market_share"].notna().sum())
    print(f"Banks with primary-market data: {n_matched:,} / {len(m):,}")
    print("SOD signals flagged:")
    for k, v in sig.items():
        print(f"  {k:<26} {int(v.sum()):>5,}")


if __name__ == "__main__":
    main()
