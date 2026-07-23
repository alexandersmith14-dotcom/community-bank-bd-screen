"""
07_cu_fetch.py  --  Pull the credit-union universe from NCUA Call Report data.

Unlike FDIC (a JSON API with pre-computed ratios), NCUA publishes quarterly bulk
ZIPs of comma-delimited tables. This downloads the current and prior-year files,
reads the three tables we need straight from the zip, computes bank-comparable
ratios from the raw account codes, filters to >= $100M assets, and writes:
  data/cu_current.csv   identity + computed ratios (one row per credit union)
  data/cu_prior.csv     CU_NUMBER + assets one year earlier (for YoY growth)

Account codes were verified against the AcctDesc.txt dictionary in the zip.
NCUA reports dollars in actual dollars (not thousands); we convert to thousands
to match the FDIC scale so banks and credit unions share the same asset bands.
"""

import io
import zipfile
import requests
import pandas as pd

BASE = "https://ncua.gov/files/publications/analysis/call-report-data-{}.zip"
ASSET_FLOOR = 100_000_000   # $100M in actual dollars
QUARTER_MONTHS = ["03", "06", "09", "12"]

# Verified NCUA account codes (case normalized to upper on load).
A_ASSETS = "ACCT_010"        # total assets
A_NW = "ACCT_997"            # total net worth
A_LOANS = "ACCT_025B"        # total loans & leases
A_SHARES_DEP = "ACCT_018"    # total shares & deposits
A_DELINQ = "ACCT_041B"       # total delinquent loans (2+ months), $
A_CHARGEOFF = "ACCT_550"     # total loans charged off YTD
A_RECOVERY = "ACCT_551"      # total recoveries YTD
A_NONINT_EXP = "ACCT_671"    # total non-interest expense
A_NET_INCOME = "ACCT_661A"   # net income (loss) YTD
A_MEMBERS = "ACCT_083"       # number of current members


def latest_quarter():
    """Find the newest quarter whose NCUA zip is published."""
    import datetime
    y, m = datetime.date.today().year, datetime.date.today().month
    # walk back from the current quarter until a file exists
    q = (m - 1) // 3            # 0..3
    yq = [(y, QUARTER_MONTHS[q])]
    for _ in range(6):
        q -= 1
        if q < 0:
            q = 3
            y -= 1
        yq.append((y, QUARTER_MONTHS[q]))
    for yy, mm in yq:
        tag = f"{yy}-{mm}"
        if requests.head(BASE.format(tag), timeout=30).status_code == 200:
            return tag
    raise RuntimeError("no NCUA quarterly file found")


def prior_year(tag):
    y, mm = tag.split("-")
    return f"{int(y) - 1}-{mm}"


def read_zip_tables(tag, tables):
    """Download the quarter's zip and return {name: DataFrame} for `tables`."""
    r = requests.get(BASE.format(tag), timeout=120)
    r.raise_for_status()
    out = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in tables:
            with z.open(name) as f:
                df = pd.read_csv(f, dtype=str, low_memory=False)
                df.columns = df.columns.str.upper()
                out[name] = df
    return out


def num(s):
    return pd.to_numeric(s, errors="coerce")


def build_current(tag):
    t = read_zip_tables(tag, ["FOICU.txt", "FS220.txt", "FS220A.txt"])
    ident = t["FOICU.txt"][["CU_NUMBER", "CU_NAME", "CITY", "STATE"]].copy()
    fs, fsa = t["FS220.txt"], t["FS220A.txt"]

    cols_fs = [A_ASSETS, A_LOANS, A_SHARES_DEP, A_DELINQ, A_CHARGEOFF,
               A_RECOVERY, A_NONINT_EXP, A_MEMBERS]
    cols_fsa = [A_NW, A_NET_INCOME]
    d = ident
    for src, cols in [(fs, cols_fs), (fsa, cols_fsa)]:
        s = src[["CU_NUMBER"] + cols].copy()
        for c in cols:
            s[c] = num(s[c])
        d = d.merge(s, on="CU_NUMBER", how="left")

    d = d[d[A_ASSETS] >= ASSET_FLOOR].copy()
    assets = d[A_ASSETS]
    out = pd.DataFrame({
        "CU_NUMBER": d["CU_NUMBER"],
        "NAME": d["CU_NAME"].str.strip().str.title(),
        "CITY": d["CITY"].str.strip().str.title(),
        "STALP": d["STATE"],
        "ASSET": (assets / 1000).round(),                         # thousands, FDIC scale
        "NW_RATIO": (d[A_NW] / assets * 100),                     # net worth / assets %
        "DELINQ": (d[A_DELINQ] / d[A_LOANS] * 100),               # delinquent / loans %
        "NCO": ((d[A_CHARGEOFF] - d[A_RECOVERY]) / d[A_LOANS] * 100 * 4),  # annualized %
        "LOAN_TO_SHARE": (d[A_LOANS] / d[A_SHARES_DEP] * 100),
        "ROA": (d[A_NET_INCOME] * 4 / assets * 100),              # annualized %
        "EXP_RATIO": (d[A_NONINT_EXP] * 4 / assets * 100),        # non-int exp / assets %
        "MEMBERS": d[A_MEMBERS],
    })
    return out


def main():
    tag = latest_quarter()
    prior = prior_year(tag)
    print(f"NCUA current quarter: {tag}   prior-year: {prior}")

    cur = build_current(tag)
    cur.to_csv("data/cu_current.csv", index=False)
    print(f"  credit unions >= $100M: {len(cur):,}")

    pri_tables = read_zip_tables(prior, ["FS220.txt"])
    pri = pri_tables["FS220.txt"][["CU_NUMBER", A_ASSETS]].copy()
    pri[A_ASSETS] = num(pri[A_ASSETS])
    pri = pri[pri[A_ASSETS] > 0]
    pri["ASSET_PRIOR"] = (pri[A_ASSETS] / 1000).round()
    pri[["CU_NUMBER", "ASSET_PRIOR"]].to_csv("data/cu_prior.csv", index=False)
    print(f"  prior-year rows: {len(pri):,}")

    with open("data/cu_repdte.txt", "w") as f:
        f.write(tag)
    print("Done.")


if __name__ == "__main__":
    main()
