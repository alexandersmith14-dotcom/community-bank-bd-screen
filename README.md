# Community-Bank BD Screen

Pulls FDIC data for every U.S. bank under $10B, compares each to its size peers,
and produces a ranked business-development target list — banks whose financials
show a symptom that maps to an advisory service, with the stat to cite.

## Run it

```bash
python 01_fetch.py       # current-quarter FDIC snapshot  (needs internet)
python 02_screen.py      # snapshot signals -> targets.csv + all_banks.csv
python 04_history.py     # 20 quarters of history         (needs internet)
python 05_trajectory.py  # 5-year trend features -> enriched targets.csv
python 03_dashboard.py   # interactive dashboard (snapshot + trajectory)
```

Dates auto-detect the latest quarter, so refreshing is just re-running. Re-tuning
snapshot thresholds needs only step 2 (+5 if you want trends re-merged); trend
thresholds live in `05_trajectory.py`. Steps 04/05 are optional — without them
the dashboard still works as a pure snapshot.

## Output

- `output/targets.csv` — one row per flagged bank: matched signals, mapped
  service lines, score, and the headline ratios. Import into Salesforce as
  leads/accounts, or filter by signal for a given service pitch.
- `output/signal_summary.csv` — how many banks tripped each signal.

## How it works

See `METHODOLOGY.md` for every signal, threshold, and FDIC field, plus the
important caveats (BSA/AML is a proxy, it's point-in-time, peer bands are coarse).

## Requirements

Python 3 with `pandas` and `requests`.
