# Known Gaps and Risks

An honest inventory of what this tool doesn't do yet and where it could break
quietly. Written 2026-08-26 after a full pass through FDIC's bank-data-guide
quick-reference table and everything built from it. Previously these lived
only in session notes outside the repo — nobody who didn't ask would have
known about them. They belong here instead.

## 1. Coverage gaps

### Credit unions get 10 signals; banks get 29
`08_cu_screen.py`'s `SERVICE` dict has 9 entries (near_10b, bsa_aml_scaling,
near_500m_audit, rapid_growth, credit_deterioration, weak_efficiency,
funding_liquidity, excess_capital, weak_profitability), plus `consent_order`
as of `15_cu_consent_orders.py`. Banks have picked up 19 more since: CRE
concentration + reverse stress test, uninsured-deposit risk, ag
concentration, deposit market share (SOD), M&A/failed-bank/charter events.
None of those have a credit-union equivalent, and some could:

- ~~NCUA issues its own formal enforcement actions~~ — **done**,
  `15_cu_consent_orders.py`. NCUA's Administrative Orders CSV is plain and
  static (no Playwright needed), but verified against real data that every
  institution-level order in the last 5 years targets a credit union well
  under the $500M screening floor — matches nothing today, kept as a safety
  net. See METHODOLOGY.md for the full writeup.
- **SOD-equivalent deposit/share concentration** — NCUA doesn't publish an
  SOD equivalent as far as investigated; would need research, not assumed
  buildable.
- **CRE-equivalent concentration test** — NCUA has its own MBL (member
  business loan) / CRE concentration supervisory guidance; not modeled here.

### Fintechs: regulatory-footprint signals only, no financials
This is an accepted limitation, not really closable — FinCEN's MSB registry
carries no financial data at all (documented in METHODOLOGY.md's fintech
section already). Listed here for completeness, not as an action item.

### Named-officer contacts: public banks only
`06_edgar.py` gets verified board/exec names for SEC-reporting banks via
EDGAR. Private banks, all credit unions, and all fintechs have no named
contact — LinkedIn search is the fallback for those. Apollo.io was the
planned enrichment path; no account/key exists. On hold, not dropped, per
prior direction.

### Salesforce push is manual
`export_salesforce.py` produces a CSV for the Data Import Wizard; there's no
API push into Salesforce. Intentional per `SALESFORCE_IMPORT.md`, revisit if
import volume grows enough to justify it.

## 2. Pipeline robustness risks

