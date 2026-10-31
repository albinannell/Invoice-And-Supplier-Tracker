"""Rule-based extractor: label-anchored lookup on the document layout.

For each field we find a segment whose whole text is a known label (e.g.
"Invoice No.", "Fakturadatum:"), then take the value from
  1. the next segment to the right on the same line, or
  2. the segment directly below it (for "labels above values" layouts).
Each candidate value is validated (dates must parse, totals must be amounts,
etc.); if it fails, the next candidate is tried.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Pattern, Tuple

import yaml

from ..models import Invoice, Line, RawDocument, Segment
from .parsing import detect_currency, parse_amount, parse_date

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "extraction.yaml"

BELOW_MAX_DISTANCE = 30.0   # points: how far below a label to look for its value
BELOW_X_TOLERANCE = 15.0    # points: horizontal alignment tolerance for "below"


@dataclass
class SupplierInfo:
    name: str
    needles: List[str]       # lowercase strings that identify the supplier
    date_order: str = "dmy"
    currency: Optional[str] = None


class RuleBasedExtractor:
    name = "rules"

    def __init__(self, config_path: Path = DEFAULT_CONFIG):
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        self.labels: Dict[str, List[Pattern]] = {
            field: [re.compile(rf"^(?:{p})\s*:?$", re.I) for p in pats]
            for field, pats in cfg["labels"].items()
        }
        self.suppliers = [
            SupplierInfo(
                name=s["name"],
                needles=[a.lower() for a in [s["name"], *s.get("aliases", []),
                                             *s.get("email_domains", [])]],
                date_order=s.get("date_order", "dmy"),
                currency=s.get("currency"),
            )
            for s in cfg.get("suppliers", [])
        ]
        self.buyer_aliases = [b.lower() for b in cfg.get("buyer_aliases", [])]

    # ------------------------------------------------------------ public --

    def extract(self, doc: RawDocument) -> Invoice:
        sup = self._match_supplier(doc)
        order = sup.date_order if sup else "dmy"

        inv = Invoice(source_file=doc.source_file, sha256=doc.sha256, extractor=self.name)
        inv.supplier = sup.name if sup else self._guess_supplier_name(doc)
        inv.supplier_known = sup is not None
        inv.invoice_number = self._find(doc, "invoice_number", _clean_identifier)
        inv.invoice_date = self._find(doc, "invoice_date", lambda v: parse_date(v, order))
        inv.po_number = self._find(doc, "po_number", _clean_identifier)

        total = self._find(doc, "total_amount", _amount_with_text)
        if total is not None:
            inv.total_amount, total_text = total
            inv.currency = detect_currency(total_text)
        if inv.currency is None:
            inv.currency = detect_currency(doc.text) or (sup.currency if sup else None)

        inv.line_items = self._line_items(doc)
        return inv

    # ---------------------------------------------------------- supplier --

    def _match_supplier(self, doc: RawDocument) -> Optional[SupplierInfo]:
        low = doc.text.lower()
        best: Optional[Tuple[int, SupplierInfo]] = None
        for s in self.suppliers:
            for needle in s.needles:
                i = low.find(needle)
                if i >= 0 and (best is None or i < best[0]):
                    best = (i, s)  # earliest mention wins (letterhead is on top)
        return best[1] if best else None

    def _guess_supplier_name(self, doc: RawDocument) -> Optional[str]:
        """Unknown supplier: take the first plausible name-like segment."""
        for line in doc.lines[:8]:
            for seg in line.segments:
                t = seg.text.strip()
                low = t.lower()
                if (len(t) < 3 or any(b in low for b in self.buyer_aliases)
                        or re.fullmatch(r"(invoice|faktura|rechnung|bill to:?|from:.*)\b.*", low)
                        or not re.search(r"[A-Za-z]{3}", t)):
                    continue
                if low.startswith("from:"):
                    t = re.sub(r"(?i)^from:\s*", "", t).split("<")[0].strip()
                return t or None
        return None

    # ------------------------------------------------------------ fields --

    def _label_hits(self, doc: RawDocument, field: str) -> Iterator[Tuple[int, int, Segment]]:
        """Yield (line_idx, seg_idx, segment) for label matches, best pattern first."""
        for pat in self.labels.get(field, []):
            for li, line in enumerate(doc.lines):
                for si, seg in enumerate(line.segments):
                    if pat.match(seg.text.strip()):
                        yield li, si, seg

    def _candidates(self, doc: RawDocument, li: int, si: int, label: Segment) -> Iterator[str]:
        line = doc.lines[li]
        if si + 1 < len(line.segments):           # value to the right
            yield line.segments[si + 1].text
        for nxt in doc.lines[li + 1:]:             # value below
            if nxt.bottom - label.bottom > BELOW_MAX_DISTANCE:
                break
            for seg in nxt.segments:
                if abs(seg.x0 - label.x0) <= BELOW_X_TOLERANCE:
                    yield seg.text
                    break

    def _find(self, doc: RawDocument, field: str, validate: Callable[[str], object]):
        for li, si, label in self._label_hits(doc, field):
            for cand in self._candidates(doc, li, si, label):
                val = validate(cand)
                if val is not None:
                    return val
        return None

    # -------------------------------------------------------- line items --

    def _line_items(self, doc: RawDocument) -> List[str]:
        items: List[str] = []
        start = None
        for li, line in enumerate(doc.lines):
            if line.segments and any(p.match(line.segments[0].text.strip())
                                     for p in self.labels.get("line_items_header", [])):
                start = li + 1
                break
        if start is None:
            return items
        end_pats = self.labels.get("line_items_end", []) + self.labels.get("total_amount", [])
        for line in doc.lines[start:]:
            first = line.segments[0].text.strip()
            if any(p.match(first) for p in end_pats):
                break
            if len(line.segments) >= 2 and parse_amount(line.segments[-1].text) is not None:
                items.append(first)
        return items


# ------------------------------------------------------------ validators --

def _clean_identifier(v: str) -> Optional[str]:
    v = v.strip().strip(":").strip()
    # identifiers contain a digit and are short, single-ish tokens
    if not re.search(r"\d", v) or len(v) > 30 or parse_date(v):
        return None
    return v


def _amount_with_text(v: str) -> Optional[Tuple[float, str]]:
    amt = parse_amount(v)
    return (amt, v) if amt is not None else None
