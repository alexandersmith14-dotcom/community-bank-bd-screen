# Importing the target list into Salesforce

You don't need to know Salesforce well — the Data Import Wizard walks you through
it. Here's the whole thing in plain steps.

## The file
`output/salesforce_import.csv` — one row per institution (banks, credit unions,
fintechs), sorted best-first. Regenerate it any time with:

```bash
python export_salesforce.py
```

Each row has: **Institution Name, Institution Type, Priority (Hot/Warm/Cool),
Priority Score, State, City, Assets ($B), KR RAS Services** (what to pitch),
**Signals** (why they're flagged), **Key Metrics** (the numbers to cite),
**Public Ticker**, **Board / Executives** (real names for public banks),
**LinkedIn Decision-Maker Search** (a link that opens the right people), and a
**Description** that summarizes all of it in one field.

## Before you import — two decisions
1. **How much to load.** 5,000+ rows is a lot for a first import. Open the CSV in
   Excel and filter to what you'll actually work — e.g. `Priority = Hot`, or one
   `Institution Type`, or one `State` — and save that as your import file. You can
   always import more later.
2. **Accounts or Leads?** Import these as **Accounts** (each institution is a
   company, not a person). That's the simplest and cleanest fit.

## The steps (Salesforce Data Import Wizard)
1. In Salesforce, click the **gear icon** (top right) → **Setup**.
2. In the Setup search box, type **Data Import Wizard** and open it.
3. Click **Launch Wizard**.
4. Under "What kind of data are you importing?", choose **Accounts and Contacts**.
5. Choose **Add new records**.
6. Drag in your CSV (or "CSV" → choose file). Click **Next**.
7. **Map the columns.** Salesforce shows your CSV columns on the left and its
   fields on the right. Map at least:
   - `Institution Name` → **Account Name**
   - `State` → **Billing State/Province**
   - `City` → **Billing City**
   - `Description` → **Account Description**
   Anything you don't have a field for, leave **unmapped** — it's fine. (If your
   admin later adds custom fields for Priority, Signals, KR RAS Services, etc.,
   you can map those too.)
8. Click **Next**, then **Start Import**.
9. Salesforce emails you when it's done (usually minutes). The accounts appear
   under the **Accounts** tab.

## Getting more of the data into Salesforce (optional, later)
The rich columns (Priority, KR RAS Services, Signals, LinkedIn link…) only land in
Salesforce if there are fields to hold them. Two options:
- **Easiest:** everything is already inside the **Description** field, so it's all
  there in one place even with zero setup.
- **Better, needs an admin:** ask whoever manages your Salesforce to add a few
  custom fields on Account (Priority, Priority Score, KR RAS Services, Signals,
  LinkedIn Search URL). Then re-run the import and map those columns. Your BD team
  can then filter/report on them (e.g. "all Hot banks in Texas flagged for BSA/AML").

## Tip
Start small — import the Hot banks for one state, make sure it looks right in
Salesforce, then scale up. Nothing here is irreversible; you can delete a bad
import and redo it.
