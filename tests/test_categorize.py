import pytest

from invoice_tracker.categorize import Categorizer
from invoice_tracker.models import Invoice
from invoice_tracker.pipeline import process_inbox


@pytest.fixture(scope="module")
def cat():
    return Categorizer()


def test_known_supplier_uses_supplier_rule(cat):
    inv = Invoice("x.pdf", supplier="Kalibra Instrument Services AB",
                  line_items=["Dry ice shipment"])  # keywords would say shipping
    assert cat.classify(inv) == ("instrument_service", "supplier")


def test_supplier_rule_is_case_insensitive(cat):
    inv = Invoice("x.pdf", supplier="nordvik labware ab")
    assert cat.classify(inv) == ("lab_consumables", "supplier")


@pytest.mark.parametrize("items,expected", [
    (["Filter pipette tips 200 uL", "Nitrile gloves"], "lab_consumables"),
    (["Annual calibration - balance", "Technician hours"], "instrument_service"),
    (["Air freight, express parcel", "Customs clearance fee"], "shipping"),
    (["Calibration visit", "Pipette tips", "Gloves"], "lab_consumables"),  # majority
])
def test_unknown_supplier_uses_keyword_vote(cat, items, expected):
    inv = Invoice("x.pdf", supplier="Some New Vendor", line_items=items)
    assert cat.classify(inv) == (expected, "keywords")


def test_tie_or_no_keywords_is_uncategorized(cat):
    tie = Invoice("x.pdf", supplier="New Vendor", line_items=["Courier", "Calibration"])
    nothing = Invoice("y.pdf", supplier="New Vendor", line_items=["Consulting fee"])
    empty = Invoice("z.pdf", supplier=None)
    for inv in (tie, nothing, empty):
        assert cat.classify(inv) == ("uncategorized", "default")


def test_pipeline_categorizes_synthetic_inbox(synthetic_inbox):
    inbox, truth = synthetic_inbox
    invoices = process_inbox(inbox)
    for inv in invoices:
        assert inv.category == truth[inv.source_file]["category"]
        assert inv.category_source == "supplier"


def test_keywords_alone_mostly_agree_with_truth(synthetic_inbox):
    """Ignoring the supplier map, keywords should classify nearly everything
    correctly and never pick a *wrong* category (unsure -> uncategorized)."""
    _, truth = synthetic_inbox
    cat = Categorizer()
    cat.by_supplier = {}
    results = [cat.classify(Invoice("x", supplier=t["supplier"], line_items=t["line_items"]))[0]
               for t in truth.values()]
    expected = [t["category"] for t in truth.values()]
    wrong = [(r, e) for r, e in zip(results, expected) if r not in (e, "uncategorized")]
    correct = sum(r == e for r, e in zip(results, expected))
    assert not wrong
    assert correct / len(expected) >= 0.9
