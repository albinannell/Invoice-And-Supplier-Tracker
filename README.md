# Invoice & Supplier Tracker

Drop PDF or `.eml` invoices into `inbox/`, run one command, get structured data out.

> Status: **Stage 1 — synthetic data generator.** Extraction, categorization,
> flags and reporting follow in later stages.

## Setup

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Note: `reportlab` is pinned below 5 (5.x needs Python 3.10+), and `cryptography`
below 44 (newer wheels fail to load against Anaconda Python 3.9's OpenSSL).

## Generate synthetic invoices

```bash
python scripts/generate_invoices.py            # writes to inbox/
python scripts/generate_invoices.py --out somewhere --seed 7
```

Produces 40 invoices (38 PDF + 2 `.eml` with the PDF attached) from 7 fictional
suppliers, all billed to the fictional buyer *Aurora Biosciences AB*:

| Supplier | Category | Currency | Layout quirks |
|---|---|---|---|
| Nordvik Labware AB | lab consumables | SEK | Swedish labels, `1 234,50`, ISO dates |
| PipetteCo Scientific Ltd | lab consumables | EUR | boxed field table, `06 Aug 2026`, `EUR 1,234.50` |
| BioReagent Supply GmbH | lab consumables | EUR | colour band header, Times, `29.05.2026`, `1.234,50` |
| Kalibra Instrument Services AB | instrument service | SEK | boxed field table, ISO dates |
| SpectraCare Field Service Inc. | instrument service | USD | Courier, labels-above-values strip, US dates, `$` |
| ColdChain Logistics AB | shipping | SEK | Swedish labels, `7 juli 2026` |
| Baltic Freight Express OÜ | shipping | EUR | `14/05/2026` (day first) |

Every invoice also has decoys an extractor must not confuse with the real
fields: due date, customer number, subtotal/VAT lines.

Planted problems:

- **2 exact duplicates** — byte-identical re-sends (`Fwd_resend_*.pdf`, `reminder_copy_*.pdf`)
- **1 near-duplicate** — BioReagent, same PO, new invoice number, amount +2%
- **2 unusually large amounts** — Nordvik and Kalibra, ~9× the supplier median
- **3 missing fields** — 2 without PO number, 1 without invoice date

`inbox/_ground_truth.json` records the true values and planted problems for
every file; tests use it to score extraction. Output is deterministic for a
given seed.

## Project layout

```
invoice_tracker/
  synthetic.py         # invoice generator (reportlab)
scripts/
  generate_invoices.py # CLI wrapper for the generator
```
