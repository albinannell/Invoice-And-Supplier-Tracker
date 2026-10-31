"""Write invoices to CSV."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, List

from .models import Invoice


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


# column name -> how to get it from an Invoice
INVOICE_COLUMNS: Dict[str, Callable[[Invoice], object]] = {
    "source_file": lambda i: i.source_file,
    "supplier": lambda i: i.supplier,
    "supplier_known": lambda i: i.supplier_known,
    "invoice_number": lambda i: i.invoice_number,
    "invoice_date": lambda i: i.invoice_date,
    "total_amount": lambda i: i.total_amount,
    "currency": lambda i: i.currency,
    "po_number": lambda i: i.po_number,
    "category": lambda i: i.category,
    "category_source": lambda i: i.category_source,
    "line_items": lambda i: " | ".join(i.line_items),
    "flags": lambda i: "; ".join(i.flags),
    "flag_reasons": lambda i: " | ".join(i.flag_reasons),
    "duplicate_of": lambda i: i.duplicate_of,
    "extractor": lambda i: i.extractor,
}


def invoice_rows(invoices: Iterable[Invoice]) -> List[Dict[str, str]]:
    return [{col: _fmt(get(inv)) for col, get in INVOICE_COLUMNS.items()} for inv in invoices]


def write_csv(rows: List[Dict[str, str]], path: Path, columns: List[str]) -> Path:
    """Write rows as CSV (UTF-8 with BOM so Excel shows å/ä/ö/Ü correctly)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    return path


def write_invoices_csv(invoices: Iterable[Invoice], path: Path) -> Path:
    return write_csv(invoice_rows(invoices), path, list(INVOICE_COLUMNS))
