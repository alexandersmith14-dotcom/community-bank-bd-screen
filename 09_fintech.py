"""
09_fintech.py  --  Build a fintech (money-transmitter / prepaid) target list.

Source: the FinCEN MSB registrant list (the authoritative federal registry of
money services businesses), mirrored weekly by OpenSanctions as a clean TSV.
Fintech universe = US money transmitters (activity 409) and prepaid-access
providers (413/414) -- the payments/lending fintechs with real BSA/AML burden.

HONEST CAVEAT: FinCEN registration is self-reported and cheap, so real digital
fintechs (PayPal, Stripe, Coinbase, Chime...) and shell registrations look
structurally identical (branches=0, "all 50 states"). We can't fully separate
them programmatically, so scoring favors the full payments stack (money
transmitter + prepaid), which is a better real-fintech indicator, and the
dashboard's name search lets you pull specific known targets. Treat this as a
filterable regulatory database, not a pre-cleaned ranked list.

Writes output/ft_targets.csv (INST_TYPE=Fintech, shared schema + FT_ columns).
"""

import io
import re
import requests
import pandas as pd

# Curated recognizable fintechs (payments, neobanks/BaaS, lending, crypto,
# remittance). FinCEN can't separate real digital fintechs from shells by data,
# but the real ones are known by name -- matching these floats them to the top
# as the "quality flag", while the full registry stays name-searchable beneath.
KNOWN_FINTECHS = [
    # Distinctive names only. Common-word brands (Current, Wise, Square, Ramp,
    # Dave, Novo, Mercury, Prosper, Toast, Unit, Bond, Divvy...) are pinned to a
    # multi-word form or dropped, because bare words match shells. Extra names
    # that aren't registered MSBs simply never match -- harmless.
    # --- Payments / processing ---
    "PayPal", "Stripe Payments", "Stripe Inc", "Adyen", "Braintree", "Marqeta",
    "Dwolla", "Modern Treasury", "Payoneer", "Checkout.com", "GoCardless",
    "Rapyd", "Airwallex", "Nium", "Currencycloud", "Shift4", "Toast Inc",
    "Bill.com", "Melio", "Plaid", "Finix", "Paystand", "Highnote", "Lithic",
    "Moov Financial", "Tabapay", "Priority Technology", "Sila Money", "Astra Finance",
    "Payabli", "Fiserv", "Worldpay", "Nuvei", "Paysafe", "Bluesnap",
    # --- Remittance / cross-border ---
    "Remitly", "WorldRemit", "Wise US", "Xoom", "MoneyGram", "Sendwave",
    "Pangea Money", "Boss Revolution", "dLocal", "EBANX", "Sunrise Banks",
    # --- Neobanks / BaaS ---
    "Chime", "Varo Bank", "Varo Money", "MoneyLion", "SoFi", "Brex",
    "Ramp Payments", "Ramp Business", "Bluevine", "Green Dot", "Netspend",
    "Mercury Technologies", "Dave Inc", "Cash App", "Venmo",
    # --- Lending / BNPL ---
    "Affirm", "Klarna", "Afterpay", "Sezzle", "Zip Co", "Upstart", "LendingClub",
    "Prosper Marketplace", "Avant", "OppFi", "Best Egg", "Kabbage", "OnDeck",
    "Fundbox", "Enova", "Figure Technolog", "Blend Labs", "Petal Card",
    "Mission Lane", "Oportun", "Possible Financial", "Splash Financial",
    # --- Crypto / digital assets ---
    "Coinbase", "Kraken", "Gemini Trust", "Paxos", "BitPay", "Circle Internet",
    "Anchorage Digital", "Fireblocks", "BitGo", "Bakkt", "Robinhood", "Ripple",
    "Strike", "MoonPay", "Bitso", "Blockchain.com", "Coinme", "Prime Trust",
    "Zero Hash", "Fortress Trust", "Uphold",
    # --- Spend / payroll / expense ---
    "Expensify", "Deel", "Papaya Global", "Rippling", "Gusto", "Justworks",
    "Remote.com", "Emburse", "Airbase",
    # --- International neobanks ---
    "Revolut", "Monzo", "Nubank", "MercadoPago", "Wealthsimple",
]
KNOWN_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in KNOWN_FINTECHS) + r")\b", re.I)

SRC = "https://data.opensanctions.org/datasets/latest/us_fincen_msb/source.tsv"

