"""Glue: inbox -> RawDocuments -> Invoices."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from .categorize import Categorizer
from .extract import Extractor, get_extractor, iter_inbox, load
from .models import Invoice

log = logging.getLogger(__name__)


def extract_inbox(inbox: Path, extractor: Optional[Extractor] = None) -> List[Invoice]:
    extractor = extractor or get_extractor("rules")
    invoices: List[Invoice] = []
    for path in iter_inbox(Path(inbox)):
        try:
            docs = load(path)
        except Exception as exc:  # unreadable file: record it, keep going
            log.warning("Could not read %s: %s", path.name, exc)
            invoices.append(Invoice(source_file=path.name, extractor=extractor.name))
            continue
        for doc in docs:
            invoices.append(extractor.extract(doc))
    return invoices


def process_inbox(inbox: Path, extractor: Optional[Extractor] = None,
                  categorizer: Optional[Categorizer] = None) -> List[Invoice]:
    """Extract and categorize every invoice in the inbox."""
    invoices = extract_inbox(inbox, extractor)
    (categorizer or Categorizer()).apply(invoices)
    return invoices
