# Community-Bank BD Screen

Pulls FDIC data for every U.S. bank under $10B, compares each to its size peers,
and produces a ranked business-development target list — banks whose financials
show a symptom that maps to an advisory service, with the stat to cite.

## Run it

```bash
python 01_fetch.py            # current-quarter FDIC snapshot  (needs internet)
python 02_screen.py           # snapshot signals -> targets.csv + all_banks.csv
python 04_history.py          # 20 quarters of history         (needs internet)
python 05_trajectory.py       # 5-year trend features -> enriched targets.csv
python 12_sod_market_share.py # deposit market share / HHI (FDIC SOD)
python 13_bank_events.py      # recent mergers, failed-bank acquisitions, charter changes
python 14_consent_orders.py   # formal enforcement orders (FDIC/OCC/Fed) -- needs Playwright
python 06_edgar.py            # SEC EDGAR board/execs for public banks (needs internet)
python 03_dashboard.py        # interactive dashboard
```

Dates auto-detect the latest quarter, so refreshing is just re-running. Re-tuning
snapshot thresholds needs only step 2 (+5 if you want trends re-merged); trend
thresholds live in `05_trajectory.py`. Steps 04/05/06/12/13/14 are optional --
without them the dashboard still works as a pure snapshot. Step 06 (SEC EDGAR)
adds verified board/executive names for the *public* banks and takes a few
minutes (rate-limited to SEC's guidelines). Steps 07/08/10/15 (credit unions -- 15 is NCUA formal enforcement orders, run
after 10), 09 (fintechs), and 11 (state-license cross-check for fintechs —
run 09 first) are optional add-ons to the bank screen; `.github/workflows/
refresh.yml` runs the full set weekly.

**API key required from 2026-09-08.** `api.fdic.gov` (used by 01/02/04/12/13)
requires an api.data.gov key starting that date. Set `FDIC_API_KEY` as an env
var / repo secret; requests work unauthenticated before the deadline and
authenticated after. Register at <https://api.data.gov/signup/>.

See `GAPS.md` for known coverage gaps and pipeline robustness risks.

## Output

- `output/targets.csv` — one row per flagged bank: matched signals, mapped
  service lines, score, and the headline ratios. Import into Salesforce as
  leads/accounts, or filter by signal for a given service pitch.
- `output/signal_summary.csv` — how many banks tripped each signal.

## How it works

See `METHODOLOGY.md` for every signal, threshold, and FDIC field, plus the
important caveats (BSA/AML is a proxy, it's point-in-time, peer bands are coarse).

## Requirements

Python 3 with `pandas`, `requests`, and `numpy`. Steps 06/09 need nothing extra;
steps 11/13/14 additionally need `pdfplumber`, `rapidfuzz`, `lxml`, `openpyxl`,
and `playwright` (plus `playwright install chromium` once). 11, 14's FDIC ED&O
leg, and 14's OCC leg all drive a real browser against sites with no public
API (ED&O and OCC's own EASearch actively block plain HTTP clients) -- these
are the steps most likely to need a source fixed up over time. Each fetch is
wrapped in try/except and skips independently on failure rather than crashing
the run, so a broken source degrades quietly; see `GAPS.md`.
