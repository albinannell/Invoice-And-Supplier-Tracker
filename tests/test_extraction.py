from datetime import date

import pytest

from invoice_tracker.extract import get_extractor, load_text, register
from invoice_tracker.extract.parsing import detect_currency, parse_amount, parse_date
from invoice_tracker.models import Invoice
from invoice_tracker.pipeline import extract_inbox

FIELDS = ["supplier", "invoice_number", "invoice_date", "total_amount", "currency", "po_number"]


def _norm(v):
    return v.isoformat() if isinstance(v, date) else v


# ------------------------------------------------- against ground truth --

def test_every_file_is_extracted(synthetic_inbox, extracted):
    _, truth = synthetic_inbox
    assert set(extracted) == set(truth)


@pytest.mark.parametrize("field", FIELDS)
def test_field_matches_ground_truth(synthetic_inbox, extracted, field):
    _, truth = synthetic_inbox
    wrong = {f: (_norm(getattr(inv, field)), truth[f][field])
             for f, inv in extracted.items()
             if _norm(getattr(inv, field)) != truth[f][field]}
    assert not wrong, f"{field} mismatches (got, want): {wrong}"


def test_line_items_match_ground_truth(synthetic_inbox, extracted):
    _, truth = synthetic_inbox
    for f, inv in extracted.items():
        assert inv.line_items == truth[f]["line_items"], f


def test_missing_fields_are_none_not_guessed(synthetic_inbox, extracted):
    _, truth = synthetic_inbox
    planted = {f: t["planted"] for f, t in truth.items()}
    no_po = [f for f, p in planted.items() if "missing_po_number" in p]
    no_date = [f for f, p in planted.items() if "missing_invoice_date" in p]
    assert len(no_po) == 2 and len(no_date) == 1
    for f in no_po:
        assert extracted[f].po_number is None
        assert extracted[f].missing_fields() == ["po_number"]
    for f in no_date:
        assert extracted[f].invoice_date is None
        assert extracted[f].missing_fields() == ["invoice_date"]


def test_eml_attachment_is_extracted(extracted):
    emls = [inv for f, inv in extracted.items() if f.endswith(".eml")]
    assert len(emls) == 2
    assert all(not inv.missing_fields() for inv in emls)


def test_exact_duplicates_share_hash(synthetic_inbox, extracted):
    _, truth = synthetic_inbox
    for f, t in truth.items():
        if "duplicate_exact" in t["planted"]:
            assert extracted[f].sha256 == extracted[t["duplicate_of"]].sha256


# ------------------------------------------------------- unit: parsing --

@pytest.mark.parametrize("text,expected", [
    ("1 234,50", 1234.50),
    ("12 345,00 SEK", 12345.00),
    ("1.234,50", 1234.50),
    ("1,234.50", 1234.50),
    ("EUR 99.00", 99.00),
    ("$2,912.02", 2912.02),
    ("213 525,00 SEK", 213525.00),
    ("1,234", 1234.0),
    ("1.234", 1234.0),
    ("0,5", 0.5),
    ("1'234.50", 1234.50),
    ("Net 30", 30.0),
    ("no digits here", None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text,order,expected", [
    ("2026-05-14", "dmy", date(2026, 5, 14)),
    ("06 Aug 2026", "dmy", date(2026, 8, 6)),
    ("7 juli 2026", "dmy", date(2026, 7, 7)),
    ("12 okt 2026", "dmy", date(2026, 10, 12)),
    ("Aug 6, 2026", "dmy", date(2026, 8, 6)),
    ("29.05.2026", "mdy", date(2026, 5, 29)),   # dotted is always day-first
    ("05/04/2026", "dmy", date(2026, 4, 5)),
    ("05/04/2026", "mdy", date(2026, 5, 4)),
    ("25/04/2026", "mdy", date(2026, 4, 25)),   # unambiguous overrides hint
    ("Net 30", "dmy", None),
    ("31/02/2026", "dmy", None),
])
def test_parse_date(text, order, expected):
    assert parse_date(text, order) == expected


@pytest.mark.parametrize("text,expected", [
    ("EUR 1,234.50", "EUR"), ("6 960,00 SEK", "SEK"), ("$12.00", "USD"),
    ("€ 40", "EUR"), ("450 kr", "SEK"), ("1,234.50", None),
])
def test_detect_currency(text, expected):
    assert detect_currency(text) == expected


# ------------------------------------------------- text / unknown input --

def test_text_only_email_body():
    body = (
        "From: Kalibra Instrument Services AB <invoices@kalibra.se>\n"
        "Invoice number: KIS-01234\n"
        "Invoice date: 2026-09-03\n"
        "PO: 4500123456\n"
        "Total amount: 18 750,00 SEK\n"
    )
    inv = get_extractor("rules").extract(load_text(body, "mail.eml"))
    assert inv.supplier == "Kalibra Instrument Services AB"
    assert inv.supplier_known
    assert inv.invoice_number == "KIS-01234"
    assert inv.invoice_date == date(2026, 9, 3)
    assert inv.po_number == "4500123456"
    assert inv.total_amount == 18750.00
    assert inv.currency == "SEK"


def test_unknown_supplier_falls_back_to_letterhead():
    text = "Acme Widgets Ltd\nInvoice No:  A-77\nDate:  03/09/2026\nTotal:  GBP 120.00\n"
    inv = get_extractor("rules").extract(load_text(text, "acme.pdf"))
    assert inv.supplier == "Acme Widgets Ltd"
    assert not inv.supplier_known
    assert inv.invoice_number == "A-77"
    assert inv.invoice_date == date(2026, 9, 3)       # dmy default
    assert (inv.total_amount, inv.currency) == (120.0, "GBP")
    assert inv.po_number is None


def test_subtotal_is_not_taken_as_total():
    text = "Nordvik Labware AB\nSubtotal:  1 000,00\nMoms 25%:  250,00\nAtt betala:  1 250,00 SEK\n"
    inv = get_extractor("rules").extract(load_text(text, "x.pdf"))
    assert inv.total_amount == 1250.0


def test_due_date_is_not_taken_as_invoice_date():
    text = "Kalibra AB\nDue date:  2026-10-01\nInvoice date:  2026-09-01\n"
    inv = get_extractor("rules").extract(load_text(text, "x.pdf"))
    assert inv.invoice_date == date(2026, 9, 1)


# --------------------------------------------------- swappable interface --

def test_extractor_can_be_swapped(synthetic_inbox):
    class FakeExtractor:
        name = "fake"

        def extract(self, doc):
            return Invoice(source_file=doc.source_file, supplier="FAKE", extractor=self.name)

    register("fake", FakeExtractor)
    inbox, truth = synthetic_inbox
    invs = extract_inbox(inbox, get_extractor("fake"))
    assert len(invs) == len(truth)
    assert {i.supplier for i in invs} == {"FAKE"}
    assert {i.extractor for i in invs} == {"fake"}
