"""Extractor interface.

An extractor turns one RawDocument into one Invoice. It must not raise for a
missing field — leave it as None; the flags stage reports missing fields.

To add an LLM-based extractor later:

    class LLMExtractor:
        name = "llm"
        def extract(self, doc: RawDocument) -> Invoice:
            ...  # send doc.text to the model, map JSON -> Invoice

    register("llm", LLMExtractor)

and run with `python -m invoice_tracker run --extractor llm`.
"""
from __future__ import annotations

from typing import Callable, Dict

try:  # Python 3.8+
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

from ..models import Invoice, RawDocument


class Extractor(Protocol):
    name: str

    def extract(self, doc: RawDocument) -> Invoice: ...


_REGISTRY: Dict[str, Callable[[], Extractor]] = {}


def register(name: str, factory: Callable[[], Extractor]) -> None:
    _REGISTRY[name] = factory


def get_extractor(name: str = "rules") -> Extractor:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown extractor {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def available_extractors():
    return sorted(_REGISTRY)
