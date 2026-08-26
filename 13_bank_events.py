"""
13_bank_events.py  --  Recent M&A activity (FDIC `history`) and failed-bank
acquisitions (FDIC `failures`), merged into the bank target list.

Both are the same underlying BD story: a bank that just took on another
institution's customers, loans, and staff usually has its BSA/AML program and
Internal Audit function stretched by the integration -- a warm, specific
reason to call, and unambiguous (unlike the peer-percentile signals, this is
"did the event happen," not a modeled judgment).

  recent_acquirer        completed >=1 merger/acquisition (FDIC `history`,
                          CHANGECODE 810 = "Participated in Absorption/
                          Consolidation/Merger") in the last 36 months.
                          ACQ_CERT ties directly to our CERT -- no name
                          matching needed.
  failed_bank_acquirer    won an FDIC-assisted failed-bank deal (`failures`)
                          in the last 5 years. `failures` only gives the
                          winning bidder's NAME (BIDNAME), not a CERT, so this
                          leg fuzzy-matches BIDNAME against institutions.csv
                          the same way 11_state_licenses.py matches fintech
                          names against state license rosters. Payout
                          resolutions (RESTYPE1 == "PO", no acquirer) are
                          excluded -- nobody absorbed anything in a payout.

Rewrites output/targets.csv in place, same pattern as 05_trajectory.py /
12_sod_market_share.py. Idempotent: strips any events_*/failed_* columns and
previously appended signals+score before recomputing.
"""

import re
import time
from datetime import date

import pandas as pd
import requests
from rapidfuzz import fuzz

API = "https://api.fdic.gov/banks"

MERGER_LOOKBACK_MONTHS = 36
FAILURE_LOOKBACK_YEARS = 5
MATCH_THRESHOLD = 88   # rapidfuzz token_sort_ratio, same threshold as 11_state_licenses.py

EVENTSERVICE = {
    "recent_acquirer": (14, "KR RAS: BSA/AML scaling, Internal Audit, risk assessment -- integrating an acquired bank's customers, loans, and staff"),
    "failed_bank_acquirer": (20, "KR RAS: BSA/AML scaling, Internal Audit, risk assessment -- absorbed a failed bank's book via an FDIC-assisted deal, usually on a compressed timeline"),
}


