"""
14_consent_orders.py  --  FDIC formal enforcement actions (Cease & Desist /
Consent Orders) from FDIC's own Enforcement Decisions & Orders (ED&O) site,
merged into the bank target list.

Unlike every other signal in this pipeline, this one is not a modeled proxy
for risk -- it's ground truth: the bank is (or recently was) under an actual
FDIC enforcement order, which almost always comes with a court-ordered or
negotiated remediation mandate (independent BSA/AML testing, an enhanced
compliance program, board oversight reporting, etc). That's about as warm and
concrete a BD reason to call as exists in this whole tool.

**No public API for this data.** ED&O (orders.fdic.gov) is a Salesforce
Experience Cloud site with a search form and a "Download All" button that
triggers a Salesforce Aura action (`EDOSSearchForm.convertCSV`) generating a
full CSV -- there's no REST/bulk endpoint to call directly, so this fetches it
the same way 11_state_licenses.py's Massachusetts leg does: a real Playwright
browser context. Wrapped in try/except like every state-licenses fetch --
if the site is unreachable or its UI changes, this step is skipped rather
than failing the whole pipeline run.

`Cert Number` ties directly to our CERT (no fuzzy name matching needed, unlike
13_bank_events.py's `failures` leg). Multi-respondent orders join several
values with ";" in one cell (e.g. `Cert Number` = "23342;N/A;N/A" for an order
naming the bank plus two individual officers) -- the first non-"N/A" token is
the bank's CERT.

Active vs. terminated: ED&O has no clean status field, but termination orders
are titled predictably ("Order Terminating Consent Order", "Order Terminating
Decision and Order to Cease and Desist"). Per CERT, if the most recent C&D-
family event in the lookback window is one of those, the order is treated as
terminated; otherwise it's presumed still active. This only looks within the
lookback window, so an order issued before the window and terminated inside
it won't show a status -- an accepted scope boundary, not a bug.

Rewrites output/targets.csv in place, same pattern as 13_bank_events.py.
Idempotent: strips prior consent_order_* columns and appended signal+score
before recomputing.
"""

import os
import re

import pandas as pd

CONSENT_LOOKBACK_YEARS = 5

CONSENTSERVICE = {
    "consent_order": (26, "KR RAS: BSA/AML & Sanctions remediation, Internal Audit, independent testing -- under (or recently under) a formal FDIC enforcement order with a live compliance mandate"),
}


def fetch_edo_csv():
    """Drive the ED&O search form's 'Download All' button in a real browser
    and return the resulting CSV as a DataFrame, or None if anything goes
    wrong (site down, UI changed, Playwright flake) -- never crash the run."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto("https://orders.fdic.gov/s/searchform", timeout=60000,
                      wait_until="networkidle")
            with page.expect_download(timeout=60000) as dl_info:
                page.click("text=Download All")
            path = dl_info.value.path()
            df = pd.read_csv(path, dtype=str)
            browser.close()
        df.columns = [c.strip() for c in df.columns]
        print(f"  ED&O: {len(df):,} total order records")
        return df
    except Exception as e:
        print(f"  ED&O fetch failed, skipping this step: {e}")
        return None


def first_cert(s):
    """'23342;N/A;N/A' -> 23342. Multi-respondent orders join per-party
    values with ';'; the bank's CERT is the first non-'N/A' token."""
    if pd.isna(s):
        return None
    for tok in str(s).split(";"):
        tok = tok.strip()
        if tok and tok.upper() != "N/A":
            try:
                return int(tok)
            except ValueError:
                continue
    return None


def main():
    targets = pd.read_csv("output/targets.csv")

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

    edo = fetch_edo_csv()
    if edo is None or edo.empty:
        targets["n_signals"] = targets["signals"].apply(
            lambda s: len([t for t in s.split("; ") if t]))
        targets = targets[targets["n_signals"] > 0]
        targets.round(3).to_csv("output/targets.csv", index=False)
        print("No ED&O data -- targets.csv rewritten with prior consent-order state cleared.")
        return

    edo["Issued Date"] = pd.to_datetime(edo["Issued Date"], errors="coerce")
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=CONSENT_LOOKBACK_YEARS)
    cd = edo[edo["Action Type"].str.contains("Cease and Desist", na=False)
             & (edo["Issued Date"] >= cutoff)].copy()
    cd["CERT"] = cd["Cert Number"].apply(first_cert)
    cd = cd.dropna(subset=["CERT", "Issued Date"])
    cd["CERT"] = cd["CERT"].astype(int)
    cd["is_termination"] = cd["Order Title"].fillna("").str.match(
        r"^\s*order terminating", flags=re.IGNORECASE)
    print(f"  Cease and Desist / Consent Orders (last {CONSENT_LOOKBACK_YEARS}yr): {len(cd):,} events")

    def per_bank(g):
        g = g.sort_values("Issued Date")
        issuing = g[~g["is_termination"]]
        if issuing.empty:
            return None
        last = g.iloc[-1]
        status = ("Terminated " + last["Issued Date"].strftime("%Y-%m-%d")
                  if last["is_termination"] else
                  "Active since " + issuing.iloc[-1]["Issued Date"].strftime("%Y-%m-%d"))
        return pd.Series({
            "consent_order_count": len(issuing),
            "consent_order_date": issuing.iloc[-1]["Issued Date"].strftime("%Y-%m-%d"),
            "consent_order_title": issuing.iloc[-1]["Order Title"],
            "consent_order_status": status,
        })

    agg = cd.groupby("CERT").apply(per_bank, include_groups=False).dropna(how="all").reset_index()
    print(f"  Banks with a consent order (matched to a CERT): {agg['CERT'].nunique():,}")

    # A consent order is concrete enough that a bank shouldn't be left off the
    # list just because no other signal happened to fire -- pull in any
    # matched CERT not already on targets.csv from the full scored universe
    # (all_banks.csv, built by 02_screen.py), same way 05_trajectory.py adds
    # banks whose trend alone qualifies them.
    new_certs = set(agg["CERT"]) - set(targets["CERT"])
    if new_certs:
        all_banks = pd.read_csv("output/all_banks.csv")
        new_rows = all_banks[all_banks["CERT"].isin(new_certs)].copy()
        new_rows["signals"] = new_rows["signals"].fillna("")
        targets = pd.concat([targets, new_rows], ignore_index=True, sort=False)
        print(f"  Added {len(new_rows):,} banks whose only signal is the consent order")

    m = targets.merge(agg, on="CERT", how="left")
    m["consent_order"] = m["consent_order_count"].fillna(0) >= 1

    def merge_row(r):
        extra = [k for k in CONSENTSERVICE if r[k]]
        sigs = [s for s in r["signals"].split("; ") if s] + extra
        score = int(r["score"]) + sum(CONSENTSERVICE[k][0] for k in extra)
        return pd.Series({"signals": "; ".join(sigs), "n_signals": len(sigs), "score": score})

    merged = m.apply(merge_row, axis=1)
    m["signals"], m["n_signals"], m["score"] = merged["signals"], merged["n_signals"], merged["score"]

    # A bank added in a prior run solely for its consent order drops back out
    # once that order ages past the lookback window and no other signal fired.
    m = m[m["n_signals"] > 0]
    m = m.sort_values(["score", "n_signals", "asset_musd"], ascending=False)
    m.round(3).to_csv("output/targets.csv", index=False)

    print(f"consent_order flagged: {int(m['consent_order'].sum()):,}")


if __name__ == "__main__":
    main()
