import csv
from collections import defaultdict
from datetime import date, datetime, timezone

from invoice_tracker.cli import main
from invoice_tracker.models import Invoice
from invoice_tracker.summary import (
    SUMMARY_COLUMNS, build_report, monthly_summary, write_summary_csv,
)


def inv(name, amount, d, *, supplier="Acme AB", cat="shipping", cur="SEK", flags=()):
    return Invoice(source_file=name, supplier=supplier, invoice_date=d, total_amount=amount,
                   currency=cur, category=cat, flags=list(flags),
                   flag_reasons=[f"reason for {f}" for f in flags])


def test_groups_by_month_supplier_category_currency():
    rows = monthly_summary([
        inv("a", 100, date(2026, 5, 3)),
        inv("b", 50.5, date(2026, 5, 20)),
        inv("c", 10, date(2026, 6, 1)),
        inv("d", 7, date(2026, 5, 9), cur="EUR"),
        inv("e", 1, date(2026, 5, 9), supplier="Other AB"),
    ])
    got = {(r.month, r.supplier, r.currency): (r.invoice_count, r.total_spend) for r in rows}
    assert got == {
        ("2026-05", "Acme AB", "SEK"): (2, 150.5),
        ("2026-06", "Acme AB", "SEK"): (1, 10.0),
        ("2026-05", "Acme AB", "EUR"): (1, 7.0),
        ("2026-05", "Other AB", "SEK"): (1, 1.0),
    }


def test_exact_duplicates_excluded_near_duplicates_included():
    rows = monthly_summary([
        inv("a", 100, date(2026, 5, 3)),
        inv("a-copy", 100, date(2026, 5, 3), flags=["duplicate_exact"]),
        inv("near", 102, date(2026, 5, 9), flags=["duplicate_near"]),
    ])
    assert len(rows) == 1
    assert (rows[0].invoice_count, rows[0].total_spend, rows[0].flagged_count) == (2, 202.0, 1)


def test_undated_invoice_uses_received_month_and_missing_amount_is_skipped():
    undated = inv("u", 40, None)
    undated.received_at = datetime(2026, 7, 2, tzinfo=timezone.utc)
    rows = monthly_summary([undated, inv("x", None, date(2026, 7, 1))])
    assert [(r.month, r.total_spend) for r in rows] == [("2026-07", 40.0)]
    report = build_report([undated], rows, today=date(2026, 10, 31))
    assert "placed in the month they were received: u" in report


def test_summary_csv_format(tmp_path):
    rows = monthly_summary([inv("a", 1234.5, date(2026, 5, 3))])
    path = write_summary_csv(rows, tmp_path / "s.csv")
    with open(path, newline="", encoding="utf-8-sig") as fh:
        data = list(csv.DictReader(fh))
    assert list(data[0]) == SUMMARY_COLUMNS
    assert data[0]["total_spend"] == "1234.50" and data[0]["month"] == "2026-05"


def test_report_sections_and_notes():
    invoices = [
        inv("a.pdf", 1000, date(2026, 5, 3)),
        inv("b.pdf", 1000, date(2026, 5, 3), flags=["duplicate_exact"]),
        inv("big.pdf", 90000, date(2026, 6, 3), flags=["unusual_amount"]),
        inv("e.pdf", 50, date(2026, 6, 4), cur="EUR", cat="lab_consumables"),
    ]
    report = build_report(invoices, monthly_summary(invoices), today=date(2026, 10, 31))
    for heading in ["# Invoice spend report", "## Totals", "## Spend by month",
                    "## Spend by category", "## Top suppliers", "## Flagged invoices (2)",
                    "## Notes"]:
        assert heading in report
    assert "period 2026-05 to 2026-06" in report
    assert "4 invoices processed, 3 counted" in report
    assert "1 exact duplicate(s) excluded from spend (1,000 SEK)" in report
    assert "90,000 SEK in 2026-06" in report
    assert "nothing is converted" in report
    # duplicates listed before other flags, with their reasons
    assert report.index("b.pdf") < report.index("big.pdf")
    assert "reason for duplicate_exact" in report


def test_end_to_end_totals_reconcile(synthetic_inbox, tmp_path):
    """Monthly summary == invoice CSV minus exact duplicates, per currency."""
    inbox, truth = synthetic_inbox
    main(["run", "--inbox", str(inbox), "--out", str(tmp_path)])
    for name in ("invoices.csv", "monthly_summary.csv", "report.md"):
        assert (tmp_path / name).exists()

    def read(name):
        with open(tmp_path / name, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    expected = defaultdict(float)
    for r in read("invoices.csv"):
        if "duplicate_exact" not in r["flags"]:
            expected[r["currency"]] += float(r["total_amount"])
    got = defaultdict(float)
    for r in read("monthly_summary.csv"):
        got[r["currency"]] += float(r["total_spend"])
    assert {k: round(v, 2) for k, v in got.items()} == {k: round(v, 2) for k, v in expected.items()}

    planted_dupes = sum("duplicate_exact" in t["planted"] for t in truth.values())
    counted = sum(int(r["invoice_count"]) for r in read("monthly_summary.csv"))
    assert counted == len(truth) - planted_dupes
