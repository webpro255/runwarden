"""Command line entry point.

Phase 0 has no surface adapters, so `probe` validates the config and then stops
with exit code 2. That is deliberate: a probe that reports PASS without having
probed anything would be worse than no probe at all.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .config import ConfigError, load

DEFAULT_REPORT_PATH = "runprobe-report.json"

# Exit codes:
#   0  probe ran and found no undeclared channel
#   1  probe ran and found a FAIL or an ERROR
#   2  probe could not run (bad config, no adapters registered)
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
    probe.set_defaults(func=cmd_probe)

    return parser


def cmd_probe(args: argparse.Namespace) -> int:
    try:
        config = load(args.config)
    except ConfigError as exc:
        print(f"runprobe: config error: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    # Unreachable while SURFACE_TYPES is empty, since config.load rejects every
    # type before it gets here. Kept so the failure mode is explicit once the
    # registry is populated in Phase 1.
    print(f"runprobe: loaded {len(config.surfaces)} surface(s) from {args.config}")
    print("no adapters registered", file=sys.stderr)
    return EXIT_CANNOT_RUN


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
