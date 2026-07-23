"""
01_fetch.py  --  Pull the community-bank universe from the FDIC BankFind API.

Outputs (into ./data):
  institutions.csv   identity + class for every ACTIVE bank under the asset cap
  fin_current.csv     latest-quarter financial ratios (one row per CERT)
  fin_prior.csv       same fields one year earlier (for year-over-year growth)

Nothing here makes judgments about banks. It only downloads primary FDIC data
so the screening step (02_screen.py) can run offline and be re-tuned freely.
"""

import time
import requests
import pandas as pd

API = "https://api.fdic.gov/banks"

# ---- What counts as a "community bank" for the pull -------------------------
# FDIC reports ASSET in THOUSANDS of dollars, so $10B = 10,000,000.
ASSET_CAP_THOUSANDS = 10_000_000

# ---- Report dates -----------------------------------------------------------
# "auto" asks the API for the newest quarter (so the scheduled refresh always
# picks up new FDIC data); or hard-code "YYYYMMDD" to pin a quarter.
CURRENT_REPDTE = "auto"
PRIOR_REPDTE   = "auto"   # same quarter one year earlier (for YoY growth)


def resolve_dates():
    global CURRENT_REPDTE, PRIOR_REPDTE
    if CURRENT_REPDTE == "auto":
        r = requests.get(
            f"{API}/financials",
            params={"fields": "REPDTE", "sort_by": "REPDTE",
                    "sort_order": "DESC", "limit": 1, "format": "json"},
            timeout=60,
        )
        r.raise_for_status()
        CURRENT_REPDTE = r.json()["data"][0]["data"]["REPDTE"]
    if PRIOR_REPDTE == "auto":
        PRIOR_REPDTE = str(int(CURRENT_REPDTE[:4]) - 1) + CURRENT_REPDTE[4:]
    print(f"Using current={CURRENT_REPDTE}  prior={PRIOR_REPDTE}")

# ---- Fields ----------------------------------------------------------------
INST_FIELDS = ["CERT", "NAME", "CITY", "STALP", "BKCLASS", "ACTIVE"]

FIN_FIELDS = [
    "CERT", "REPDTE", "ASSET", "DEP", "NUMEMP",
    # capital
    "EQV",        # equity capital to assets (%)
    "RBC1AAJ",    # tier 1 leverage ratio (%)
    "RBCRWAJ",    # total risk-based capital ratio (%)
    "RBCT1CER",   # common equity tier 1 (CET1) ratio (%)
    # profitability
    "ROA", "ROE", "NIMY",
    # efficiency
    "EEFFR",      # efficiency ratio (%)
    # asset quality
    "NCLNLSR",    # net charge-offs to loans (%)
    "NPERFV",     # noncurrent assets + OREO to assets (%)
    "ELNANTR",    # allowance as % of noncurrent loans (coverage)
    "LNATRESR",   # allowance to total loans (%)
    # loans / funding
    "LNLSNTV",    # net loans & leases to assets (%)
    "LNLSDEPR",   # net loans & leases to deposits (%)
    "BRO",        # brokered deposits ($000s)
]


def fetch_all(endpoint, filters, fields):
    """Page through an FDIC list endpoint and return every matching row."""
    rows, offset, limit = [], 0, 5000
    while True:
        params = {
            "filters": filters,
            "fields": ",".join(fields),
            "limit": limit,
            "offset": offset,
            "format": "json",
        }
        r = requests.get(f"{API}/{endpoint}", params=params, timeout=60)
        r.raise_for_status()
        batch = r.json().get("data", [])
        if not batch:
            break
        rows.extend(d["data"] for d in batch)
        offset += limit
        if len(batch) < limit:
            break
        time.sleep(0.3)
    return pd.DataFrame(rows)


def main():
    resolve_dates()
    cap = ASSET_CAP_THOUSANDS
    # Universe = everything under the asset cap PLUS any bank FDIC officially
    # flags as a community bank (CB:1), which adds back the ~15 community banks
    # that are over $10B. The under-cap set still includes non-community
    # specialty banks, kept as BD "potentials".
    universe = f"(ASSET:[0 TO {cap}] OR CB:1)"

    print("Fetching active institutions (under cap OR FDIC community bank) ...")
    inst = fetch_all(
        "institutions",
        filters=f"ACTIVE:1 AND {universe}",
        fields=INST_FIELDS,
    )
    inst.to_csv("data/institutions.csv", index=False)
    print(f"  institutions: {len(inst):,}")

    print("Fetching current-quarter financials ...")
    cur = fetch_all(
        "financials",
        filters=f"REPDTE:{CURRENT_REPDTE} AND {universe}",
        fields=FIN_FIELDS,
    )
    cur.to_csv("data/fin_current.csv", index=False)
    print(f"  fin_current: {len(cur):,}")

    print("Fetching prior-year financials (assets only needed) ...")
    pri = fetch_all(
        "financials",
        filters=f"REPDTE:{PRIOR_REPDTE} AND {universe}",
        fields=["CERT", "REPDTE", "ASSET"],
    )
    pri.to_csv("data/fin_prior.csv", index=False)
    print(f"  fin_prior:   {len(pri):,}")

    with open("data/repdte.txt", "w") as f:
        f.write(CURRENT_REPDTE)

    print("Done.")


if __name__ == "__main__":
    main()
