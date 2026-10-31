"""Generate synthetic invoices into inbox/ (or a folder of your choice).

    python scripts/generate_invoices.py [--out inbox] [--seed 42]
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from invoice_tracker.synthetic import generate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="inbox", help="output folder (default: inbox)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    truth = generate(Path(args.out), seed=args.seed)
    planted = Counter(p for t in truth for p in t["planted"])
    exts = Counter(Path(t["source_file"]).suffix for t in truth)
    print(f"Wrote {len(truth)} invoices to {args.out}/ ({dict(exts)})")
    print(f"Suppliers: {len({t['supplier'] for t in truth})}")
    print(f"Planted problems: {dict(planted)}")


if __name__ == "__main__":
    main()
