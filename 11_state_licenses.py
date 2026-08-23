"""
11_state_licenses.py  --  Cross-check fintech targets against real state money-
transmitter licensee rosters, as a counterweight to FinCEN's self-reported MSB
list (see the HONEST CAVEAT in 09_fintech.py -- shells and real companies look
identical there).

State money-transmitter licensing is real regulatory approval (background
checks, bonding, financial review), so a name match here is a much stronger
"this is a real company" signal than the curated KNOWN_FINTECHS name list.

COVERAGE, NOT COMPLETENESS: only 5 states publish a real bulk/machine-readable
roster; the other ~41 only offer NMLS Consumer Access, which has no bulk/API
access and an explicit Terms of Use ban on bulk copying -- not scraped here.
So the flag below means "confirmed licensed in at least one of these 5 states,"
never "not licensed anywhere" for a company that doesn't match.

Sources (checked by hand, 2026-08-22):
  FL  real.flofr.com          zipped CSV, ~6,100 rows, all statuses ever issued
  NC  nccob.gov                server-rendered HTML table (Cloudflare-protected;
                                intermittently returns a JS challenge -- skip on
                                failure rather than fight it)
  MS  dbcf.ms.gov               PDF, fixed text columns (Company Id/Name/Street/
                                City/ST/ZIP)
  AK  commerce.alaska.gov       PDF, multi-line records (name row + wrapped
                                address rows); URL is dated and will go stale --
                                update it when this starts returning 404s
  MA  mass.gov                  XLSX; the download page is a JS SPA and the file
                                URL itself 403s to a plain HTTP request, so this
                                needs a real (Playwright) browser context

Writes output/state_licenses.csv (raw, one row per licensee) and merges into
output/ft_targets.csv as ft_state_verified + FT_STATE_LICENSES.
"""

import io
import re
import time
import zipfile
import pandas as pd
import requests
from rapidfuzz import fuzz

UA = {"User-Agent": "Mozilla/5.0 (compatible; Community-Bank-BD-Screen research)"}
TIMEOUT = 60
MATCH_THRESHOLD = 88   # rapidfuzz token_sort_ratio; company legal-name suffixes vary


