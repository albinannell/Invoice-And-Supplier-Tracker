"""Locale-tolerant parsing of amounts and dates."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

CURRENCY_CODES = ("SEK", "EUR", "USD", "GBP", "NOK", "DKK", "CHF")
CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

_AMOUNT_RE = re.compile(r"-?\d[\d\s  .,']*")


def parse_amount(s: str) -> Optional[float]:
    """Parse '1 234,50', '1.234,50', '1,234.50', 'EUR 99.00', '$2,912.02'...

    Rules: whitespace and apostrophes are thousands separators. If both '.'
    and ',' appear, the last one is the decimal mark. If only one kind
    appears, it's a decimal mark when followed by 1-2 digits at the end,
    otherwise a thousands separator.
    """
    if s is None:
        return None
    m = _AMOUNT_RE.search(s)
    if not m:
        return None
    num = re.sub(r"[\s  ']", "", m.group(0)).rstrip(".,")
    if not num or num == "-":
        return None
    if "," in num and "." in num:
        dec = "," if num.rfind(",") > num.rfind(".") else "."
        thou = "." if dec == "," else ","
        num = num.replace(thou, "").replace(dec, ".")
    elif "," in num or "." in num:
        sep = "," if "," in num else "."
        head, _, tail = num.rpartition(sep)
        if num.count(sep) == 1 and 1 <= len(tail) <= 2:
            num = head + "." + tail
        else:
            num = num.replace(sep, "")
    try:
        return round(float(num), 2)
    except ValueError:
        return None


def detect_currency(s: str) -> Optional[str]:
    up = s.upper()
    for code in CURRENCY_CODES:
        if re.search(rf"\b{code}\b", up):
            return code
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in s:
            return code
    if re.search(r"\d\s*kr\b|\bkr\s*\d", s, re.I):
        return "SEK"
    return None


_MONTHS = {
    # English
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    # Swedish
    "januari": 1, "februari": 2, "mars": 3, "maj": 5, "juni": 6, "juli": 7,
    "augusti": 8, "okt": 10, "oktober": 10,
    # German
    "januar": 1, "februar": 2, "märz": 3, "mai": 5, "okt.": 10, "dez": 12, "dezember": 12,
}


def _mk(y: int, m: int, d: int) -> Optional[date]:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(s: str, order: str = "dmy") -> Optional[date]:
    """Parse ISO, '06 Aug 2026', '7 juli 2026', 'Aug 6, 2026', '29.05.2026',
    '05/04/2026'. For ambiguous a/b/yyyy, `order` ('dmy' or 'mdy') decides
    unless one component is > 12.
    """
    if not s:
        return None
    s = s.strip()
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})\.?\s+([A-Za-zäöåÄÖÅ]{3,9}\.?)\s+(\d{4})\b", s)
    if m and m.group(2).lower() in _MONTHS:
        return _mk(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", s)
    if m and m.group(1).lower() in _MONTHS:
        return _mk(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.search(r"\b(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})\b", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        if m.group(2) == ".":          # dotted dates are day-first everywhere
            return _mk(y, b, a)
        if a > 12:
            return _mk(y, b, a)
        if b > 12:
            return _mk(y, a, b)
        return _mk(y, a, b) if order == "mdy" else _mk(y, b, a)
    return None
