"""Command line entry point.

`probe` loads the config, runs the probe in a temp work directory, prints the
table to stdout, writes the JSON report, and exits non-zero if any undeclared
channel was found. The work directory is deleted unless --keep-work is given.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from . import __version__, surfaces  # noqa: F401  (imported for adapter registration)
from .config import ConfigError, load
from .probe import run_probe

DEFAULT_REPORT_PATH = "runprobe-report.json"

# Exit codes:
#   0  probe ran and found no undeclared channel
#   1  probe ran and found a FAIL or an ERROR
#   2  probe could not run (bad config, or the report could not be written)
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CANNOT_RUN = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runprobe",
        description=(
            "Probe whether one supposedly isolated agent run can leave information "
            "where another supposedly isolated run can recover it."
        ),
    )
    parser.add_argument("--version", action="version", version=f"runprobe {__version__}")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    probe = subparsers.add_parser(
        "probe",
        help="run a cross-run isolation probe over the configured surfaces",
    )
    probe.add_argument(
        "--config",
        required=True,
        metavar="PATH",
        help="path to surfaces.json",
    )
    probe.add_argument(
        "--report",
        default=DEFAULT_REPORT_PATH,
        metavar="PATH",
        help=f"path to write the JSON report (default: {DEFAULT_REPORT_PATH})",
    )
    probe.add_argument(
        "--keep-work",
        action="store_true",
        help="print the work directory and leave it in place instead of deleting it",
    )
    probe.set_defaults(func=cmd_probe)

    return parser


def cmd_probe(args: argparse.Namespace) -> int:
    try:
        config = load(args.config)
    except ConfigError as exc:
        print(f"runprobe: config error: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    work = Path(tempfile.mkdtemp(prefix="runprobe-"))
    try:
        report = run_probe(config, work)
    finally:
        if args.keep_work:
            print(f"runprobe: work directory kept at {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    print(report.to_table())

    report_path = Path(args.report)
    try:
        report_path.write_text(report.to_json() + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"runprobe: could not write report to {report_path}: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    print(f"runprobe: report written to {report_path}", file=sys.stderr)
    return report.exit_code()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        return EXIT_CANNOT_RUN

    result = args.func(args)
    return int(result)


if __name__ == "__main__":
    sys.exit(main())
