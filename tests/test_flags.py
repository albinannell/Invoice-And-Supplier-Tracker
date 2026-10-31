from datetime import date, datetime, timedelta, timezone

import pytest

from invoice_tracker.flags import (
    DUPLICATE_EXACT, DUPLICATE_NEAR, MISSING_FIELDS, UNUSUAL_AMOUNT, FlagConfig, apply_flags,
)
from invoice_tracker.models import Invoice
from invoice_tracker.pipeline import process_inbox
from invoice_tracker.synthetic import generate

T0 = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
CFG = FlagConfig()  # code defaults == config/flags.yaml


def inv(name, amount=1000.0, *, supplier="Acme AB", number=None, po=None, day=0,
        currency="SEK", sha=None, invoice_date=date(2026, 6, 1)):
    return Invoice(
        source_file=name, supplier=supplier, invoice_number=number or f"N-{name}",
        invoice_date=invoice_date, total_amount=amount, currency=currency,
        po_number=po or f"PO-{name}", sha256=sha or f"sha-{name}",
        received_at=T0 + timedelta(days=day),
    )


def flags_of(invoices):
    return {i.source_file: set(i.flags) for i in invoices}


# ------------------------------------------------- synthetic ground truth --

PLANTED_TO_FLAG = {"missing_po_number": MISSING_FIELDS, "missing_invoice_date": MISSING_FIELDS}


def _expected(truth):
    return {(f, PLANTED_TO_FLAG.get(p, p)) for f, t in truth.items() for p in t["planted"]}


def test_synthetic_flags_match_planted_problems(synthetic_inbox):
    inbox, truth = synthetic_inbox
    invoices = process_inbox(inbox)
    got = {(i.source_file, f) for i in invoices for f in i.flags}
    assert got == _expected(truth)


def test_synthetic_duplicates_point_to_original(synthetic_inbox):
    inbox, truth = synthetic_inbox
    by_file = {i.source_file: i for i in process_inbox(inbox)}
    for f, t in truth.items():
        if t["duplicate_of"]:
            assert by_file[f].duplicate_of == t["duplicate_of"]
            assert t["duplicate_of"] in " ".join(by_file[f].flag_reasons)
        else:
            assert by_file[f].duplicate_of is None


@pytest.mark.parametrize("seed", [3, 17, 2026])
def test_other_seeds_catch_every_planted_problem(tmp_path, seed):
    """Every planted problem is caught on other data too. (A rare extra
    unusual_amount on a naturally large invoice is tolerated; nothing else.)"""
    truth = {t["source_file"]: t for t in generate(tmp_path, seed=seed)}
    got = {(i.source_file, f) for i in process_inbox(tmp_path) for f in i.flags}
    expected = _expected(truth)
    assert expected <= got
    assert {f for _, f in got - expected} <= {UNUSUAL_AMOUNT}


# ---------------------------------------------------------- exact dupes --

def test_identical_file_flags_later_copy_only():
    a = inv("a.pdf", sha="same", day=0)
    b = inv("b.pdf", sha="same", day=2, number="OTHER")  # bytes win regardless
    apply_flags([b, a], CFG)
    assert flags_of([a, b]) == {"a.pdf": set(), "b.pdf": {DUPLICATE_EXACT}}
    assert b.duplicate_of == "a.pdf"
    assert "identical file" in b.flag_reasons[0]


def test_same_supplier_number_amount_is_exact_duplicate_even_if_bytes_differ():
    a = inv("a.pdf", 500.0, number="INV-1", day=0)
    b = inv("b.eml", 500.0, number="inv 1".upper().replace(" ", "-"), day=1)
    apply_flags([a, b], CFG)
    assert b.flags == [DUPLICATE_EXACT] and b.duplicate_of == "a.pdf"
    assert "same supplier, invoice number and amount" in b.flag_reasons[0]


def test_three_copies_all_point_to_first():
    copies = [inv(f"{c}.pdf", sha="same", day=d) for c, d in (("c", 3), ("a", 0), ("b", 1))]
    apply_flags(copies, CFG)
    dup_of = {i.source_file: i.duplicate_of for i in copies}
    assert dup_of == {"a.pdf": None, "b.pdf": "a.pdf", "c.pdf": "a.pdf"}


def test_same_number_different_supplier_is_not_duplicate():
    a = inv("a.pdf", number="1001", supplier="Acme AB")
    b = inv("b.pdf", number="1001", supplier="Other AB", day=1)
    apply_flags([a, b], CFG)
    assert not a.flags and not b.flags


# ----------------------------------------------------------- near dupes --

def test_same_po_small_amount_difference_is_near_duplicate():
    a = inv("a.pdf", 1000.0, po="PO-9", day=0)
    b = inv("b.pdf", 1020.0, po="PO-9", day=6)
    apply_flags([a, b], CFG)
    assert flags_of([a, b]) == {"a.pdf": set(), "b.pdf": {DUPLICATE_NEAR}}
    assert "PO-9" in b.flag_reasons[0] and "+2.0%" in b.flag_reasons[0]


def test_same_po_large_amount_difference_is_not_flagged():
    a = inv("a.pdf", 1000.0, po="PO-9")
    b = inv("b.pdf", 1300.0, po="PO-9", day=6)   # e.g. a second partial delivery
    apply_flags([a, b], CFG)
    assert not b.flags