def fetch_fl():
    r = requests.get("https://real.flofr.com/Public/MT/Money_Transmitters_monthly.zip",
                      headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    with z.open("Money_Transmitters_monthly.csv") as f:
        df = pd.read_csv(f, dtype=str, encoding="latin-1",
                          on_bad_lines="skip", engine="python")
    df = df[df["STATUS"] == "Approved"]
    return pd.DataFrame({
        "SRC_STATE": "FL",
        "COMPANY": df["FIRM NAME"].str.strip(),
        "ADDRESS": df["PRIM ADDRESS 1"].fillna("").str.strip(),
        "CITY": df["PRIM CITY"].fillna("").str.strip(),
        "STALP": df["PRIM STATE"].fillna("").str.strip(),
        "ZIP": df["PRIM ZIP"].fillna("").str.strip(),
    })


def fetch_nc():
    r = requests.get("https://www.nccob.gov/Online/MTS/MTSCompanyListing.aspx",
                      headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    if "Just a moment" in r.text or "challenge-platform" in r.text:
        raise RuntimeError("Cloudflare challenge page, not the real listing")
    tables = pd.read_html(io.StringIO(r.text), attrs={"id": "tblresults"}, header=0)
    df = tables[0]
    df.columns = [str(c).strip() for c in df.columns]
    addr = df["Address"].fillna("")
    # "street, city, ST, zip" -- split from the right so multi-word streets survive
    parts = addr.str.rsplit(",", n=3, expand=True)
    return pd.DataFrame({
        "SRC_STATE": "NC",
        "COMPANY": df["Company Name"].str.strip(),
        "ADDRESS": parts[0].str.strip() if 0 in parts else "",
        "CITY": parts[1].str.strip() if 1 in parts else "",
        "STALP": parts[2].str.strip() if 2 in parts else "",
        "ZIP": parts[3].str.strip() if 3 in parts else "",
    })


def fetch_ms():
    r = requests.get(
        "https://dbcf.ms.gov/wp-content/uploads/2024/10/Money-Transmitter-Licensee-list-for-Website-09302024.pdf",
        headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    import pdfplumber
    pdf = pdfplumber.open(io.BytesIO(r.content))
    # Fixed text columns (verified 2026-08-22): Id<182<=Name<546<=Street<922<=City<1034<=ST<1085<=ZIP
    bounds = [("COMPANY", 182, 546), ("ADDRESS", 546, 922), ("CITY", 922, 1034),
              ("STALP", 1034, 1085), ("ZIP", 1085, 9999)]
    rows = []
    for page in pdf.pages:
        by_row = {}
        for w in page.extract_words():
            by_row.setdefault(round(w["top"]), []).append(w)
        for top, words in by_row.items():
            if not any(w["text"].isdigit() and len(w["text"]) >= 5 for w in words if w["x0"] < 182):
                continue   # header/section rows have no leading Company Id
            rec = {}
            for name, lo, hi in bounds:
                toks = [w["text"] for w in words if lo <= w["x0"] < hi]
                rec[name] = " ".join(toks)
            if rec["COMPANY"]:
                rows.append(rec)
    df = pd.DataFrame(rows)
    df.insert(0, "SRC_STATE", "MS")
    return df


def fetch_ak():
    url = "https://www.commerce.alaska.gov/web/Portals/3/pub/MSB%20Roster%2020260319.pdf"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    import pdfplumber
    pdf = pdfplumber.open(io.BytesIO(r.content))
    KNOWN_HEADERS = {"money transmitter", "currency exchange", "check casher",
                     "money order", "stored value", "filing description"}
    rows, current = [], None
    for page in pdf.pages:
        by_row = {}
        for w in page.extract_words():
            by_row.setdefault(round(w["top"]), []).append(w)
        for top in sorted(by_row):
            words = sorted(by_row[top], key=lambda w: w["x0"])
            name_zone = " ".join(w["text"] for w in words if w["x0"] < 300)
            addr_zone = " ".join(w["text"] for w in words if 380 <= w["x0"] < 580)
            filenum = next((w["text"] for w in words if w["x0"] >= 680 and re.match(r"^\d{5,}$", w["text"])), None)
            if name_zone and name_zone.strip().lower() not in KNOWN_HEADERS and filenum is None and addr_zone == "":
                if current:
                    rows.append(current)
                current = {"COMPANY": name_zone.strip(), "ADDRESS": ""}
            elif current and addr_zone:
                current["ADDRESS"] = (current["ADDRESS"] + " " + addr_zone).strip()
            if filenum and current:
                rows.append(current)
                current = None
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df.insert(0, "SRC_STATE", "AK")
    df["CITY"] = ""
    df["STALP"] = ""
    df["ZIP"] = ""
    return df


def fetch_ma():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://www.mass.gov/lists/download-a-list-of-approved-licensees",
                   timeout=45000, wait_until="networkidle")
        resp = ctx.request.get("https://www.mass.gov/doc/money-transmitter-licensee-list/download")
        body = resp.body()
        browser.close()
    df = pd.read_excel(io.BytesIO(body), header=1)
    df.columns = [str(c).strip() for c in df.columns]
    name_col = next((c for c in df.columns if "name" in c.lower()), df.columns[0])
    addr_col = next((c for c in df.columns if "address" in c.lower()), None)
    city_col = next((c for c in df.columns if "city" in c.lower()), None)
    st_col = next((c for c in df.columns if c.lower() in ("state", "st")), None)
    zip_col = next((c for c in df.columns if "zip" in c.lower()), None)
    return pd.DataFrame({
        "SRC_STATE": "MA",
        "COMPANY": df[name_col].astype(str).str.strip(),
        "ADDRESS": df[addr_col].astype(str).str.strip() if addr_col else "",
        "CITY": df[city_col].astype(str).str.strip() if city_col else "",
        "STALP": df[st_col].astype(str).str.strip() if st_col else "",
        "ZIP": df[zip_col].astype(str).str.strip() if zip_col else "",
    })


FETCHERS = [("FL", fetch_fl), ("NC", fetch_nc), ("MS", fetch_ms),
            ("AK", fetch_ak), ("MA", fetch_ma)]


def core_name(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    s = re.sub(r"\b(inc|llc|corp|corporation|co|company|ltd|limited|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_state_licenses(ft, licenses):
    lic_names = licenses["COMPANY"].apply(core_name)
    lic_lookup = list(zip(lic_names, licenses["SRC_STATE"]))
    lic_lookup = [(n, s) for n, s in lic_lookup if len(n) >= 4]

    verified, matched_states = [], []
    for legal, dba in zip(ft["NAME"].fillna(""), ft["FT_DBA"].fillna("")):
        candidates = {core_name(legal), core_name(dba)} - {""}
        found = set()
        for cand in candidates:
            if len(cand) < 4:
                continue
            for lic_name, st in lic_lookup:
                if abs(len(lic_name) - len(cand)) > 15:
                    continue
                if fuzz.token_sort_ratio(cand, lic_name) >= MATCH_THRESHOLD:
                    found.add(st)
        verified.append(bool(found))
        matched_states.append("; ".join(sorted(found)))
    return verified, matched_states


def main():
    frames = []
    for state, fn in FETCHERS:
        try:
            df = fn()
            print(f"  {state}: {len(df):,} licensees")
            frames.append(df)
        except Exception as e:
            print(f"  {state}: SKIPPED ({e})")
        time.sleep(0.5)

    if not frames:
        print("No state sources succeeded -- nothing to merge.")
        return

    licenses = pd.concat(frames, ignore_index=True)
    licenses.to_csv("output/state_licenses.csv", index=False)
    print(f"Total state-licensee rows: {len(licenses):,}")

    ft = pd.read_csv("output/ft_targets.csv")

    # Idempotent: this script both reads and writes ft_targets.csv, so undo any
    # ft_state_verified left over from a prior run before reapplying it -- else
    # a rerun double-counts the score bump and duplicates the signal string.
    if "ft_state_verified" in ft.columns:
        had = ft["ft_state_verified"].fillna(False).astype(bool)
        ft.loc[had, "score"] -= 12
        ft["signals"] = ft["signals"].apply(
            lambda s: "; ".join(x for x in str(s).split("; ") if x and x != "ft_state_verified"))
        ft = ft.drop(columns=["ft_state_verified", "FT_STATE_LICENSES"])

    print("Matching fintech targets against state rosters ...")
    verified, matched_states = match_state_licenses(ft, licenses)
    ft["ft_state_verified"] = verified
    ft["FT_STATE_LICENSES"] = matched_states
    n_verified = sum(verified)
    print(f"State-verified: {n_verified:,} / {len(ft):,} fintech targets")

    ft.loc[ft["ft_state_verified"], "score"] += 12
    ft["signals"] = ft.apply(
        lambda r: (r["signals"] + "; ft_state_verified") if r["ft_state_verified"] else r["signals"],
        axis=1)
    ft["n_signals"] = ft["signals"].apply(lambda s: len([x for x in str(s).split("; ") if x]))
    ft = ft.sort_values(["score", "FT_STATES"], ascending=False)
    ft.to_csv("output/ft_targets.csv", index=False)
    print("Updated output/ft_targets.csv with ft_state_verified.")


if __name__ == "__main__":
    main()
