# Invoice & Supplier Tracker

Drop PDF or `.eml` invoices into `inbox/`, run one command, get structured data out.

> Status: **Stage 3 — categorization.** CSV output, flags and reporting
> follow in later stages.

## Quick start

```bash
python scripts/generate_invoices.py   # fill inbox/ with synthetic invoices
python -m invoice_tracker run         # extract every invoice in inbox/
pytest                                # run the tests
```

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

## Extraction

Each file in `inbox/` is loaded into a `RawDocument`:

- **PDF** — pdfplumber words, grouped into lines and *segments* (runs of words
  separated by a wide gap, so a label and its value become separate segments).
- **.eml** — each PDF attachment becomes a document; an email without a PDF
  falls back to its body text.

The **rule-based extractor** (`invoice_tracker/extract/rules.py`) finds a
segment whose whole text is a known label (`Invoice No.`, `Fakturadatum:`,
`Customer PO`, …) and takes the value to its right, or directly below it for
"labels above values" layouts. Values are validated (dates must parse, totals
must be numbers), so a wrong neighbour is skipped rather than accepted.
Exact-match labels mean `Subtotal` never wins over `Total`, and `Due date`
never wins over `Invoice date`.

- Supplier: matched by name / alias / email domain from `config/extraction.yaml`;
  unknown suppliers fall back to the letterhead text (`supplier_known = False`).
- Dates: ISO, `06 Aug 2026`, `7 juli 2026`, `29.05.2026`, `05/04/2026`. Ambiguous
  slash dates use the supplier's `date_order` (default day-first).
- Amounts: `1 234,50`, `1.234,50`, `1,234.50`, `$2,912.02`, `EUR 99.00`.
- Currency: from the total line, else anywhere in the document, else the
  supplier default.
- Missing fields are returned as `None`, never guessed.

Labels and suppliers are configured in `config/extraction.yaml`. Add a label
synonym or supplier there; no code changes needed.

### Swapping in another extractor (e.g. an LLM)

Extractors implement one method:

```python
class Extractor(Protocol):
    name: str
    def extract(self, doc: RawDocument) -> Invoice: ...
```

`doc.text` holds the plain text (what you'd send an LLM); `doc.lines` holds the
layout. Register the class and select it on the command line:

```python
from invoice_tracker.extract import register
register("llm", LLMExtractor)
```
```bash
python -m invoice_tracker run --extractor llm
```

## Categorization

Each invoice gets a spend category (`lab_consumables`, `instrument_service`,
`shipping`, or `uncategorized`) from `config/categories.yaml`:

1. **supplier** — the supplier name is in the supplier → category map.
2. **keywords** — otherwise, every line item is matched against per-category
   keyword regexes; the category with the most hits wins.
3. **default** — a tie or no hits gives `uncategorized` (better unsure than wrong).

The `category_source` column says which rule decided. To categorize a new
supplier, add one line under `suppliers:`.

## Tests

```bash
pytest
```

- `tests/test_extraction.py` generates a fresh inbox, checks every field of
  every invoice against the ground truth, and unit-tests the amount/date/currency
  parsers, email-body input, unknown suppliers and extractor swapping.
- `tests/test_categorize.py` covers the supplier rule, keyword vote, ties, and
  checks that keywords alone never assign a wrong category to the synthetic set.

## Project layout

```
config/
  extraction.yaml        # label synonyms, known suppliers
  categories.yaml        # supplier -> category, keyword fallback
invoice_tracker/
  models.py              # RawDocument, Invoice
  categorize.py          # Categorizer
  extract/
    base.py              # Extractor protocol + registry
    loaders.py           # PDF / .eml -> RawDocument
    parsing.py           # amount, date, currency parsing
    rules.py             # RuleBasedExtractor
  pipeline.py            # inbox -> invoices
  cli.py                 # python -m invoice_tracker ...
  synthetic.py           # invoice generator (reportlab)
scripts/
  generate_invoices.py   # CLI wrapper for the generator
tests/
```
