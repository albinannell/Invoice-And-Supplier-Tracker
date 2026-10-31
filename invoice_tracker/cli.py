"""Command line entry point: python -m invoice_tracker <command>."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .extract import available_extractors, get_extractor
from .pipeline import process_inbox


def cmd_run(args: argparse.Namespace) -> None:
    invoices = process_inbox(Path(args.inbox), get_extractor(args.extractor))
    cols = ["source_file", "supplier", "invoice_number", "invoice_date",
            "total_amount", "currency", "po_number", "category", "category_source"]
    print(" | ".join(cols))
    for inv in invoices:
        print(" | ".join("" if getattr(inv, c) is None else str(getattr(inv, c)) for c in cols))
    print(f"\n{len(invoices)} invoices extracted from {args.inbox}/")


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="invoice_tracker")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="process every invoice in the inbox")
    run.add_argument("--inbox", default="inbox")
    run.add_argument("--out", default="output")
    run.add_argument("--extractor", default="rules", choices=available_extractors())
    run.set_defaults(func=cmd_run)
    args = ap.parse_args(argv)
    args.func(args)
