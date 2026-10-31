"""Assign a spend category to each invoice.

Order: supplier rule -> keyword vote on line items -> default.
`category_source` records which rule decided: supplier | keywords | default.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Pattern, Tuple

import yaml

from .models import Invoice

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "categories.yaml"


class Categorizer:
    def __init__(self, config_path: Path = DEFAULT_CONFIG):
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        self.by_supplier: Dict[str, str] = {
            k.casefold(): v for k, v in (cfg.get("suppliers") or {}).items()}
        self.keywords: Dict[str, List[Pattern]] = {
            cat: [re.compile(rf"\b{p}", re.I) for p in pats]
            for cat, pats in (cfg.get("keywords") or {}).items()
        }
        self.default: str = cfg.get("default", "uncategorized")

    def keyword_scores(self, items: Iterable[str]) -> Counter:
        scores: Counter = Counter()
        for item in items:
            for cat, pats in self.keywords.items():
                scores[cat] += sum(1 for p in pats if p.search(item))
        return +scores  # drop zero counts

    def classify(self, inv: Invoice) -> Tuple[str, str]:
        if inv.supplier and inv.supplier.casefold() in self.by_supplier:
            return self.by_supplier[inv.supplier.casefold()], "supplier"
        ranked = self.keyword_scores(inv.line_items).most_common()
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            return ranked[0][0], "keywords"
        return self.default, "default"

    def apply(self, invoices: Iterable[Invoice]) -> None:
        for inv in invoices:
            inv.category, inv.category_source = self.classify(inv)
