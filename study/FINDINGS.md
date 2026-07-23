# The pre-enforcement financial signature

**Question:** Do community banks that receive a consent order / formal action share
a consistent financial pattern *before* the order lands?

**Answer: yes — a coherent one.**

## Data
- **95** bank-level enforcement orders (OCC Cease-and-Desist / Formal Agreement /
  Consent Order + Federal Reserve Written Agreement / Consent / C&D / PCA) since
  Jan 2022, from the OpenSanctions mirrors of each regulator's published actions.
- **75** matched to their FDIC CERT (name + state), then to the tool's 20-quarter
  financial history.
- Coverage caveat: OCC (national banks) + Fed (state-member banks). It does **not**
  include FDIC-regulated state-nonmember banks (their enforcement isn't published
  as data), so this is a large sample, not the full population.

## Method
For each enforced bank, we took its financials in each of the 8 quarters *before*
the order and computed its **percentile within its own asset-size band** that
quarter (using the whole community-bank population). We flipped "good" metrics so
that **higher = more distressed**, then averaged across all enforced banks by how
many quarters before the order it was. 50 = an average bank; 100 = worst of its peers.

## The signature (distress percentile, quarters before the order)

| Metric | t-8 | t-6 | t-4 | t-2 | t-1 |
|---|---|---|---|---|---|
| **ROA (earnings)** | 57 | 57 | 65 | 68 | **71** |
| **Efficiency ratio** | 59 | 62 | 64 | 69 | **70** |
| **Noncurrent assets / assets** | 63 | 64 | 66 | 67 | **64** |
| **Net charge-offs / loans** | 63 | 63 | 66 | 66 | **63** |
| **Brokered deposits / deposits** | 54 | 57 | 57 | 61 | **61** |
| Equity / assets (capital) | 56 | 56 | 52 | 55 | 55 |
| Asset growth (YoY) | 45 | 51 | 57 | 49 | 52 |

## What it says
1. **Earnings are the clearest tell.** ROA distress climbs steadily from ~57th to
   the **71st percentile** over the two years before an order — a bank quietly
   grinding toward the bottom of its peer group on profitability.
2. **Efficiency worsens in lockstep** — costs rising relative to revenue, to the
   70th percentile by the quarter before.
3. **Asset quality is persistently weak the entire time** — noncurrent loans and
   charge-offs sit around the 63rd–66th percentile for the full two years, not a
   late spike. These banks had a credit problem well before the order.
4. **Funding stress builds** — reliance on brokered deposits rises into the order,
   a classic "reaching for funding as the core weakens" sign.
5. **Capital is only mildly weak, and rapid growth is *not* a consistent
   precursor** — the story is earnings + asset quality + funding, not a capital or
   growth blow-up. (Capital often still looks OK when the order hits.)

**Plain-English signature:** *a persistent credit-quality problem, grinding
earnings and efficiency deterioration over ~2 years, and rising brokered funding —
capital still standing.*

## Honest read on strength
The pattern is real and directionally consistent across metrics, but it's
**moderate, not extreme** (percentiles in the 60s–70s, not 90s) — averages wash out
individual variation, and plenty of weak-earnings banks never get an order. So this
is a **risk indicator, not a prediction**: banks matching the profile are
meaningfully more order-prone than peers, with false positives expected.

## The payoff
This signature can be turned into a **"pre-enforcement profile" flag** in the
screen — surface banks *today* whose ROA, efficiency, asset quality, and brokered
funding look like enforced banks did in the year before their order. For KR RAS
that's a warm, specific reason to reach out ("your profile matches banks that drew
regulatory action — here's how we help get ahead of it") — and it's built entirely
from data we already pull.
