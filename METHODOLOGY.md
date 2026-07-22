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

| Signal | Rule (default) | FDIC fields | Maps to |
|---|---|---|---|
| **Excess capital** | equity/assets in top 20% of peer band | `EQV` | Capital deployment, M&A readiness, capital planning |
| **Credit deterioration** | net charge-offs *or* noncurrent assets in worst 15% of band | `NCLNLSR`, `NPERFV` | Credit risk review, ALLL/CECL validation, loan review |
| **Under-reserved** *(intensifier)* | deterioration **and** allowance < 40% of noncurrent loans | `ELNANTR` | ALLL/CECL model validation, reserve adequacy |
| **Weak efficiency** | efficiency ratio ≥ 70% **and** top 20% of band | `EEFFR` | Process improvement, outsourced internal audit, cost transformation |
| **Funding / liquidity** | loan-to-deposit ≥ 100% *or* worst 15% of band *or* brokered deposits ≥ 10% of deposits | `LNLSDEPR`, `BRO`, `DEP` | Liquidity risk management, funding & IRR advisory |
| **Rapid growth** | assets up ≥ 15% year over year | `ASSET` (YoY) | Growth-tier readiness, risk-infrastructure scaling |
| **Near $10B threshold** | assets between $8B and $10B | `ASSET` | $10B readiness: Durbin, CFPB supervision, DFAST |
| **Weak profitability** | ROA in bottom 15% of band *or* negative | `ROA` | Earnings improvement, margin & balance-sheet advisory |
| **BSA/AML scaling** *(proxy)* | assets up ≥ 20% YoY | `ASSET` (YoY) | BSA/AML program enhancement, independent testing |

**Scoring.** Each matched signal carries a weight (see `SERVICE` in
`02_screen.py`); a bank's `score` is the sum, and `n_signals` is the count.
Ranking is by score, then signal count, then size.

### Reading the list

Signals are **not all the same direction**. "Excess capital" is a healthy bank
with a deployment question; "weak profitability" is a stressed bank with an
earnings question. A bank can show both. So for a specific service line, filter
`targets.csv` by that signal rather than only reading from the top. The score is
an intensity/breadth proxy, not a "best prospect" ranking for any one service.

### Known limits

- **BSA/AML is a proxy.** Program adequacy isn't visible in Call Report ratios;
  fast asset growth is only a hint that a program has to scale. Treat as a
  conversation starter, not evidence.
- **Point-in-time.** One quarter. A trend (several quarters) is stronger signal
  than a single reading; adding multi-quarter history is the natural next build.
- **Peer bands are coarse.** Four size buckets. FFIEC's official UBPR peer
  groups are finer; these are a defensible approximation from primary data.