US_STATES = set("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA
MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV
WI WY DC""".split())

ACT = {
    "401": "Issuer of traveler's checks", "402": "Seller of traveler's checks",
    "403": "Redeemer of traveler's checks", "404": "Issuer of money orders",
    "405": "Seller of money orders", "406": "Redeemer of money orders",
    "407": "Currency dealer/exchanger", "408": "Check casher",
    "409": "Money transmitter", "410": "Travelers check sales/redemption",
    "411": "Money order sales/redemption", "412": "US Postal Service",
    "413": "Seller of prepaid access", "414": "Provider of prepaid access",
    "415": "Dealer in foreign exchange", "4999": "Other",
}

# fintech signal -> (weight, KR RAS service line)
SERVICE = {
    "ft_national":   (20, "KR RAS: BSA/AML program + independent testing; multistate money-transmitter licensing (40+ states)"),
    "ft_fullstack":  (18, "KR RAS: enterprise BSA/AML program, independent testing, SOC/audit (full payments stack)"),
    "ft_multistate": (16, "KR RAS: BSA/AML program + independent testing; state MTL compliance (scaling)"),
    "ft_prepaid":    (14, "KR RAS: BSA/AML + FinCEN prepaid-access rule compliance; consumer compliance"),
    "ft_fx_crypto":  (14, "KR RAS: BSA/AML for virtual-currency / FX money transmission; OFAC/sanctions"),
}


def readable_acts(codes):
    labels = [ACT.get(c) for c in codes if c in ACT]
    labels = [x for x in labels if x]
    return "; ".join(dict.fromkeys(labels))


def main():
    print("Downloading FinCEN MSB list ...")
    r = requests.get(SRC, timeout=120)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), sep="\t", dtype=str).fillna("")
    print(f"  raw MSB registrants: {len(df):,}")

    df["is_us"] = df["STATE"].isin(US_STATES)
    df["nstates"] = df["STATES OF MSB ACTIVITIES"].apply(
        lambda s: len([x for x in s.split() if x in US_STATES]))
    df["acts"] = df["MSB ACTIVITIES"].apply(lambda s: set(s.split()))
    df["mt"] = df["acts"].apply(lambda a: "409" in a)
    df["prepaid"] = df["acts"].apply(lambda a: bool(a & {"413", "414"}))
    df["fx"] = df["acts"].apply(lambda a: bool(a & {"407", "415"}))
    df["branches"] = pd.to_numeric(df["# OF BRANCHES"], errors="coerce").fillna(0).astype(int)

    # fintech-relevant universe: US money transmitters and/or prepaid providers
    ft = df[df["is_us"] & (df["mt"] | df["prepaid"])].copy().reset_index(drop=True)

    sig = {
        "ft_national":   ft["mt"] & (ft["nstates"] >= 40),
        "ft_multistate": ft["mt"] & ft["nstates"].between(10, 39),
        "ft_prepaid":    ft["prepaid"],
        "ft_fullstack":  ft["mt"] & ft["prepaid"],
        "ft_fx_crypto":  ft["fx"] & (ft["mt"] | ft["prepaid"]),
    }
    for k, v in sig.items():
        ft[k] = v.fillna(False).astype(bool)
    signal_cols = list(sig.keys())

    ft["_m"] = ft.apply(lambda r: [s for s in signal_cols if r[s]], axis=1)
    ft["signals"] = ft["_m"].apply("; ".join)
    ft["service_lines"] = ft["_m"].apply(lambda xs: "; ".join(dict.fromkeys(SERVICE[s][1] for s in xs)))
    ft["n_signals"] = ft["_m"].apply(len)
    ft["score"] = ft["_m"].apply(lambda xs: sum(SERVICE[s][0] for s in xs))

    # "Known fintech" quality flag: matches a curated recognizable name, so the
    # real companies rank above the shell registrations. Boosts score so they
    # top the score-sorted dashboard; the full registry stays searchable.
    ft["ft_known"] = (ft["LEGAL NAME"] + " " + ft["DBA NAME"]).apply(
        lambda s: bool(KNOWN_RE.search(s)))
    # Shell tell: CO/WY-registered "Ltd"/"Limited" entities are overwhelmingly
    # shells (real US fintechs are Inc/LLC in CA/NY, never Ltd in CO). Don't let
    # them claim the known flag, and demote them so they sink below real ones.
    shell_like = (ft["STATE"].isin({"CO", "WY"}) &
                  ft["LEGAL NAME"].str.contains(r"\b(?:Ltd|Limited)\b", case=False, regex=True))
    ft["ft_known"] = ft["ft_known"] & ~shell_like
    ft.loc[ft["ft_known"], "score"] = ft.loc[ft["ft_known"], "score"] + 100
    ft.loc[shell_like, "score"] = ft.loc[shell_like, "score"] - 40

    ft["INST_TYPE"] = "Fintech"
    ft["CERT"] = 90_000_000 + ft.index          # synthetic id, no collision
    ft["NAME"] = ft["LEGAL NAME"].str.strip().str.title()
    ft["CITY"] = ft["CITY"].str.strip().str.title()
    ft["STALP"] = ft["STATE"]
    ft["FT_STATES"] = ft["nstates"]
    ft["FT_ACTIVITIES"] = ft["acts"].apply(lambda a: readable_acts(sorted(a)))
    ft["FT_BRANCHES"] = ft["branches"]
    ft["FT_DBA"] = ft["DBA NAME"].str.strip().str.title()

    ft["FT_KNOWN"] = ft["ft_known"]
    out_cols = ["INST_TYPE", "CERT", "NAME", "CITY", "STALP", "n_signals",
                "score", "signals", "FT_STATES", "FT_ACTIVITIES", "FT_BRANCHES",
                "FT_DBA", "FT_KNOWN"]
    # Cap to the top targets by score. The full registry has ~21k MSBs, but the
    # long tail is shell-dominated and self-reported; the top slice keeps all the
    # recognizable fintechs (boosted) plus the highest-footprint transmitters and
    # keeps the dashboard lean. Widen this if you want deeper coverage.
    ranked = ft[ft["n_signals"] > 0].sort_values(
        ["score", "FT_STATES"], ascending=False).head(1500)
    ranked[out_cols].to_csv("output/ft_targets.csv", index=False)

    print(f"Fintech universe (US MT/prepaid): {len(ft):,}")
    print(f"Fintech targets (>=1 signal):     {len(ranked):,}")
    print(f"  known (recognizable) fintechs:  {int(ft['ft_known'].sum()):,}")
    for s in signal_cols:
        print(f"  {s:<16} {int(ft[s].sum()):>6,}")


if __name__ == "__main__":
    main()
