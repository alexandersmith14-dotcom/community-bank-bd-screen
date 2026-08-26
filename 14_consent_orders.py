"""
14_consent_orders.py  --  Formal enforcement actions (Cease & Desist /
Consent Orders / Formal Agreements) from all three primary bank regulators
-- FDIC, OCC, and the Federal Reserve -- merged into the bank target list.

Unlike every other signal in this pipeline, this one is not a modeled proxy
for risk -- it's ground truth: the bank is (or recently was) under an actual
formal enforcement order, which almost always comes with a court-ordered or
negotiated remediation mandate (independent BSA/AML testing, an enhanced
compliance program, board oversight reporting, etc). That's about as warm and
concrete a BD reason to call as exists in this whole tool.

Covering only FDIC's own actions would structurally miss 36% of the universe:
our institutions are REGAGNT FDIC/OCC/FED in roughly 64/20/16 proportions, and
FDIC's ED&O only lists FDIC-supervised (mostly state nonmember) banks. OCC
regulates national banks and federal savings associations; the Fed regulates
state member banks and their holding companies. So this pulls all three:

  FDIC (orders.fdic.gov, "ED&O")
    No public API -- a Salesforce Experience Cloud site whose "Download All"
    button triggers a Salesforce Aura action (`EDOSSearchForm.convertCSV`)
    generating a full CSV. Fetched via a real Playwright browser context
    (same approach as 11_state_licenses.py's Massachusetts leg). `Cert
    Number` ties directly to CERT. Active/terminated inferred from order-
    title text ("Order Terminating...") since ED&O has no status field.

  OCC (apps.occ.gov/EASearch)
    Also no public API, and also blocks plain HTTP clients outright (SSL
    handshake rejected for both `requests` and `curl` -- a WAF/bot-protection
    wall, confirmed, not a fluke) -- fetched via Playwright too. Unlike FDIC,
    OCC's results page is server-rendered HTML (no separate JSON API call
    observed), and every action has its own Start Date / Termination Date
    columns on one row -- cleaner than FDIC's separate issuance/termination
    order rows, no title-text inference needed. `Charter Number` in OCC's
    data is a DIFFERENT numbering system from FDIC's CERT, but FDIC's own
    `institutions` endpoint carries it as the `CHARTER` field (added to
    01_fetch.py's INST_FIELDS) -- a direct cross-reference, no fuzzy name
    matching. Scope: Action Type "C&D" (Cease & Desist) and "FA" (Formal
    Agreement, OCC's consent-order-equivalent for national banks).

  Federal Reserve (via OpenSanctions' `us_fed_enforcements` mirror -- the
  same source study/enforcement_study.py already uses for the *modeled*
  pre_enforcement signal, just never turned into a direct ground-truth flag
  until now)
    A plain CSV, no browser needed. No RSSD or charter cross-reference
    field exists in this dataset, so this is fuzzy-matched -- same
    core_name() + rapidfuzz pattern as 13_bank_events.py's `failures` leg.
    Two wrinkles specific to this source: (1) "Banking Organization" is
    often the HOLDING COMPANY, not the bank itself (e.g. "SNB Bancshares,
    Inc., Eufaula, Oklahoma, and Bank of Eufaula, Eufaula, Oklahoma"), so
    candidates are matched against both institutions' NAME and NAMEHCR
    (holding co name, also newly added to 01_fetch.py); (2) one row can
    name multiple entities joined by "and" or ";", so each row is split
    into candidate segments before matching. Scope: Action containing
    "Written Agreement" (the Fed's consent-order-equivalent), "Cease and
    Desist", or "Consent Order" -- excludes CMP-only, Section 19, and
    prohibition-from-banking actions (those are individual-focused anyway).

All three normalize to the same shape (CERT, start date, termination date,
title, source) and combine into one `consent_order` signal. A bank matched
in more than one source (shouldn't happen in practice -- each bank has one
primary regulator -- but handled safely if it does) has its order counts
summed and its most recent event's title/status shown.

Any source that fails to fetch (site down, UI changed, blocked) is skipped
independently -- wrapped in try/except like every state-licenses fetch in
11_state_licenses.py -- so one flaky regulator's site never kills the run
or the other two sources' data.

Unlike every other event-based signal in this pipeline, a consent order can
add a bank to the target list on its own (pulled in from the full scored
universe, all_banks.csv, same as 05_trajectory.py does for trend-only
banks) -- and it drops back off once the order ages past the lookback
window and no other signal fired.

Rewrites output/targets.csv in place, same pattern as 13_bank_events.py.
Idempotent: strips prior consent_order_* columns and appended signal+score
before recomputing.
"""