def core_name(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    s = re.sub(r"\b(inc|llc|corp|corporation|co|company|ltd|limited|the|bank|na|n a|national association)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def months_ago(n):
    d = date.today()
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(d.day, 28))


def fetch_all(endpoint, filters, fields):
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


def fetch_mergers():
    start = months_ago(MERGER_LOOKBACK_MONTHS).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    df = fetch_all(
        "history",
        filters=f"CHANGECODE:810 AND EFFDATE:[{start} TO {end}]",
        fields=["CERT", "ACQ_CERT", "OUT_INSTNAME", "EFFDATE"],
    )
    print(f"  Mergers (last {MERGER_LOOKBACK_MONTHS}mo): {len(df):,} events")
    if df.empty:
        return df
    df["CERT"] = pd.to_numeric(df["ACQ_CERT"], errors="coerce")
    return df.dropna(subset=["CERT"])


def fetch_failures():
    cutoff = date.today().replace(year=date.today().year - FAILURE_LOOKBACK_YEARS)
    df = fetch_all(
        "failures",
        filters=f"FAILYR:[{cutoff.year} TO {date.today().year}]",
        fields=["CERT", "NAME", "FAILDATE", "RESTYPE1", "BIDNAME", "QBFDEP"],
    )
    print(f"  Failures (last {FAILURE_LOOKBACK_YEARS}yr): {len(df):,} events")
    if df.empty:
        return df
    return df[(df["RESTYPE1"] != "PO") & df["BIDNAME"].notna() & (df["BIDNAME"] != "")]


def match_failures(failures, institutions):
    """Fuzzy-match each failure's winning bidder (BIDNAME) to our bank universe."""
    inst_names = list(zip(institutions["CERT"], institutions["NAME"].apply(core_name)))
    inst_names = [(c, n) for c, n in inst_names if len(n) >= 4]

    matches = []   # (acquirer CERT, failed bank name, fail date, deposits)
    for _, row in failures.iterrows():
        cand = core_name(row["BIDNAME"])
        if len(cand) < 4:
            continue
        best_cert, best_score = None, 0
        for cert, name in inst_names:
            if abs(len(name) - len(cand)) > 15:
                continue
            score = fuzz.token_sort_ratio(cand, name)
            if score > best_score:
                best_cert, best_score = cert, score
        if best_score >= MATCH_THRESHOLD:
            matches.append((int(best_cert), row["NAME"], row["FAILDATE"], row["QBFDEP"]))
    return pd.DataFrame(matches, columns=["CERT", "failed_bank_name", "failed_bank_date", "failed_bank_deposits"])


def main():
    targets = pd.read_csv("output/targets.csv")

    event_cols = ["events_acquired_count", "events_acquired_names", "events_last_merger_date",
                  "failed_bank_name", "failed_bank_date", "failed_bank_deposits"]
    targets = targets.drop(columns=[c for c in event_cols if c in targets.columns])

    def strip_prior(r):
        toks = r["signals"].split("; ") if r["signals"] else []
        removed = [t for t in toks if t in EVENTSERVICE]
        kept = [t for t in toks if t not in EVENTSERVICE]
        return pd.Series({
            "signals": "; ".join(kept),
            "score": int(r["score"]) - sum(EVENTSERVICE[t][0] for t in removed),
        })

    targets["signals"] = targets["signals"].fillna("")
    stripped = targets.apply(strip_prior, axis=1)
    targets["signals"], targets["score"] = stripped["signals"], stripped["score"]

    print("Fetching FDIC structure-change history (mergers) ...")
    mergers = fetch_mergers()
    print("Fetching FDIC failures ...")
    failures = fetch_failures()

    institutions = pd.read_csv("data/institutions.csv")[["CERT", "NAME"]]
    print("Fuzzy-matching failed-bank winning bidders against our bank universe ...")
    failed_matches = match_failures(failures, institutions) if not failures.empty else \
        pd.DataFrame(columns=["CERT", "failed_bank_name", "failed_bank_date", "failed_bank_deposits"])
    print(f"  Matched {len(failed_matches):,} failed-bank acquisitions to a target bank")

    if not mergers.empty:
        merger_agg = mergers.groupby("CERT").agg(
            events_acquired_count=("OUT_INSTNAME", "count"),
            events_acquired_names=("OUT_INSTNAME", lambda s: "; ".join(s)),
            events_last_merger_date=("EFFDATE", "max"),
        ).reset_index()
        merger_agg["CERT"] = merger_agg["CERT"].astype(int)
    else:
        merger_agg = pd.DataFrame(columns=["CERT", "events_acquired_count",
                                            "events_acquired_names", "events_last_merger_date"])

    # A bank can win more than one failed-bank deal in the window; keep the largest.
    if not failed_matches.empty:
        failed_matches = failed_matches.sort_values("failed_bank_deposits", ascending=False) \
            .drop_duplicates("CERT", keep="first")

    m = targets.merge(merger_agg, on="CERT", how="left")
    m = m.merge(failed_matches, on="CERT", how="left")

    sig = {
        "recent_acquirer": m["events_acquired_count"].fillna(0) >= 1,
        "failed_bank_acquirer": m["failed_bank_name"].notna(),
    }
    for k, v in sig.items():
        m[k] = v

    def merge_row(r):
        extra = [k for k in EVENTSERVICE if r[k]]
        sigs = [s for s in r["signals"].split("; ") if s] + extra
        score = int(r["score"]) + sum(EVENTSERVICE[k][0] for k in extra)
        return pd.Series({"signals": "; ".join(sigs), "n_signals": len(sigs), "score": score})

    merged = m.apply(merge_row, axis=1)
    m["signals"], m["n_signals"], m["score"] = merged["signals"], merged["n_signals"], merged["score"]

    m = m.sort_values(["score", "n_signals", "asset_musd"], ascending=False)
    m.round(3).to_csv("output/targets.csv", index=False)

    print("Event signals flagged:")
    for k, v in sig.items():
        print(f"  {k:<22} {int(v.sum()):>5,}")


if __name__ == "__main__":
    main()