### No floor against a silently truncated pull
Every fetch calls `r.raise_for_status()`, which catches hard HTTP failures
(4xx/5xx) — those crash the step loudly and the Action shows red, which is
the correct behavior. Nothing catches a **soft** failure: an API call that
returns HTTP 200 with an empty or partial result (a bad filter, a mid-outage
partial response, a misconfigured `FDIC_API_KEY` that gets silently ignored
rather than rejected). If `01_fetch.py` ever pulled 40 institutions instead
of 4,000, nothing in the pipeline would notice — `02_screen.py` would happily
screen 40 banks, and the Action's commit step (`git diff --staged --quiet ||
commit`) has no row-count sanity check, so a near-empty `targets.csv` would
overwrite the real one on the next scheduled run. No script anywhere asserts
a minimum row count.

### Three scrapers depend on live browser automation against sites with no public API and no stability guarantee
FDIC ED&O (`14_consent_orders.py`, Salesforce Aura button), OCC EASearch
(`14_consent_orders.py`, server-rendered HTML, confirmed to block plain
`requests`/`curl` outright), and `11_state_licenses.py`'s NC/MA legs. Each is
wrapped in try/except so one flaky source can't take down the run, but that
same resilience is exactly what makes silent degradation possible — a
UI change on any of these sites makes that source return nothing, the step
still exits 0, and the Action still shows green. This already happened once
(the NC/MA `lxml`/`openpyxl` CI-dependency gap from 2026-08-22 — the run
"succeeded" with 3/5 state sources instead of 5/5, caught only by manually
reading the CI log line by line, not by any automated check).

### ~~The Action's own commit step had no retry on a push race~~ — fixed
Caught live: a manually-triggered Action run passed all 14 pipeline steps
clean, then failed at "Commit if the dashboard or output CSVs changed" — its
own `git push` got rejected because a manual push (from this same session)
landed on `main` first. `refresh.yml` had no pull-and-retry, just a bare
`git push`, so any concurrent push — another triggered run, a manual push, a
scheduled run overlapping a dispatch — could fail the whole job at the last
step after 15+ minutes of real work. Fixed with a 3-attempt
pull-`-X ours`-and-retry loop; safe here because this step only ever stages
`docs/index.html` and `output/*.csv`, so any conflict it hits can only be on
those deterministically-regenerated files.

### No monitoring or alerting on partial failure
Nothing watches for a step printing "fetch failed, skipping" or a
lower-than-expected match/row count. The only way to catch a silently
degraded source today is to read the Action log by hand after each run.

### No automated tests
Zero unit or integration tests across all 14 pipeline scripts. Every
verification so far has been manual: run the script, eyeball the output,
check idempotency by rerunning once. That's caught two real score-doubling
bugs this session alone (`12_sod_market_share.py`, then repeated in
`14_consent_orders.py`'s first pass) — both would have shipped without the
manual rerun-and-diff check. Nothing forces that check to happen next time.

## 3. Matching-confidence caveats

- **Fed consent orders**: fuzzy name match, no RSSD/charter cross-reference
  exists in the source dataset. Last run: 33 of 47 records matched to a CERT
  (14 unmatched — not individually verified as true non-matches vs. missed
  matches; could be name variants below the 88-score threshold, could be
  genuinely out-of-universe entities).
- **FDIC failed-bank acquirers** (`13_bank_events.py`): fuzzy match on
  `BIDNAME`, no CERT provided by the source. 9 of 13 failures in the 5-year
  window matched.
- **FinCEN fintech list**: quality capped by self-registration — shells and
  real companies are structurally identical in the source data. Documented
  at length in METHODOLOGY.md already.
- **State MT license cross-check**: only 5 of ~46 NMLS-participating states
  have a public bulk roster (FL, NC, MS, AK, MA); the rest are invisible to
  `11_state_licenses.py` by design (NMLS Consumer Access itself is
  ToS-blocked and Cloudflare-protected — investigated and ruled out, not an
  oversight).

## 4. Documentation debt

- **README.md is stale.** Still describes a 6-step pipeline (01/02/04/05/06/
  03); doesn't mention 07/08/09/10/11/12/13/14, doesn't mention the
  `FDIC_API_KEY` requirement (mandatory from FDIC's side starting
  2026-09-08), and its one accuracy claim about scraping ("step 11 is the
  only one that scrapes non-API state government pages") is now false —
  `14_consent_orders.py` scrapes two more (FDIC ED&O, OCC EASearch).
- **This file didn't exist until today.** Every gap above except the FDIC
  ED&O/OCC/NCUA-related ones was already known but tracked only in an
  external memory system outside the repo — invisible to anyone who didn't
  think to ask about it.

## Not gaps — deliberately out of scope

- FDIC's raw Call Report / FFIEC CDR bulk files: more granular than
  `api.fdic.gov/financials` (risview), but risview already exposes ~450-500
  fields via the same easy REST call we already use, including everything
  pulled so far. No wall hit here, just not needed yet.
- FDIC's aggregate/industry-level tools (Statistics at a Glance, Deposits
  Summary Tables, Annual Data Summaries, Aggregate Time Series, QBP, State
  Profiles, CFR, Community Banking Studies, FDIC Quarterly): no per-bank
  breakdown exists in any of them. Confirmed by direct inspection, not
  assumed.
