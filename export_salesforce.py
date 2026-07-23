"""
export_salesforce.py  --  Flatten the target lists into one Salesforce-ready CSV.

Reads the three target files (banks / credit unions / fintechs) plus the EDGAR
officers, and writes output/salesforce_import.csv: one row per institution, with
plain columns that map to Salesforce Account (or Lead) fields, and a self-
contained Description so the "why" survives even without custom fields.

Sorted best-first within each type. Import it with Salesforce's Data Import
Wizard (see SALESFORCE_IMPORT.md).
"""

import json
import os
import re
import pandas as pd

SIGLAB = {
    "excess_capital": "Excess capital", "credit_deterioration": "Credit deterioration",
    "under_reserved": "Under-reserved", "weak_efficiency": "Weak efficiency",
    "funding_liquidity": "Funding/liquidity", "rapid_growth": "Rapid growth",
    "near_10b_threshold": "Approaching $10B", "near_fdicia_1b": "Near $1B (FDICIA)",
    "near_500m_audit": "Crossed $500M (CU audit)", "weak_profitability": "Weak profitability",
    "bsa_aml_scaling": "BSA/AML scaling", "capital_building": "Capital building (trend)",
    "credit_turning": "Credit turning (trend)", "growth_accelerating": "Growth accelerating (trend)",
    "runway_to_10b": "Runway to $10B (trend)", "margin_eroding": "Margin eroding (trend)",
    "ft_national": "National money transmitter", "ft_fullstack": "Full payments stack",
    "ft_multistate": "Multistate transmitter", "ft_prepaid": "Prepaid access",
    "ft_fx_crypto": "FX / crypto",
}
SIGSVC = {
    "near_10b_threshold": "$10B readiness (CFPB, Internal Audit, FDICIA ICFR)",
    "near_fdicia_1b": "FDICIA Part 363 ICFR attestation readiness",
    "near_500m_audit": "NCUA Part 715 CPA financial-statement audit",
    "bsa_aml_scaling": "BSA/AML program enhancement + independent testing",
    "rapid_growth": "BSA/AML scaling, Internal Audit, risk assessment",
    "growth_accelerating": "BSA/AML scaling + Internal Audit (growth outpacing controls)",
    "credit_deterioration": "Internal Audit loan review + CECL model validation",
    "credit_turning": "Early Internal Audit loan review + CECL validation",
    "under_reserved": "CECL model validation / reserve adequacy",
    "weak_efficiency": "Robotic Process Automation + Internal Audit",
    "funding_liquidity": "Internal Audit of liquidity/funding controls",
    "excess_capital": "Refer: capital deployment / M&A (other KR practice)",
    "capital_building": "Refer: capital deployment / M&A (other KR practice)",
    "weak_profitability": "Refer: earnings / margin advisory (other KR practice)",
    "margin_eroding": "RPA cost automation (partial)",
    "ft_national": "BSA/AML program + testing; multistate MTL licensing",
    "ft_fullstack": "Enterprise BSA/AML, testing, SOC/audit",
    "ft_multistate": "BSA/AML + state MTL compliance",
    "ft_prepaid": "BSA/AML + FinCEN prepaid rule; consumer compliance",
    "ft_fx_crypto": "BSA/AML for virtual currency / FX; OFAC",
}
LD_TITLES = {
    "Bank": '"Chief Executive Officer" OR "President" OR "BSA Officer" OR "Chief Risk Officer" OR "Chief Audit Executive"',
    "Credit Union": '"Chief Executive Officer" OR "President" OR "BSA Officer" OR "Chief Compliance Officer" OR "Supervisory Committee"',
    "Fintech": '"BSA Officer" OR "Chief Compliance Officer" OR "Chief Risk Officer" OR "General Counsel" OR "Chief Executive Officer"',
}


def sigs(s):
    return [x for x in str(s).split("; ") if x] if pd.notnull(s) else []


def linkedin(name, itype):
    kw = f'"{name}" ({LD_TITLES[itype]})'
    from urllib.parse import quote
    return "https://www.linkedin.com/search/results/people/?keywords=" + quote(kw)


def bank_metrics(r):
    p = []
    if pd.notnull(r.get("EQV")): p.append(f"equity/assets {r['EQV']:.1f}%")
    if pd.notnull(r.get("ROA")): p.append(f"ROA {r['ROA']:.2f}%")
    if pd.notnull(r.get("EEFFR")): p.append(f"efficiency {r['EEFFR']:.0f}%")
    if pd.notnull(r.get("NCLNLSR")): p.append(f"net charge-offs {r['NCLNLSR']:.2f}%")
    if pd.notnull(r.get("asset_musd")): p.append(f"assets ${r['asset_musd']/1000:.1f}B")
    return "; ".join(p)


