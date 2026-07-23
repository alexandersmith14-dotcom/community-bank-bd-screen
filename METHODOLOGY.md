# Community-Bank BD Screen — Methodology

**Purpose.** Reverse-engineer a business-development target list from primary
financial data. Every FDIC-insured bank files quarterly Call Reports; the FDIC
publishes the derived ratios through its BankFind API. This project pulls that
data for every bank under $10B, compares each bank to its size peers, and flags
the financial *symptoms* that map to an advisory conversation — with the exact
statistic to cite in outreach.

This is a **prospecting tool, not a conclusion**. A flag says "the numbers look
like a bank that might need X"; a human decides whether the story actually fits.

---

## Data

| Item | Source |
|---|---|
| Universe | FDIC BankFind `institutions`, `ACTIVE:1`, assets < $10B |
| Financial ratios | FDIC BankFind `financials`, latest quarter |
| Year-over-year growth | Same, prior-year quarter |

Report date is pinned at the top of `01_fetch.py` and updated each quarter.
All dollar figures from FDIC are in **thousands**.

## Peer grouping

"High" and "low" are meaningless in the abstract — a 12% capital ratio is
ordinary for a $150M bank and remarkable for a $9B one. So every relative signal
uses a **within-band percentile**. Bands:

- `<$250M`, `$250M–$1B`, `$1B–$3B`, `$3B–$10B`

A bank at the 90th percentile for equity/assets is in the top 10% *of banks its
own size*.

---

## Signals → service lines

Each signal is a rule over a ratio or its peer percentile. Peer-relative where
the question is "compared to similar banks"; absolute where a regulatory or
structural line matters. Thresholds live at the top of `02_screen.py` and are
meant to be tuned.

Service lines are mapped to **Kaufman Rossin Risk Advisory Services (RAS)**'s
actual catalog — AML & Sanctions, OFAC, Consumer Compliance, FINRA/SEC, Internal
Audit, Cybersecurity/DFIR, Robotic Process Automation, and the Risk Intelligence
Suite. Weights favor genuinely RAS-sellable signals; signals that belong to a
*different* KR practice are kept visible but scored low and tagged **Refer**.

| Signal | Rule (default) | FDIC fields | KR RAS service (weight) |
|---|---|---|---|
| **Near $10B threshold** | assets between $8B and $10B | `ASSET` | $10B readiness — Consumer Compliance (CFPB), BSA/AML, Internal Audit; FDICIA/SOX ICFR attestation (22) |
| **BSA/AML scaling** *(proxy)* | assets up ≥ 20% YoY | `ASSET` (YoY) | BSA/AML program enhancement + independent testing, OFAC (20) |
| **Near $1B (FDICIA)** | assets between $850M and $1.15B | `ASSET` | FDICIA Part 363 ICFR attestation readiness + Internal Audit (18) |
| **Rapid growth** | assets up ≥ 15% YoY | `ASSET` (YoY) | BSA/AML scaling, Internal Audit, risk assessment; FDICIA ICFR if crossing $1B (18) |
| **Credit deterioration** | net charge-offs *or* noncurrent in worst 15% of band | `NCLNLSR`, `NPERFV` | Internal Audit loan review + **CECL model validation** + ALLL/CECL governance (18) |
| **Weak efficiency** | efficiency ratio ≥ 70% **and** top 20% of band | `EEFFR` | Robotic Process Automation (RPA) + Internal Audit process review (15) |
| **Under-reserved** *(intensifier)* | deterioration **and** allowance < 40% of noncurrent | `ELNANTR` | CECL model validation / reserve adequacy review (10) |
| **Funding / liquidity** | loan/deposit ≥ 100% *or* worst 15% *or* brokered ≥ 10% of deposits | `LNLSDEPR`, `BRO`, `DEP` | *(partial)* Internal Audit of liquidity/funding controls; ALM advisory is another practice (10) |
| **Excess capital** | equity/assets in top 20% of peer band | `EQV` | *Refer* — capital deployment / M&A (other KR practice); RAS angle = M&A compliance due diligence (5) |
| **Weak profitability** | ROA in bottom 15% of band *or* negative | `ROA` | *Refer* — earnings / margin advisory (other KR practice); RAS angle = RPA cost automation (5) |

Two standing services that aren't cleanly signal-derived:

- **Cybersecurity / Digital Forensics & Incident Response** applies to essentially
  every institution — a universal cross-sell.
- **SOX ICFR (Section 404)** applies to *publicly traded* banks. Call Report data
  does not indicate which banks are SEC registrants, so SOX can't be flagged from
  this dataset alone; it rides along on the $1B+ / $10B ICFR-attestation signals
  and needs an external public/private data point to target precisely. **FDICIA**
  is the size-based analog (attestation at $1B) that *can* be flagged — see the
  "Near $1B (FDICIA)" signal above.

**Scoring.** Each matched signal carries a weight (see `SERVICE` in
`02_screen.py`); a bank's `score` is the sum, and `n_signals` is the count.
Ranking is by score, then signal count, then size.

### Reading the list

Signals are **not all the same direction**. "Excess capital" is a healthy bank
with a deployment question; "weak profitability" is a stressed bank with an
earnings question. A bank can show both. So for a specific service line, filter
`targets.csv` by that signal rather than only reading from the top. The score is
an intensity/breadth proxy, not a "best prospect" ranking for any one service.

## Trajectory signals (5-year, direction of travel)

`04_history.py` pulls 20 quarters and `05_trajectory.py` turns them into trend
features (OLS slope per year, 2-year change, growth acceleration, projected
runway to $10B). These are layered *on top of* the snapshot signals — a bank can
be flagged by a level, a trend, or both, and the combination is the point:
"over-capitalized **and** still building capital" is a warmer call than either
alone. Trend flags need ≥ 6 quarters of data.

| Trajectory signal | Rule (default) | KR RAS service (weight) |
|---|---|---|
| **Runway to $10B** | ≥ $5B now **and** projected to cross $10B within 12 quarters | $10B runway — Consumer Compliance (CFPB), BSA/AML, Internal Audit readiness (20) |
| **Growth accelerating** | assets ≥ 10% YoY **and** ≥ 3 pts faster than the prior year | BSA/AML scaling + Internal Audit as growth outpaces controls (16) |
| **Credit turning** | charge-offs *or* noncurrent rising ≥ 0.15 pts/yr | Early Internal Audit loan review / credit-risk controls (16) |
| **Margin eroding** | ROA falling ≤ −0.10 pts/yr **and** efficiency rising ≥ 2.5 pts/yr | *(partial)* RPA cost automation; broader margin advisory is another practice (10) |
| **Capital building** | equity/assets rising ≥ 0.40 pts/yr **and** +0.75 pts over 2yr | *Refer* — capital deployment / M&A (other KR practice) (5) |

Trajectory flags add to a bank's score and count alongside the snapshot signals.
The dashboard shows each flagged bank's equity/assets, ROA, assets, and
noncurrent trend as sparklines in its drill-down. Thresholds live at the top of
`05_trajectory.py`.

### Known limits

- **BSA/AML is a proxy.** Program adequacy isn't visible in Call Report ratios;
  fast asset growth is only a hint that a program has to scale. Treat as a
  conversation starter, not evidence.
- **Point-in-time.** One quarter. A trend (several quarters) is stronger signal
  than a single reading; adding multi-quarter history is the natural next build.
- **Peer bands are coarse.** Four size buckets. FFIEC's official UBPR peer
  groups are finer; these are a defensible approximation from primary data.
