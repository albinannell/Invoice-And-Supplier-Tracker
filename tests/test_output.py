import csv
from datetime import date

from invoice_tracker.cli import main
from invoice_tracker.models import Invoice
from invoice_tracker.output import INVOICE_COLUMNS, write_invoices_csv


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def test_csv_row_format(tmp_path):
    inv = Invoice("a.pdf", supplier="Baltic Freight Express OÜ", supplier_known=True,
                  invoice_number="BFE000834", invoice_date=date(2026, 6, 23),
                  total_amount=494.1, currency="EUR", po_number=None,
                  line_items=["Air freight", "Customs clearance fee"],
                  category="shipping", category_source="supplier", extractor="rules")
    rows = _read(write_invoices_csv([inv], tmp_path / "out" / "invoices.csv"))
    assert rows == [{
        "source_file": "a.pdf", "supplier": "Baltic Freight Express OÜ",
        "supplier_known": "yes", "invoice_number": "BFE000834",
        "invoice_date": "2026-06-23", "total_amount": "494.10", "currency": "EUR",
        "po_number": "", "category": "shipping", "category_source": "supplier",
        "line_items": "Air freight | Customs clearance fee", "extractor": "rules",
    }]


def test_run_command_writes_one_row_per_invoice(synthetic_inbox, tmp_path, capsys):
    inbox, truth = synthetic_inbox
    main(["run", "--inbox", str(inbox), "--out", str(tmp_path)])
    rows = _read(tmp_path / "invoices.csv")
    assert list(rows[0]) == list(INVOICE_COLUMNS)
    assert len(rows) == len(truth)
    assert {r["source_file"] for r in rows} == set(truth)
    for r in rows:
        t = truth[r["source_file"]]
        assert r["total_amount"] == f"{t['total_amount']:.2f}"
        assert r["invoice_date"] == (t["invoice_date"] or "")
        assert r["po_number"] == (t["po_number"] or "")
    assert "Wrote" in capsys.readouterr().out
