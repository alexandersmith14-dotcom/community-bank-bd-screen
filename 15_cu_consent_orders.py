"""
15_cu_consent_orders.py  --  NCUA formal enforcement actions (Administrative
Orders), merged into the credit-union target list.

Same concept as 14_consent_orders.py for banks: ground truth, not a modeled
proxy. Reuses the bank pipeline's `consent_order` signal key so the dashboard
shows one consistent chip/description regardless of institution type.

**Expected to flag close to nothing, and that's fine.** NCUA's public
disclosure page (ncua.gov/news/enforcement-actions/administrative-orders)
offers a plain, static CSV -- no Playwright needed, unlike FDIC/OCC -- but
verified against real data that every institution-level order in the last 5
years targets a credit union well under our $500M screening floor
(`ASSET_FLOOR` in 07_cu_fetch.py): the best fuzzy-match score across all 18
candidates was 78.6, below the 88 threshold used everywhere else in this
pipeline -- i.e. zero real matches at the time this was built. This is a
safety net for the day a $500M+ credit union gets one, not a signal expected
to fire regularly. Cheap to keep, same pattern as everything else here.

**Data quality note.** NCUA's CSV mixes individual actions (prohibitions
against former employees/officers -- the large majority of rows) with
institution-level orders, and has no clean "action type" or status column
distinguishing them (unlike FDIC/OCC/Fed). Verified empirically: on an
institution-level row, the credit union's own name appears in BOTH the
`Institution` and `Relationship` columns identically -- that equality is the
only reliable filter found. There's also no exact date, only `Year`, so the
lookback window is coarser than the bank version's, and no way to tell
active vs. terminated -- both accepted scope boundaries, not oversights.

Rewrites output/cu_targets.csv in place. Idempotent: strips prior
consent_order_* columns and appended signal+score before recomputing.
"""

import io
import re

import pandas as pd
import requests
from rapidfuzz import fuzz

CONSENT_LOOKBACK_YEARS = 5
MATCH_THRESHOLD = 88   # same threshold as every fuzzy match elsewhere in this pipeline

CONSENTSERVICE = {
    "consent_order": (26, "KR RAS: BSA/AML & Sanctions remediation, Internal Audit, independent testing -- under (or recently under) a formal enforcement order with a live compliance mandate"),
}

NCUA_CSV = "https://ncua.gov/sites/default/files/list_csv/administrative-orders.csv"


def core_name(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    s = re.sub(r"\b(inc|llc|corp|corporation|co|company|ltd|limited|the|federal|"
               r"credit|union|fcu|cu)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_ncua_orders(cutoff_year):
    try:
        r = requests.get(NCUA_CSV, timeout=60)
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content), dtype=str)
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        df = df[df["Year"] >= cutoff_year]
        # Institution-level heuristic, verified against real data: on those
        # rows the CU's own name lands in both Institution and Relationship.
        df = df[df["Institution"].notna() & (df["Relationship"] == df["Institution"])]
        print(f"  NCUA: {len(df):,} institution-level Administrative Orders (last {CONSENT_LOOKBACK_YEARS}yr)")
        return df
    except Exception as e:
        print(f"  NCUA fetch failed, skipping: {e}")
        return None


def match_ncua_to_cu(ncua_df, cu):
    pool = [(row["CU_NUMBER"], core_name(row["NAME"])) for _, row in cu.iterrows()]
    pool = [(c, n) for c, n in pool if len(n) >= 4]

    rows = []
    for _, row in ncua_df.iterrows():
        cand = core_name(row["Institution"])
        if len(cand) < 4:
            continue
        best_cert, best_score = None, 0
        for cu_number, name in pool:
            if abs(len(name) - len(cand)) > 15:
                continue
            score = fuzz.token_sort_ratio(cand, name)
            if score > best_score:
                best_cert, best_score = cu_number, score
        if best_score >= MATCH_THRESHOLD:
            rows.append({"CERT": best_cert, "Year": row["Year"]})
    return pd.DataFrame(rows)


