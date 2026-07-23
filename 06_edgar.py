"""
06_edgar.py  --  Enrich target banks with SEC EDGAR officers/directors.

For publicly traded banks, matches the FDIC institution to its SEC registrant
(name normalization + bank-SIC confirmation) and pulls a few board/executive
names from recent Section 16 (Form 3/4/5) filings (structured XML => reliable).

Robustness (learned the hard way): SEC throttles above ~10 req/s, so we cap the
rate, use hard connect+read timeouts so nothing can hang, fetch only a handful
of filings per bank, and CHECKPOINT results every N banks. Combined with the
incremental cache, a re-run resumes instead of starting over.

Writes output/edgar_officers.json and output/edgar_checked.json (the cache).
Delete edgar_checked.json to force a full refresh (e.g. a new quarter).
Scope: public banks only; Section 16 = board + principal officers, not every
functional head -- pairs with the dashboard's LinkedIn link.
"""

import json
import os
import re
import time
import requests
import pandas as pd

OFFICERS_FILE = "output/edgar_officers.json"
CHECK_CACHE = "output/edgar_checked.json"

UA = {"User-Agent": "Community-Bank-BD-Screen alexandersmith14@gmail.com"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUB_URL = "https://data.sec.gov/submissions/CIK{:010d}.json"
ARCH = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

SLEEP = 0.20            # ~5 req/s, safely under SEC's 10/s limit
TIMEOUT = (5, 15)       # (connect, read) seconds -- nothing can hang
MAX_FILINGS = 6         # recent Form 3/4/5 to scan per public bank
CHECKPOINT_EVERY = 50   # save progress this often

SUFFIX = set("""bank banks national association na company co corp corporation inc
incorporated bancorp bancshares banshares financial finl group grp holdings holding
savings ssb fsb nb trust the of and & services service systems""".split())
GENERIC = set("""first national community citizens state peoples farmers merchants
commercial savings federal county valley heritage premier united american capital
central southern northern eastern western pacific atlantic home town city old new
security liberty independence pinnacle summit""".split())

SESSION = requests.Session()
SESSION.headers.update(UA)


def sget(url):
    """Rate-limited GET with hard timeouts; returns Response or None."""
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        time.sleep(SLEEP)
        return r if r.status_code == 200 else None
    except Exception:
        time.sleep(SLEEP)
        return None


def core_tokens(name):
    toks = re.sub(r"[^a-z0-9 ]", " ", str(name).lower()).split()
    return [t for t in toks if t not in SUFFIX]


def build_sec_index(tickers):
    idx = {}
    for row in tickers.values():
        core = set(core_tokens(row["title"]))
        if not core:
            continue
        entry = (int(row["cik_str"]), row["ticker"], row["title"], core)
        for t in core:
            idx.setdefault(t, []).append(entry)
    return idx


def match_bank(bank_name, sec_index):
    core = set(core_tokens(bank_name))
    distinctive = core - GENERIC
    if not distinctive:
        return None
    cand, seen = None, set()
    for t in distinctive:
        for e in sec_index.get(t, []):
            if e[0] in seen:
                continue
            seen.add(e[0])
            cik, ticker, name, sec_core = e
            if distinctive <= sec_core:
                extra = len(sec_core - core)
                if cand is None or extra < cand[0]:
                    cand = (extra, cik, ticker, name)
    return None if cand is None else cand[1:]


def confirm_and_fetch(cik):
    r = sget(SUB_URL.format(cik))
    if r is None:
        return False, None
    try:
        j = r.json()
    except Exception:
        return False, None
    desc = (j.get("sicDescription") or "").lower()
    return any(w in desc for w in ("bank", "saving", "credit")), j


def extract_officers(cik, sub):
    recent = sub["filings"]["recent"]
    forms, accs, docs = recent["form"], recent["accessionNumber"], recent["primaryDocument"]
    people, n = {}, 0
    for form, acc, doc in zip(forms, accs, docs):
        if form not in ("3", "4", "5") or not doc.lower().endswith(".xml"):
            continue
        r = sget(ARCH.format(cik=cik, acc=acc.replace("-", ""), doc=doc))
        n += 1
        if r is not None:
            xml = r.text
            nm = re.search(r"<rptOwnerName>(.*?)</rptOwnerName>", xml, re.S)
            if nm:
                is_dir = re.search(r"<isDirector>\s*(1|true)\s*</isDirector>", xml, re.I)
                is_off = re.search(r"<isOfficer>\s*(1|true)\s*</isOfficer>", xml, re.I)
                if is_dir or is_off:
                    name = re.sub(r"\s+", " ", nm.group(1)).strip()
                    title = re.search(r"<officerTitle>(.*?)</officerTitle>", xml, re.S)
                    t = re.sub(r"\s+", " ", title.group(1)).strip() if title else ""
                    roles = ("officer" if is_off else "") + ("/director" if is_dir else "")
                    if name not in people or (t and not people[name]["title"]):
                        people[name] = {"name": name, "title": t, "role": roles.strip("/")}
        if n >= MAX_FILINGS:
            break
    out = []
    for p in people.values():
        parts = p["name"].split()
        if len(parts) >= 2:
            p = {**p, "name": " ".join(parts[1:] + parts[:1]).title()}
        out.append(p)
    out.sort(key=lambda p: (0 if p["title"] else 1, p["name"]))
    return out[:12]


def save(result, checked):
    with open(OFFICERS_FILE, "w") as f:
        json.dump(result, f)
    with open(CHECK_CACHE, "w") as f:
        json.dump(sorted(checked), f)


def main():
    print("Loading SEC ticker universe ...", flush=True)
    tickers = SESSION.get(TICKERS_URL, timeout=TIMEOUT).json()
    time.sleep(SLEEP)
    sec_index = build_sec_index(tickers)

    banks = pd.read_csv("output/targets.csv")[["CERT", "NAME"]].drop_duplicates("CERT")
    banks = banks[banks["CERT"].notna()]
    print(f"Target banks to check: {len(banks):,}", flush=True)

    existing = json.load(open(OFFICERS_FILE)) if os.path.exists(OFFICERS_FILE) else {}
    checked = set(json.load(open(CHECK_CACHE))) if os.path.exists(CHECK_CACHE) else set()

    result = {}
    scanned = public = new = 0
    for _, b in banks.iterrows():
        cs = str(int(b["CERT"]))
        if cs in checked:
            if cs in existing:
                result[cs] = existing[cs]
            continue
        scanned += 1
        new += 1
        checked.add(cs)
        m = match_bank(b["NAME"], sec_index)
        if m:
            cik, ticker, sec_name = m
            ok, sub = confirm_and_fetch(cik)
            if ok:
                public += 1
                result[cs] = {
                    "cik": cik, "ticker": ticker, "sec_name": sec_name,
                    "officers": extract_officers(cik, sub),
                    "edgar": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&type=DEF+14A",
                }
        if scanned % CHECKPOINT_EVERY == 0:
            save(result, checked)
            print(f"  scanned {scanned:,} new | public so far {public:,} (checkpointed)", flush=True)

    save(result, checked)
    print(f"Done. Newly scanned: {new:,} | public in file: {len(result):,}", flush=True)


if __name__ == "__main__":
    main()