import io
import re
from urllib.parse import quote

import pandas as pd
from rapidfuzz import fuzz

CONSENT_LOOKBACK_YEARS = 5
MATCH_THRESHOLD = 88   # rapidfuzz token_sort_ratio, same threshold as 11_state_licenses.py / 13_bank_events.py

CONSENTSERVICE = {
    "consent_order": (26, "KR RAS: BSA/AML & Sanctions remediation, Internal Audit, independent testing -- under (or recently under) a formal enforcement order with a live compliance mandate"),
}

STATE_NAMES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut",
    "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
    "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan",
    "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina",
    "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
    "District of Columbia", "Puerto Rico", "Canada",
}


def core_name(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    s = re.sub(r"\b(inc|llc|corp|corporation|co|company|ltd|limited|the|bank|na|n a|"
               r"national association|bancshares|bancorp|holding|holdings|financial|group)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------- #
# FDIC (ED&O)
# --------------------------------------------------------------------------- #

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
        print(f"  FDIC ED&O: {len(df):,} total order records")
        return df
    except Exception as e:
        print(f"  FDIC ED&O fetch failed, skipping: {e}")
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


def fdic_agg(cutoff):
    edo = fetch_edo_csv()
    if edo is None or edo.empty:
        return pd.DataFrame(columns=["CERT", "consent_order_count", "consent_order_date",
                                      "consent_order_title", "consent_order_status"])

    edo["Issued Date"] = pd.to_datetime(edo["Issued Date"], errors="coerce")
    cd = edo[edo["Action Type"].str.contains("Cease and Desist", na=False)
             & (edo["Issued Date"] >= cutoff)].copy()
    cd["CERT"] = cd["Cert Number"].apply(first_cert)
    cd = cd.dropna(subset=["CERT", "Issued Date"])
    cd["CERT"] = cd["CERT"].astype(int)
    cd["is_termination"] = cd["Order Title"].fillna("").str.match(
        r"^\s*order terminating", flags=re.IGNORECASE)
    print(f"  FDIC: {len(cd):,} Cease and Desist / Consent Order events (last {CONSENT_LOOKBACK_YEARS}yr)")

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

    if cd.empty:
        return pd.DataFrame(columns=["CERT", "consent_order_count", "consent_order_date",
                                      "consent_order_title", "consent_order_status"])
    agg = cd.groupby("CERT").apply(per_bank, include_groups=False).dropna(how="all").reset_index()
    return agg


# --------------------------------------------------------------------------- #
# OCC (EASearch)
# --------------------------------------------------------------------------- #

def fetch_occ_actions(cutoff):
    try:
        from playwright.sync_api import sync_playwright
        start = cutoff.strftime("%m/%d/%Y")
        end = pd.Timestamp.now().strftime("%m/%d/%Y")
        url = ("https://apps.occ.gov/EASearch/Search/Table?q=&pg=0&pgsz=2000&view=Table"
               "&activeOnly=true&terminatedOnly=true&isAdv=true"
               f"&startDteMin={quote(start)}&startDteMax={quote(end)}")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, timeout=60000, wait_until="networkidle")
            html = page.content()
            browser.close()
        tables = pd.read_html(io.StringIO(html))
        df = next((t for t in tables if any("Charter Number" in str(c) for c in t.columns)), None)
        if df is None:
            print("  OCC fetch: results table not found (page layout may have changed), skipping")
            return None
        df.columns = ["Institution", "Charter", "Company", "Individual", "CityState",
                      "Type", "Amount", "StartDate", "StartDoc", "TermDate", "TermDoc",
                      "Docket", "SubjectMatters"][:len(df.columns)]
        df = df[df["Type"].isin(["C&D", "FA"])].copy()
        print(f"  OCC: {len(df):,} Cease & Desist / Formal Agreement records (last {CONSENT_LOOKBACK_YEARS}yr)")
        return df
    except Exception as e:
        print(f"  OCC fetch failed, skipping: {e}")
        return None


def occ_agg(cutoff, institutions):
    df = fetch_occ_actions(cutoff)
    cols = ["CERT", "consent_order_count", "consent_order_date", "consent_order_title", "consent_order_status"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    df["Charter"] = pd.to_numeric(df["Charter"], errors="coerce")
    df = df.dropna(subset=["Charter"])
    df["Charter"] = df["Charter"].astype(int)
    chart_map = institutions[institutions["CHARTER"] > 0][["CERT", "CHARTER"]].drop_duplicates("CHARTER")
    m = df.merge(chart_map, left_on="Charter", right_on="CHARTER", how="inner")
    if m.empty:
        return pd.DataFrame(columns=cols)

    m["StartDate"] = pd.to_datetime(m["StartDate"], errors="coerce")
    m["TermDate"] = pd.to_datetime(m["TermDate"], errors="coerce")
    m = m.dropna(subset=["CERT", "StartDate"])

    def per_bank(g):
        g = g.sort_values("StartDate")
        last = g.iloc[-1]
        status = ("Terminated " + last["TermDate"].strftime("%Y-%m-%d") if pd.notna(last["TermDate"])
                  else "Active since " + last["StartDate"].strftime("%Y-%m-%d"))
        return pd.Series({
            "consent_order_count": len(g),
            "consent_order_date": last["StartDate"].strftime("%Y-%m-%d"),
            "consent_order_title": last["Type"] + " (OCC)",
            "consent_order_status": status,
        })

    return m.groupby("CERT").apply(per_bank, include_groups=False).reset_index()


# --------------------------------------------------------------------------- #
# Federal Reserve (OpenSanctions mirror)
# --------------------------------------------------------------------------- #

FED_CSV = "https://data.opensanctions.org/datasets/latest/us_fed_enforcements/source.csv"


def fetch_fed_actions(cutoff):
    import requests
    try:
        r = requests.get(FED_CSV, timeout=60)
        r.raise_for_status()
        r.encoding = "utf-8-sig"
        df = pd.read_csv(io.StringIO(r.text), dtype=str)
        df.columns = [c.strip() for c in df.columns]
        df = df[df["Banking Organization"].notna()].copy()
        df["Effective Date"] = pd.to_datetime(df["Effective Date"], errors="coerce")
        mask = df["Action"].fillna("").str.contains(
            "Written Agreement|Cease and Desist|Consent Order", regex=True)
        df = df[mask & (df["Effective Date"] >= cutoff)]
        print(f"  Fed: {len(df):,} Written Agreement / Cease & Desist / Consent Order records (last {CONSENT_LOOKBACK_YEARS}yr)")
        return df
    except Exception as e:
        print(f"  Fed fetch failed, skipping: {e}")
        return None


def strip_city_state(seg):
    parts = [p.strip() for p in seg.split(",")]
    if len(parts) >= 3 and parts[-1] in STATE_NAMES:
        return ", ".join(parts[:-2])
    if len(parts) >= 2:
        return ", ".join(parts[:-1])
    return seg


def match_fed_to_cert(fed_df, institutions):
    name_pool = [(int(r["CERT"]), core_name(r["NAME"])) for _, r in institutions.iterrows()]
    name_pool += [(int(r["CERT"]), core_name(r["NAMEHCR"])) for _, r in institutions.iterrows()
                  if pd.notna(r.get("NAMEHCR"))]
    name_pool = [(c, n) for c, n in name_pool if len(n) >= 4]

    rows = []
    for _, row in fed_df.iterrows():
        segments = re.split(r"\s*;\s*|\s+and\s+", str(row["Banking Organization"]))
        for seg in segments:
            cand = core_name(strip_city_state(seg))
            if len(cand) < 4:
                continue
            best_cert, best_score = None, 0
            for cert, name in name_pool:
                if abs(len(name) - len(cand)) > 15:
                    continue
                score = fuzz.token_sort_ratio(cand, name)
                if score > best_score:
                    best_cert, best_score = cert, score
            if best_score >= MATCH_THRESHOLD:
                rows.append({"CERT": best_cert, "Effective Date": row["Effective Date"],
                             "Termination Date": row.get("Termination Date"), "Action": row["Action"]})
                break   # first good match on this row is enough
    return pd.DataFrame(rows)


def fed_agg(cutoff, institutions):
    cols = ["CERT", "consent_order_count", "consent_order_date", "consent_order_title", "consent_order_status"]
    fed = fetch_fed_actions(cutoff)
    if fed is None or fed.empty:
        return pd.DataFrame(columns=cols)

    m = match_fed_to_cert(fed, institutions)
    print(f"  Fed: matched {len(m):,} of {len(fed):,} records to a CERT")
    if m.empty:
        return pd.DataFrame(columns=cols)

    m["Effective Date"] = pd.to_datetime(m["Effective Date"], errors="coerce")
    m["Termination Date"] = pd.to_datetime(m["Termination Date"], errors="coerce")
    m = m.dropna(subset=["CERT", "Effective Date"])

    def per_bank(g):
        g = g.sort_values("Effective Date")
        last = g.iloc[-1]
        status = ("Terminated " + last["Termination Date"].strftime("%Y-%m-%d") if pd.notna(last["Termination Date"])
                  else "Active since " + last["Effective Date"].strftime("%Y-%m-%d"))
        return pd.Series({
            "consent_order_count": len(g),
            "consent_order_date": last["Effective Date"].strftime("%Y-%m-%d"),
            "consent_order_title": last["Action"] + " (Fed)",
            "consent_order_status": status,
        })

    return m.groupby("CERT").apply(per_bank, include_groups=False).reset_index()


# --------------------------------------------------------------------------- #
# Combine + merge into targets.csv
# --------------------------------------------------------------------------- #

def main():
    targets = pd.read_csv("output/targets.csv")
    institutions = pd.read_csv("data/institutions.csv")

    consent_cols = ["consent_order_count", "consent_order_date", "consent_order_title",
                     "consent_order_status", "consent_order_source"]
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

    cutoff = pd.Timestamp.now() - pd.DateOffset(years=CONSENT_LOOKBACK_YEARS)

    print("Fetching FDIC ED&O ...")
    a_fdic = fdic_agg(cutoff)
    a_fdic["consent_order_source"] = "FDIC"
    print("Fetching OCC EASearch ...")
    a_occ = occ_agg(cutoff, institutions)
    a_occ["consent_order_source"] = "OCC"
    print("Fetching Fed enforcement actions ...")
    a_fed = fed_agg(cutoff, institutions)
    a_fed["consent_order_source"] = "FED"

    combined = pd.concat([a_fdic, a_occ, a_fed], ignore_index=True)
    combined = combined.dropna(subset=["CERT"])
    if combined.empty:
        targets["n_signals"] = targets["signals"].apply(
            lambda s: len([t for t in s.split("; ") if t]))
        targets = targets[targets["n_signals"] > 0]
        targets.round(3).to_csv("output/targets.csv", index=False)
        print("No consent-order data from any source -- targets.csv rewritten with prior state cleared.")
        return

    combined["CERT"] = combined["CERT"].astype(int)
    combined["consent_order_date"] = pd.to_datetime(combined["consent_order_date"])

    def combine_sources(g):
        g = g.sort_values("consent_order_date")
        last = g.iloc[-1]
        return pd.Series({
            "consent_order_count": int(g["consent_order_count"].sum()),
            "consent_order_date": last["consent_order_date"].strftime("%Y-%m-%d"),
            "consent_order_title": last["consent_order_title"],
            "consent_order_status": last["consent_order_status"],
            "consent_order_source": "; ".join(sorted(set(g["consent_order_source"]))),
        })

    agg = combined.groupby("CERT").apply(combine_sources, include_groups=False).reset_index()
    print(f"Banks with a consent order across all regulators (matched to a CERT): {agg['CERT'].nunique():,}")

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
    if not agg.empty:
        print(agg["consent_order_source"].value_counts().to_string())


if __name__ == "__main__":
    main()
