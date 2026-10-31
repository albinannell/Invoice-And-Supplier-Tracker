import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from invoice_tracker.pipeline import extract_inbox  # noqa: E402
from invoice_tracker.synthetic import generate  # noqa: E402


@pytest.fixture(scope="session")
def synthetic_inbox(tmp_path_factory):
    """A freshly generated inbox (seed 42) plus its ground truth."""
    inbox = tmp_path_factory.mktemp("inbox")
    truth = generate(inbox, seed=42)
    return inbox, {t["source_file"]: t for t in truth}


@pytest.fixture(scope="session")
def extracted(synthetic_inbox):
    inbox, _ = synthetic_inbox
    return {inv.source_file: inv for inv in extract_inbox(inbox)}
