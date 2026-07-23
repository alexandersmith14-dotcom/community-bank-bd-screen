"""
06_edgar.py  --  Enrich target banks with SEC EDGAR officers/directors.

For the banks that are publicly traded, this matches the FDIC institution to its
SEC registrant (usually the holding company), confirms it's a bank, and pulls the
current board + named executive officers from recent Section 16 (Form 3/4/5)
filings -- which are structured XML, so the names are reliable.

Writes output/edgar_officers.json:
  { "<CERT>": {cik, ticker, sec_name, officers:[{name,title,role}], edgar, proxy} }

Honest scope: only *public* banks match (many community banks are private/mutual),
and Section 16 covers the board + principal officers (CEO/CFO/etc.), not every
functional head. Pairs with the dashboard's LinkedIn link, which finds the rest.
"""

import json
import re
import time
import requests
import pandas as pd

UA = {"User-Agent": "Community-Bank-BD-Screen alexandersmith14@gmail.com"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUB_URL = "https://data.sec.gov/submissions/CIK{:010d}.json"
ARCH = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

# Words stripped before comparing names; what's left is the "core".
SUFFIX = set("""bank banks national association na company co corp corporation inc
incorporated bancorp bancshares banshares financial finl group grp holdings holding
savings ssb fsb nb trust the of and & services service systems""".split())
# Distinctive-token requirement: a match must share a NON-generic token, so
# "First Bank" doesn't match every "First Bancorp" in the country.
GENERIC = set("""first national community citizens state peoples farmers merchants
commercial savings federal county valley heritage premier united american capital
central southern northern eastern western pacific atlantic home town city old new
security liberty independence pinnacle summit""".split())

SLEEP = 0.13


def core_tokens(name):
    toks = re.sub(r"[^a-z0-9 ]", " ", str(name).lower()).split()
    return [t for t in toks if t not in SUFFIX]


def build_sec_index(tickers):
    """distinctive-token -> list of (cik, ticker, name, core_set)."""
    idx = {}
    for row in tickers.values():
        name = row["title"]
        core = set(core_tokens(name))
        if not core:
            continue
        entry = (int(row["cik_str"]), row["ticker"], name, core)
        for t in core:
            idx.setdefault(t, []).append(entry)
    return idx


def match_bank(bank_name, sec_index):
    core = set(core_tokens(bank_name))
    distinctive = core - GENERIC
    if not distinctive:
        return None                      # too generic to match safely
    # candidates share every distinctive token with the bank
    cand = None
    seen = set()
    for t in distinctive:
        for e in sec_index.get(t, []):
            if e[0] in seen:
                continue
            seen.add(e[0])
            cik, ticker, name, sec_core = e
            if distinctive <= sec_core:          # bank's distinctive core is contained
                extra = len(sec_core - core)     # prefer the tightest superset
                if cand is None or extra < cand[0]:
                    cand = (extra, cik, ticker, name)
    return None if cand is None else cand[1:]    # (cik, ticker, name)


def confirm_and_fetch(cik):
    """Confirm the registrant is a bank and return (sic_ok, submissions json)."""
    r = requests.get(SUB_URL.format(cik), headers=UA, timeout=30)
    if r.status_code != 200:
        return False, None
    j = r.json()
    desc = (j.get("sicDescription") or "").lower()
    ok = any(w in desc for w in ("bank", "saving", "credit"))
    return ok, j


def extract_officers(cik, sub, max_filings=20):
    """Pull reporting owners (directors/officers) from recent Form 3/4/5 XML."""
    recent = sub["filings"]["recent"]
    forms = recent["form"]
    accs = recent["accessionNumber"]
    docs = recent["primaryDocument"]
    people = {}
    n = 0
    for form, acc, doc in zip(forms, accs, docs):
        if form not in ("3", "4", "5") or not doc.lower().endswith(".xml"):
            continue
        url = ARCH.format(cik=cik, acc=acc.replace("-", ""), doc=doc)
        try:
            xml = requests.get(url, headers=UA, timeout=30).text
        except Exception:
            continue
        time.sleep(SLEEP)
        name = re.search(r"<rptOwnerName>(.*?)</rptOwnerName>", xml, re.S)
        if not name:
            continue
        nm = re.sub(r"\s+", " ", name.group(1)).strip()
        title = re.search(r"<officerTitle>(.*?)</officerTitle>", xml, re.S)
        is_dir = re.search(r"<isDirector>\s*(1|true)\s*</isDirector>", xml, re.I)
        is_off = re.search(r"<isOfficer>\s*(1|true)\s*</isOfficer>", xml, re.I)
        if not (is_dir or is_off):
            continue                     # skip pure 10%-owner entities (funds)
        roles = []
        if is_off:
            roles.append("officer")
        if is_dir:
            roles.append("director")
        t = re.sub(r"\s+", " ", title.group(1)).strip() if title else ""
        # keep the richest record per person (one with a title wins)
        if nm not in people or (t and not people[nm]["title"]):
            people[nm] = {"name": nm, "title": t, "role": "/".join(roles) or "insider"}
        n += 1
        if n >= max_filings:
            break
    # names in filings are "LAST FIRST" — flip to "First Last" for readability
    out = []
    for p in people.values():
        parts = p["name"].split()
        if len(parts) >= 2:
            p = {**p, "name": " ".join(parts[1:] + parts[:1]).title()}
        out.append(p)
    # directors-with-a-title (execs) first, then other officers, then directors
    out.sort(key=lambda p: (0 if p["title"] else 1, p["name"]))
    return out[:15]


def main():
    print("Loading SEC ticker universe ...")
    tickers = requests.get(TICKERS_URL, headers=UA, timeout=30).json()
    time.sleep(SLEEP)
    sec_index = build_sec_index(tickers)

    banks = pd.read_csv("output/targets.csv")[["CERT", "NAME", "STALP"]].drop_duplicates("CERT")
    print(f"Target banks to check: {len(banks):,}")

    result, matched, public = {}, 0, 0
    for _, b in banks.iterrows():
        m = match_bank(b["NAME"], sec_index)
        if not m:
            continue
        matched += 1
        cik, ticker, sec_name = m
        try:
            ok, sub = confirm_and_fetch(cik)
        except Exception:
            ok, sub = False, None
        time.sleep(SLEEP)
        if not ok:
            continue
        public += 1
        officers = extract_officers(cik, sub)
        result[str(int(b["CERT"]))] = {
            "cik": cik, "ticker": ticker, "sec_name": sec_name,
            "officers": officers,
            "edgar": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&type=DEF+14A",
        }
        if public % 25 == 0:
            print(f"  ...{public} public banks enriched")

    with open("output/edgar_officers.json", "w") as f:
        json.dump(result, f)
    print(f"Name-matched: {matched:,}  |  confirmed public banks: {public:,}")
    print("Wrote output/edgar_officers.json")


if __name__ == "__main__":
    main()
