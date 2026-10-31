"""Command line entry point: python -m invoice_tracker <command>."""
from __future__ import annotations

import argparse
import logging
from collections import Counter
from pathlib import Path

from .extract import available_extractors, get_extractor
from .flags import ALL_FLAGS
from .output import write_invoices_csv
from .pipeline import process_inbox


def cmd_run(args: argparse.Namespace) -> None:
    inbox, out = Path(args.inbox), Path(args.out)
    if not inbox.is_dir():
        raise SystemExit(f"Inbox folder not found: {inbox}/")
    invoices = process_inbox(inbox, get_extractor(args.extractor))
    csv_path = write_invoices_csv(invoices, out / "invoices.csv")

    by_cat = Counter(i.category for i in invoices)
    by_flag = Counter(f for i in invoices for f in i.flags)
    flagged = sum(1 for i in invoices if i.flags)
    print(f"Processed {len(invoices)} invoices from {inbox}/")
    print("  categories: " + ", ".join(f"{c} {n}" for c, n in by_cat.most_common()))
    print(f"  flagged:    {flagged} invoices"
          + (" (" + ", ".join(f"{f} {by_flag[f]}" for f in ALL_FLAGS if by_flag[f]) + ")"
             if flagged else ""))
    print(f"Wrote {csv_path}")


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="invoice_tracker")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="process every invoice in the inbox")
    run.add_argument("--inbox", default="inbox", help="input folder (default: inbox)")
    run.add_argument("--out", default="output", help="output folder (default: output)")
    run.add_argument("--extractor", default="rules", choices=available_extractors())
    run.set_defaults(func=cmd_run)
    args = ap.parse_args(argv)
    args.func(args)
