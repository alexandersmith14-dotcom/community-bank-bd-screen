# Community-Bank BD Screen

Pulls FDIC data for every U.S. bank under $10B, compares each to its size peers,
and produces a ranked business-development target list — banks whose financials
show a symptom that maps to an advisory service, with the stat to cite.

## Run it

```bash
python 01_fetch.py     # downloads FDIC data into ./data  (needs internet)
python 02_screen.py    # builds ./output/targets.csv      (offline, fast)
```

Re-tuning thresholds only needs step 2. Refreshing for a new quarter: update
`CURRENT_REPDTE` / `PRIOR_REPDTE` in `01_fetch.py`, then run both.

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