def main():
    targets = pd.read_csv("output/cu_targets.csv")
    cu = pd.read_csv("data/cu_current.csv")

    consent_cols = ["consent_order_count", "consent_order_date",
                     "consent_order_title", "consent_order_status"]
    targets = targets.drop(columns=[c for c in consent_cols if c in targets.columns])

    def strip_prior(r):
        toks = r["signals"].split("; ") if r["signals"] else []
        removed = [t for t in toks if t in CONSENTSERVICE]
        kept = [t for t in toks if t not in CONSENTSERVICE]
        return pd.Series({
            "signals": "; ".join(kept),
            "score": int(r["score"]) - sum(CONSENTSERVICE[t][0] for t in removed),
        })

    targets["signals"] = targets["signals"].fillna("")
    stripped = targets.apply(strip_prior, axis=1)
    targets["signals"], targets["score"] = stripped["signals"], stripped["score"]

    cutoff_year = pd.Timestamp.now().year - CONSENT_LOOKBACK_YEARS
    ncua = fetch_ncua_orders(cutoff_year)
    if ncua is None or ncua.empty:
        targets["n_signals"] = targets["signals"].apply(
            lambda s: len([t for t in s.split("; ") if t]))
        targets = targets[targets["n_signals"] > 0]
        targets.round(3).to_csv("output/cu_targets.csv", index=False)
        print("No NCUA data -- cu_targets.csv rewritten with prior consent-order state cleared.")
        return

    matched = match_ncua_to_cu(ncua, cu)
    print(f"  Matched {len(matched):,} of {len(ncua):,} NCUA orders to a credit union >= $500M")

    if matched.empty:
        targets["n_signals"] = targets["signals"].apply(
            lambda s: len([t for t in s.split("; ") if t]))
        targets = targets[targets["n_signals"] > 0]
        targets.round(3).to_csv("output/cu_targets.csv", index=False)
        print("consent_order flagged: 0")
        return

    matched["CERT"] = matched["CERT"].astype(int)

    def per_cu(g):
        g = g.sort_values("Year")
        last = g.iloc[-1]
        return pd.Series({
            "consent_order_count": len(g),
            "consent_order_date": str(int(last["Year"])),
            "consent_order_title": "NCUA Administrative Order",
            "consent_order_status": f"On record {int(last['Year'])} (NCUA doesn't publish termination status)",
        })

    agg = matched.groupby("CERT").apply(per_cu, include_groups=False).reset_index()

    # Same pull-in-new-banks logic as 14_consent_orders.py: cu_current.csv
    # IS the full >=$500M universe (no separate all-CUs file needed), so any
    # matched CERT not already on cu_targets.csv gets pulled in from it.
    new_certs = set(agg["CERT"]) - set(targets["CERT"])
    if new_certs:
        new_rows = cu[cu["CU_NUMBER"].isin(new_certs)].copy()
        new_rows["CERT"] = new_rows["CU_NUMBER"]
        new_rows["INST_TYPE"] = "Credit Union"
        new_rows["asset_musd"] = (new_rows["ASSET"] / 1000).round(1)
        new_rows["signals"] = ""
        new_rows["score"] = 0
        targets = pd.concat([targets, new_rows], ignore_index=True, sort=False)
        print(f"  Added {len(new_rows):,} credit unions whose only signal is the consent order")

    m = targets.merge(agg, on="CERT", how="left")
    m["consent_order"] = m["consent_order_count"].fillna(0) >= 1

    def merge_row(r):
        extra = [k for k in CONSENTSERVICE if r[k]]
        sigs = [s for s in r["signals"].split("; ") if s] + extra
        score = int(r["score"]) + sum(CONSENTSERVICE[k][0] for k in extra)
        return pd.Series({"signals": "; ".join(sigs), "n_signals": len(sigs), "score": score})

    merged = m.apply(merge_row, axis=1)
    m["signals"], m["n_signals"], m["score"] = merged["signals"], merged["n_signals"], merged["score"]

    m = m[m["n_signals"] > 0]
    m = m.sort_values(["score", "n_signals", "asset_musd"], ascending=False)
    m.round(3).to_csv("output/cu_targets.csv", index=False)

    print(f"consent_order flagged: {int(m['consent_order'].sum()):,}")


if __name__ == "__main__":
    main()
