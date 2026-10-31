"""Monthly spend summary (CSV) and a short readable report (Markdown).

Spend rules:
- Exact duplicates are excluded (they'd double-count the same invoice).
- Near-duplicates are *included* (they may be legitimate) but called out.
- Amounts are never converted between currencies; everything is grouped by
  currency.
- An invoice without an invoice date is placed in the month it was received.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .flags import DUPLICATE_EXACT, DUPLICATE_NEAR, UNUSUAL_AMOUNT
from .models import Invoice
from .output import write_csv

SUMMARY_COLUMNS = ["month", "supplier", "category", "currency",
                   "invoice_count", "total_spend", "flagged_count"]


@dataclass
class SummaryRow:
    month: str
    supplier: str
    category: str
    currency: str
    invoice_count: int = 0
    total_spend: float = 0.0
    flagged_count: int = 0


def invoice_month(inv: Invoice) -> Tuple[str, bool]:
    """Return (YYYY-MM, from_received_date)."""
    if inv.invoice_date:
        return inv.invoice_date.strftime("%Y-%m"), False
    if inv.received_at:
        return inv.received_at.strftime("%Y-%m"), True
    return "unknown", True


def counted(invoices: List[Invoice]) -> List[Invoice]:
    """Invoices that count towards spend."""
    return [i for i in invoices
            if DUPLICATE_EXACT not in i.flags and i.total_amount is not None]


def monthly_summary(invoices: List[Invoice]) -> List[SummaryRow]:
    rows: Dict[Tuple[str, str, str, str], SummaryRow] = {}
    for inv in counted(invoices):
        month, _ = invoice_month(inv)
        key = (month, inv.supplier or "(unknown supplier)",
               inv.category or "uncategorized", inv.currency or "???")
        row = rows.setdefault(key, SummaryRow(*key))
        row.invoice_count += 1
        row.total_spend = round(row.total_spend + inv.total_amount, 2)
        row.flagged_count += bool(inv.flags)
    return sorted(rows.values(), key=lambda r: (r.month, r.currency, r.category, r.supplier))


def write_summary_csv(rows: List[SummaryRow], path: Path) -> Path:
    data = [{"month": r.month, "supplier": r.supplier, "category": r.category,
             "currency": r.currency, "invoice_count": str(r.invoice_count),
             "total_spend": f"{r.total_spend:.2f}", "flagged_count": str(r.flagged_count)}
            for r in rows]
    return write_csv(data, path, SUMMARY_COLUMNS)


# ------------------------------------------------------------------ report --

def _amt(x: float) -> str:
    return f"{x:,.0f}"


def _table(header: List[str], rows: List[List[str]], right_from: int = 1) -> List[str]:
    align = ["---" if i < right_from else "---:" for i in range(len(header))]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def _pivot(rows: List[SummaryRow], key) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        out[key(r)][r.currency] += r.total_spend
    return out


def build_report(invoices: List[Invoice], rows: List[SummaryRow],
                 today: Optional[date] = None, top_n: int = 5) -> str:
    today = today or date.today()
    used = counted(invoices)
    excluded = [i for i in invoices if DUPLICATE_EXACT in i.flags]
    no_amount = [i for i in invoices if i.total_amount is None and DUPLICATE_EXACT not in i.flags]
    currencies = sorted({r.currency for r in rows})
    months = sorted({r.month for r in rows})
    flagged = [i for i in invoices if i.flags]
    undated = [i for i in used if invoice_month(i)[1]]

    L: List[str] = ["# Invoice spend report", ""]
    period = f"{months[0]} to {months[-1]}" if months else "no invoices"
    L.append(f"Generated {today.isoformat()} · period {period} · "
             f"{len(invoices)} invoices processed, {len(used)} counted towards spend.")
    L.append("")

    # --- headline
    totals = _pivot(rows, lambda r: "all")["all"] if rows else {}
    L += ["## Totals", ""]
    L += _table(["Currency", "Spend", "Invoices"],
                [[c, _amt(totals[c]),
                  str(sum(r.invoice_count for r in rows if r.currency == c))]
                 for c in currencies])
    L.append("")

    # --- by month
    by_month = _pivot(rows, lambda r: r.month)
    L += ["## Spend by month", ""]
    L += _table(["Month", *currencies],
                [[m, *[_amt(by_month[m][c]) if by_month[m].get(c) else "–" for c in currencies]]
                 for m in months])
    L.append("")

    # --- by category
    by_cat = _pivot(rows, lambda r: r.category)
    L += ["## Spend by category", ""]
    L += _table(["Category", *currencies],
                [[cat, *[_amt(by_cat[cat][c]) if by_cat[cat].get(c) else "–" for c in currencies]]
                 for cat in sorted(by_cat)])
    L.append("")

    # --- top suppliers (per currency, since amounts aren't comparable across)
    sup: Dict[Tuple[str, str, str], List[float]] = defaultdict(lambda: [0.0, 0])
    for r in rows:
        s = sup[(r.supplier, r.category, r.currency)]
        s[0] += r.total_spend
        s[1] += r.invoice_count
    L += ["## Top suppliers", ""]
    top_rows = []
    for c in currencies:
        ranked = sorted(((k, v) for k, v in sup.items() if k[2] == c), key=lambda kv: -kv[1][0])
        for (name, cat, cur), (spend, n) in ranked[:top_n]:
            share = spend / totals[c] * 100 if totals.get(c) else 0
            top_rows.append([name, cat, cur, _amt(spend), f"{share:.0f}%", str(int(n))])
    L += _table(["Supplier", "Category", "Currency", "Spend", "Share", "Invoices"],
                top_rows, right_from=3)
    L.append("")

    # --- flagged
    L += [f"## Flagged invoices ({len(flagged)})", ""]
    if flagged:
        order = {DUPLICATE_EXACT: 0, DUPLICATE_NEAR: 1, UNUSUAL_AMOUNT: 2}
        for i in sorted(flagged, key=lambda i: (min(order.get(f, 9) for f in i.flags),
                                                i.source_file)):
            amount = f"{i.total_amount:,.2f} {i.currency or ''}".strip() \
                if i.total_amount is not None else "no amount"
            L.append(f"- **{i.source_file}** — {i.supplier or 'unknown supplier'}, "
                     f"{amount} · `{', '.join(i.flags)}`")
            for reason in i.flag_reasons:
                L.append(f"  - {reason}")
    else:
        L.append("None.")
    L.append("")

    # --- notes
    notes = []
    if excluded:
        dup_total = defaultdict(float)
        for i in excluded:
            if i.total_amount is not None:
                dup_total[i.currency] += i.total_amount
        notes.append(f"{len(excluded)} exact duplicate(s) excluded from spend ("
                     + ", ".join(f"{_amt(v)} {c}" for c, v in sorted(dup_total.items()))
                     + ").")
    near = [i for i in used if DUPLICATE_NEAR in i.flags]
    if near:
        notes.append(f"{len(near)} possible duplicate(s) are *included* in spend "
                     "until reviewed.")
    unusual = [i for i in used if UNUSUAL_AMOUNT in i.flags]
    if unusual:
        notes.append(f"{len(unusual)} unusually large invoice(s) are *included* in spend "
                     "and may dominate their month: "
                     + ", ".join(f"{_amt(i.total_amount)} {i.currency} in {invoice_month(i)[0]}"
                                 for i in unusual) + ".")
    if undated:
        notes.append(f"{len(undated)} invoice(s) without an invoice date are placed in "
                     "the month they were received: "
                     + ", ".join(i.source_file for i in undated) + ".")
    if no_amount:
        notes.append(f"{len(no_amount)} invoice(s) with no readable total are not in "
                     "spend: " + ", ".join(i.source_file for i in no_amount) + ".")
    if len(currencies) > 1:
        notes.append("Amounts are shown per currency; nothing is converted.")
    L += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    return "\n".join(L)


def write_report(invoices: List[Invoice], rows: List[SummaryRow], path: Path,
                 today: Optional[date] = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(invoices, rows, today), encoding="utf-8")
    return path