def test_tolerance_is_configurable():
    a = inv("a.pdf", 1000.0, po="PO-9")
    b = inv("b.pdf", 1080.0, po="PO-9", day=6)
    apply_flags([a, b], FlagConfig(near_amount_tolerance=0.10))
    assert b.flags == [DUPLICATE_NEAR]


def test_same_invoice_number_different_amount_is_near_duplicate():
    a = inv("a.pdf", 1000.0, number="INV-7")
    b = inv("b.pdf", 1500.0, number="INV-7", day=3)
    apply_flags([a, b], CFG)
    assert b.flags == [DUPLICATE_NEAR]
    assert "same invoice number INV-7" in b.flag_reasons[0]


def test_near_duplicate_ignores_different_currency():
    a = inv("a.pdf", 1000.0, po="PO-9", currency="EUR")
    b = inv("b.pdf", 1010.0, po="PO-9", currency="SEK", day=1)
    apply_flags([a, b], CFG)
    assert not b.flags


# -------------------------------------------------------- unusual amount --

def _history(amounts, **kw):
    return [inv(f"h{i}.pdf", a, day=i, **kw) for i, a in enumerate(amounts)]


def test_large_amount_is_flagged_with_reason():
    hist = _history([5200, 6100, 6400, 6900, 7300, 8100])
    big = inv("big.pdf", 59000.0, day=30)
    apply_flags(hist + [big], CFG)
    assert big.flags == [UNUSUAL_AMOUNT]
    assert "8.9x the median (6,650.00 SEK)" in big.flag_reasons[0]
    assert "IQR fence" in big.flag_reasons[0]
    assert not any(h.flags for h in hist)


def test_normal_variation_is_not_flagged():
    hist = _history([1200, 3400, 2100, 5600, 2900, 4400, 3800])
    apply_flags(hist, CFG)
    assert not any(h.flags for h in hist)


def test_above_fence_but_below_min_ratio_is_not_flagged():
    # very tight history -> tiny IQR; 1.5x the median is above the fence
    hist = _history([1000, 1001, 1002, 1003, 1004])
    x = inv("x.pdf", 1500.0, day=10)
    apply_flags(hist + [x], CFG)
    assert not x.flags


def test_small_history_uses_ratio_rule():
    hist = _history([400, 450, 500, 550])           # 4 peers: ratio rule
    x = inv("x.pdf", 4500.0, day=10)                 # 9.5x median
    apply_flags(hist + [x], CFG)
    assert x.flags == [UNUSUAL_AMOUNT]
    assert "ratio rule" in x.flag_reasons[0]


def test_too_little_history_is_not_judged():
    hist = _history([400, 450, 500])                 # 3 peers: no check
    x = inv("x.pdf", 50000.0, day=10)
    apply_flags(hist + [x], CFG)
    assert not x.flags


def test_outliers_are_per_supplier_and_currency():
    sek = _history([1000, 1100, 1200, 1300, 1400], supplier="Acme AB", currency="SEK")
    eur = inv("eur.pdf", 9000.0, supplier="Acme AB", currency="EUR", day=10)
    other = inv("other.pdf", 9000.0, supplier="Big Spender AB", day=11)
    apply_flags(sek + [eur, other], CFG)
    assert not eur.flags and not other.flags


def test_exact_duplicates_do_not_count_as_history():
    hist = _history([1000, 1100, 1200, 1300])
    copies = [inv(f"copy{i}.pdf", 1000, sha="sha-h0.pdf", day=20 + i) for i in range(3)]
    x = inv("x.pdf", 8500.0, day=40)                 # 7.7x median: under 8x small-n rule
    apply_flags(hist + copies + [x], CFG)
    assert all(c.flags == [DUPLICATE_EXACT] for c in copies)
    assert not x.flags   # would be judged by IQR on 7 peers if copies counted


# -------------------------------------------------------- missing fields --

def test_missing_fields_are_listed():
    x = Invoice("x.pdf", supplier="Acme AB", invoice_number="1", total_amount=10.0,
                currency="SEK")
    apply_flags([x], CFG)
    assert x.flags == [MISSING_FIELDS]
    assert x.flag_reasons == ["Missing field(s): invoice_date, po_number"]


def test_unreadable_file_gets_missing_fields_and_nothing_else():
    x = Invoice("broken.pdf")
    apply_flags([x], CFG)
    assert x.flags == [MISSING_FIELDS]


def test_multiple_flags_combine():
    hist = _history([5200, 6100, 6400, 6900, 7300, 8100])
    big = inv("big.pdf", 59000.0, day=30)
    big.po_number = None
    apply_flags(hist + [big], CFG)
    assert big.flags == [MISSING_FIELDS, UNUSUAL_AMOUNT]
    assert len(big.flag_reasons) == 2


def test_apply_flags_is_idempotent():
    a, b = inv("a.pdf", sha="s"), inv("b.pdf", sha="s", day=1)
    apply_flags([a, b], CFG)
    apply_flags([a, b], CFG)
    assert b.flags == [DUPLICATE_EXACT] and len(b.flag_reasons) == 1


def test_config_file_matches_code_defaults():
    assert FlagConfig.load() == FlagConfig()
