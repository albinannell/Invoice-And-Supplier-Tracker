from .base import Extractor, available_extractors, get_extractor, register
from .loaders import iter_inbox, load, load_text
from .rules import RuleBasedExtractor

register("rules", RuleBasedExtractor)

__all__ = ["Extractor", "RuleBasedExtractor", "available_extractors", "get_extractor",
           "register", "iter_inbox", "load", "load_text"]
