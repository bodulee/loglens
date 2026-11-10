"""Command-line input and output; no network access or log modification."""

import argparse
import gzip
import json
import os
from pathlib import Path
import sys
import zlib

from . import __version__
from .core import Summary


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def safe_text(value: str) -> str:
    """Render untrusted log fields as terminal-safe ASCII."""
    return value.encode("unicode_escape").decode("ascii")


def text_report(report: dict) -> str:
    lines = [
        "LogLens - HTTP access log report",
        "=" * 32,
        f"Requests: {report['requests']}",
        f"Errors (4xx/5xx): {report['errors']} ({report['error_rate_percent']:.2f}%)",
        f"Response bytes (known): {report['bytes_sent']}",
        f"Unknown response sizes: {report['unknown_size_requests']}",
        f"Unique clients: {report['unique_clients']}",
        f"Lines: {report['lines_read']} | Blank: {report['blank_lines']} | Malformed: {report['malformed_lines']}",
    ]
    for title, key in (("Status codes", "status_codes"), ("Methods", "methods")):
        lines.extend(["", title])
        lines.extend(f"  {count:>8}  {safe_text(value)}" for value, count in report[key].items())
        if not report[key]:
            lines.append("  (none)")
    for title, key in (("Top paths", "top_paths"), ("Top clients", "top_clients")):
        lines.extend(["", title])
        lines.extend(f"  {item['count']:>8}  {safe_text(item['value'])}" for item in report[key])
        if not report[key]:
            lines.append("  (none)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Common/Combined HTTP access logs locally.")
    parser.add_argument("files", nargs="+", metavar="FILE", help="UTF-8 log files (.gz supported); - reads stdin")
    parser.add_argument("--top", type=positive_int, default=10, metavar="N", help="show the top N paths and clients (default: 10)")
    parser.add_argument("--json", action="store_true", help="print a machine-readable JSON report")
    parser.add_argument("--keep-query", action="store_true", help="keep query strings when grouping request targets")
    parser.add_argument("--version", action="version", version=f"LogLens {__version__}")
    args = parser.parse_args(argv)
    if args.files.count("-") > 1:
        parser.error("stdin (-) may only be specified once")

    summary = Summary(keep_query=args.keep_query)
    try:
        for name in args.files:
            if name == "-":
                if hasattr(sys.stdin, "reconfigure"):
                    sys.stdin.reconfigure(encoding="utf-8-sig", errors="strict")
                for line in sys.stdin:
                    summary.add(line)
            else:
                path = Path(name)
                opener = gzip.open if path.suffix.lower() == ".gz" else open
                with opener(path, "rt", encoding="utf-8-sig") as stream:
                    for line in stream:
                        summary.add(line)
    except (OSError, EOFError, UnicodeError, zlib.error) as error:
        print(f"loglens: cannot read input: {safe_text(str(error))}", file=sys.stderr)
        return 2

    report = summary.report(args.top)
    try:
        print(json.dumps(report, indent=2, ensure_ascii=True) if args.json else text_report(report), flush=True)
    except BrokenPipeError:
        # A consumer such as head may exit early. Redirect the descriptor so
        # Python's final buffered flush cannot raise a second exception.
        descriptor = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(descriptor, sys.stdout.fileno())
        finally:
            os.close(descriptor)
        return 0
    return 1 if summary.malformed_lines and not summary.requests else 0
