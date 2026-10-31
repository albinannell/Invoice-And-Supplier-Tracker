"""Flag invoices that need a human look.

Flags (an invoice can have several):
  duplicate_exact  identical file, or same supplier + invoice number + amount
                   as an invoice received earlier
  duplicate_near   same supplier + PO with an amount within tolerance, or same
                   invoice number with a different amount
  unusual_amount   high outlier versus the supplier's other invoices
  missing_fields   a required field could not be extracted

For duplicates, the earliest-received invoice is treated as the original and
only the later one(s) are flagged, with `duplicate_of` pointing back.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import yaml

from .models import Invoice

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "flags.yaml"

DUPLICATE_EXACT = "duplicate_exact"
DUPLICATE_NEAR = "duplicate_near"
UNUSUAL_AMOUNT = "unusual_amount"
MISSING_FIELDS = "missing_fields"
ALL_FLAGS = (DUPLICATE_EXACT, DUPLICATE_NEAR, UNUSUAL_AMOUNT, MISSING_FIELDS)


@dataclass
class FlagConfig:
    near_amount_tolerance: float = 0.05
    min_peers_iqr: int = 5
    iqr_k: float = 3.0
    min_ratio: float = 4.0
    min_peers_ratio: int = 4
    small_n_ratio: float = 8.0

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG) -> "FlagConfig":
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        merged = {**(cfg.get("duplicates") or {}), **(cfg.get("unusual_amount") or {})}
        return cls(**{k: v for k, v in merged.items() if k in cls.__dataclass_fields__})


def apply_flags(invoices: List[Invoice], cfg: Optional[FlagConfig] = None) -> List[Invoice]:
    cfg = cfg or FlagConfig.load()
    for inv in invoices:
        inv.flags, inv.flag_reasons, inv.duplicate_of = [], [], None
    flag_missing_fields(invoices)
    ordered = sorted(invoices, key=_arrival_key)
    flag_exact_duplicates(ordered)
    flag_near_duplicates(ordered, cfg)
    flag_unusual_amounts(invoices, cfg)
    return invoices


# ---------------------------------------------------------------- helpers --

_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


def _arrival_key(inv: Invoice) -> Tuple:
    received = inv.received_at or _FAR_FUTURE
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    return (received, inv.invoice_date or date.max, inv.source_file)


def _norm(s: Optional[str]) -> Optional[str]:
    return re.sub(r"\s+", "", s).casefold() if s else None


def _money(x: float, cur: Optional[str]) -> str:
    return f"{x:,.2f} {cur or ''}".strip()


# ----------------------------------------------------------------- checks --

def flag_missing_fields(invoices: Iterable[Invoice]) -> None:
    for inv in invoices:
        missing = inv.missing_fields()
        if missing:
            inv.add_flag(MISSING_FIELDS, "Missing field(s): " + ", ".join(missing))


def flag_exact_duplicates(ordered: List[Invoice]) -> None:
    seen: Dict[Tuple, Invoice] = {}
    for inv in ordered:
        keys = []
        if inv.sha256:
            keys.append(("file", inv.sha256))
        if inv.supplier and inv.invoice_number and inv.total_amount is not None:
            keys.append(("content", _norm(inv.supplier), _norm(inv.invoice_number),
                         round(inv.total_amount, 2), inv.currency))
        hit = next(((k, seen[k]) for k in keys if k in seen), None)
        if hit:
            key, orig = hit
            how = ("identical file" if key[0] == "file"
                   else "same supplier, invoice number and amount")
            inv.duplicate_of = orig.source_file
            inv.add_flag(DUPLICATE_EXACT, f"Exact duplicate of {orig.source_file} ({how})")
        else:
            for k in keys:
                seen[k] = inv


def flag_near_duplicates(ordered: List[Invoice], cfg: FlagConfig) -> None:
    earlier: List[Invoice] = []
    for inv in ordered:
        if DUPLICATE_EXACT in inv.flags:
            continue
        match = _find_near_match(inv, earlier, cfg)
        if match:
            other, why = match
            inv.duplicate_of = other.source_file
            inv.add_flag(DUPLICATE_NEAR, f"Possible duplicate of {other.source_file}: {why}")
        earlier.append(inv)


def _find_near_match(inv: Invoice, earlier: List[Invoice],
                     cfg: FlagConfig) -> Optional[Tuple[Invoice, str]]:
    if not inv.supplier or inv.total_amount is None:
        return None
    for o in earlier:
        if (_norm(o.supplier) != _norm(inv.supplier) or o.currency != inv.currency
                or o.total_amount is None):
            continue
        a, b = o.total_amount, inv.total_amount
        diff = (b - a) / a * 100 if a else float("inf")
        amounts = f"{_money(b, inv.currency)} vs {_money(a, o.currency)} ({diff:+.1f}%)"
        if inv.invoice_number and _norm(o.invoice_number) == _norm(inv.invoice_number):
            return o, f"same invoice number {inv.invoice_number}, amount {amounts}"
        if (inv.po_number and _norm(o.po_number) == _norm(inv.po_number)
                and abs(b - a) <= cfg.near_amount_tolerance * max(abs(a), abs(b))):
            return o, f"same supplier and PO {inv.po_number}, amount {amounts}"
    return None


def flag_unusual_amounts(invoices: List[Invoice], cfg: FlagConfig) -> None:
    groups: Dict[Tuple, List[Invoice]] = {}
    for inv in invoices:
        if inv.total_amount is None or not inv.supplier or DUPLICATE_EXACT in inv.flags:
            continue
        groups.setdefault((_norm(inv.supplier), inv.currency), []).append(inv)

    for members in groups.values():
        for inv in members:
            peers = [m.total_amount for m in members if m is not inv]
            reason = _outlier_reason(inv, peers, cfg)
            if reason:
                inv.add_flag(UNUSUAL_AMOUNT, reason)


def _outlier_reason(inv: Invoice, peers: List[float], cfg: FlagConfig) -> Optional[str]:
    amt, cur = inv.total_amount, inv.currency
    if len(peers) < cfg.min_peers_ratio:
        return None
    med = statistics.median(peers)
    if med <= 0:
        return None
    ratio = amt / med
    base = (f"Amount {_money(amt, cur)} is {ratio:.1f}x the median "
            f"({_money(med, cur)}) of {len(peers)} other {inv.supplier} invoices")
    if len(peers) >= cfg.min_peers_iqr:
        q1, _, q3 = statistics.quantiles(peers, n=4, method="inclusive")
        fence = q3 + cfg.iqr_k * (q3 - q1)
        if amt > fence and ratio >= cfg.min_ratio:
            return f"{base}; above IQR fence {_money(fence, cur)}"
        return None
    if ratio > cfg.small_n_ratio:
        return f"{base}; few invoices, so ratio rule (> {cfg.small_n_ratio:g}x) used"
    return None
