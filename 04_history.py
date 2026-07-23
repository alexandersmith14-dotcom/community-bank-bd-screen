"""
04_history.py  --  Pull 20 quarters of history for the community-bank universe.

Writes ./data/history.csv (long format: one row per bank per quarter) with the
subset of ratios the trajectory step needs. This is what turns the screen from a
snapshot into a read on *direction of travel* — is capital building, is credit
turning, is growth accelerating toward the $10B line.

Banks that didn't exist (or filed above the cap) in an earlier quarter simply
have fewer rows; the trajectory step handles short histories gracefully.
"""

import time
import requests
import pandas as pd

API = "https://api.fdic.gov/banks"
ASSET_CAP_THOUSANDS = 10_000_000
N_QUARTERS = 20   # ~5 years

# Metrics tracked through time (kept lean to limit payload).
HIST_FIELDS = [
    "CERT", "REPDTE", "ASSET",
    "EQV",       # equity / assets
    "RBC1AAJ",   # tier 1 leverage
    "NCLNLSR",   # net charge-offs / loans
    "NPERFV",    # noncurrent assets / assets
    "EEFFR",     # efficiency ratio
    "ROA",
    "LNLSDEPR",  # loan / deposit
    "BRO", "DEP",
]


def latest_repdte():
    r = requests.get(
        f"{API}/financials",
        params={"fields": "REPDTE", "sort_by": "REPDTE",
                "sort_order": "DESC", "limit": 1, "format": "json"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["data"][0]["data"]["REPDTE"]


def quarter_series(latest, n):
    """Return the n most recent quarter-end dates ending at `latest`."""
    y, m = int(latest[:4]), int(latest[4:6])
    dates = []
    for _ in range(n):
        dates.append(f"{y}{m:02d}{ {3:'31',6:'30',9:'30',12:'31'}[m] }")
        m -= 3
        if m <= 0:
            m += 12
            y -= 1
    return dates


def fetch_quarter(repdte, cap):
    rows, offset, limit = [], 0, 5000
    while True:
        params = {
            "filters": f"REPDTE:{repdte} AND (ASSET:[0 TO {cap}] OR CB:1)",
            "fields": ",".join(HIST_FIELDS),
            "limit": limit, "offset": offset, "format": "json",
        }
        r = requests.get(f"{API}/financials", params=params, timeout=60)
        r.raise_for_status()
        batch = r.json().get("data", [])
        if not batch:
            break
        rows.extend(d["data"] for d in batch)
        offset += limit
        if len(batch) < limit:
            break
    return rows


def main():
    latest = latest_repdte()
    dates = quarter_series(latest, N_QUARTERS)
    print(f"Pulling {len(dates)} quarters: {dates[-1]} .. {dates[0]}")

    frames = []
    for d in dates:
        rows = fetch_quarter(d, ASSET_CAP_THOUSANDS)
        print(f"  {d}: {len(rows):,}")
        frames.append(pd.DataFrame(rows))
        time.sleep(0.25)

    hist = pd.concat(frames, ignore_index=True)
    hist.to_csv("data/history.csv", index=False)
    print(f"Wrote data/history.csv  ({len(hist):,} rows)")


if __name__ == "__main__":
    main()