def cu_metrics(r):
    p = []
    if pd.notnull(r.get("NW_RATIO")): p.append(f"net worth {r['NW_RATIO']:.1f}%")
    if pd.notnull(r.get("ROA")): p.append(f"ROA {r['ROA']:.2f}%")
    if pd.notnull(r.get("DELINQ")): p.append(f"delinquency {r['DELINQ']:.2f}%")
    if pd.notnull(r.get("LOAN_TO_SHARE")): p.append(f"loan/share {r['LOAN_TO_SHARE']:.0f}%")
    if pd.notnull(r.get("asset_musd")): p.append(f"assets ${r['asset_musd']/1000:.1f}B")
    return "; ".join(p)


def ft_metrics(r):
    p = [f"{int(r['FT_STATES'])} states of MSB activity"]
    if str(r.get("FT_ACTIVITIES")): p.append(str(r["FT_ACTIVITIES"]))
    return "; ".join(p)


def main():
    edgar = {}
    if os.path.exists("output/edgar_officers.json"):
        edgar = json.load(open("output/edgar_officers.json"))

    rows = []
    files = [("Bank", "output/targets.csv"), ("Credit Union", "output/cu_targets.csv"),
             ("Fintech", "output/ft_targets.csv")]
    for itype, path in files:
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        for _, r in df.iterrows():
            sg = sigs(r["signals"])
            labels = "; ".join(SIGLAB.get(x, x) for x in sg)
            services = "; ".join(dict.fromkeys(SIGSVC.get(x, "") for x in sg if SIGSVC.get(x)))
            if itype == "Bank":
                metrics = bank_metrics(r)
            elif itype == "Credit Union":
                metrics = cu_metrics(r)
            else:
                metrics = ft_metrics(r)

            cert = r.get("CERT")
            eg = edgar.get(str(int(cert))) if itype == "Bank" and pd.notnull(cert) else None
            ticker = eg["ticker"] if eg else ""
            officers = "; ".join(f"{o['name']} ({o['title'] or o['role']})"
                                 for o in (eg["officers"] if eg else [])[:5])
            known = " [known fintech]" if (itype == "Fintech" and r.get("FT_KNOWN")) else ""

            n = int(r["n_signals"])
            if itype == "Fintech":
                # Signal count isn't a quality signal for fintechs (shells stack
                # signals too); the verified "known" flag is what matters.
                priority = "Hot" if known else "Cool"
            else:
                priority = "Hot" if n >= 3 else "Warm" if n == 2 else "Cool"
            assets = f"{r['asset_musd']/1000:.2f}" if pd.notnull(r.get("asset_musd")) else ""
            regid = ("FDIC CERT " + str(int(cert))) if itype == "Bank" else \
                    ("NCUA " + str(int(cert))) if itype == "Credit Union" else "FinCEN MSB"

            desc = (f"{itype}{known} in {r.get('CITY','')}, {r.get('STALP','')}. "
                    f"Priority {priority}. Flagged for: {labels}. "
                    f"KR RAS opportunities: {services}. "
                    f"Key metrics: {metrics}.")
            if ticker:
                desc += f" Public ({ticker}); board/execs: {officers}."

            rows.append({
                "Institution Name": r.get("NAME", ""),
                "Institution Type": itype,
                "Priority": priority,
                "Priority Score": int(r["score"]),
                "Signals (count)": n,
                "State": r.get("STALP", ""),
                "City": r.get("CITY", ""),
                "Assets ($B)": assets,
                "KR RAS Services": services,
                "Signals": labels,
                "Key Metrics": metrics,
                "Public Ticker": ticker,
                "Board / Executives (SEC)": officers,
                "LinkedIn Decision-Maker Search": linkedin(r.get("NAME", ""), itype),
                "Regulator ID": regid,
                "Description": desc,
            })

    out = pd.DataFrame(rows)
    order = {"Hot": 0, "Warm": 1, "Cool": 2}
    out["_p"] = out["Priority"].map(order)
    out = out.sort_values(["Institution Type", "_p", "Priority Score"],
                          ascending=[True, True, False]).drop(columns="_p")
    out.to_csv("output/salesforce_import.csv", index=False)
    print(f"Wrote output/salesforce_import.csv  ({len(out):,} rows)")
    print(out.groupby(["Institution Type", "Priority"]).size())


if __name__ == "__main__":
    main()
