"""Core data types shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


@dataclass
class Segment:
    """A run of words on one line, separated from neighbours by a wide gap.

    Coordinates are in PDF points from the top-left; text-only documents
    (e.g. an email body) get synthetic coordinates so the same lookup logic
    works for both.
    """
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class Line:
    segments: List[Segment]

    @property
    def text(self) -> str:
        return "  ".join(s.text for s in self.segments)

    @property
    def bottom(self) -> float:
        return max(s.bottom for s in self.segments)


@dataclass
class RawDocument:
    """What a loader hands to an extractor: one invoice's content."""
    source_file: str
    text: str                          # plain text, for text-based/LLM extractors
    lines: List[Line] = field(default_factory=list)  # layout-aware view
    sha256: Optional[str] = None       # hash of the underlying PDF/text bytes
    origin: str = "pdf"                # pdf | eml-attachment | eml-body
    received_at: Optional[datetime] = None  # email Date header, else file mtime


@dataclass
class Invoice:
    source_file: str
    supplier: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    po_number: Optional[str] = None
    line_items: List[str] = field(default_factory=list)
    supplier_known: bool = False       # matched a configured supplier?
    sha256: Optional[str] = None
    received_at: Optional[datetime] = None
    extractor: str = ""
    # filled by later stages
    category: Optional[str] = None
    category_source: Optional[str] = None
    flags: List[str] = field(default_factory=list)
    flag_reasons: List[str] = field(default_factory=list)
    duplicate_of: Optional[str] = None  # source_file of the original, if a duplicate

    def add_flag(self, flag: str, reason: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)
        self.flag_reasons.append(reason)

    REQUIRED_FIELDS = ("supplier", "invoice_number", "invoice_date",
                       "total_amount", "currency", "po_number")

    def missing_fields(self) -> List[str]:
        return [f for f in self.REQUIRED_FIELDS if getattr(self, f) in (None, "")]
