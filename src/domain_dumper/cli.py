"""Command-line interface: ``python -m domain_dumper.cli`` or ``domain-dumper``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import DEFAULT_OUTPUT, FORMATS, Config
from .exceptions import EXIT_USAGE, DomainDumperError, UsageError
from .pipeline import run

EPILOG = """\
exit codes:
  0  success
  1  finished, but with recoverable input errors or untouched conflicting files
  2  invalid or incompatible arguments
  3  no usable input could be read
  4  output could not be written
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domain-dumper",
        description=(
            "Extract, normalize and deduplicate domain names from files, directories or "
            "standard input, writing one text file per domain."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        action="append",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="input file or directory; repeatable, and accepts several paths at once",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--stdin", action="store_true", help="also read input piped on stdin")
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default="auto",
        help="force a parser for all inputs (default: auto, by file extension; stdin is txt)",
    )
    parser.add_argument(
        "--recursive", action="store_true", help="search input directories recursively"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing domain files whose content differs (default: leave them)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="extract and validate, report what would change, write nothing",
    )
    parser.add_argument("--quiet", action="store_true", help="only print warnings and errors")
    parser.add_argument("--verbose", action="store_true", help="print diagnostic details")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def configure_logging(*, quiet: bool, verbose: bool) -> None:
    """INFO and below go to stdout, WARNING and above to stderr."""
    logger = logging.getLogger("domain_dumper")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO)
    formatter = logging.Formatter("[%(levelname)s] %(message)s")

    out = logging.StreamHandler(sys.stdout)
    out.addFilter(lambda record: record.levelno < logging.WARNING)
    out.setFormatter(formatter)
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.WARNING)
    err.setFormatter(formatter)
    logger.addHandler(out)
    logger.addHandler(err)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits for --help, --version and bad arguments
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE

    configure_logging(quiet=args.quiet, verbose=args.verbose)
    log = logging.getLogger("domain_dumper.cli")
    config = Config(
        inputs=tuple(path for group in (args.input or []) for path in group),
        output=args.output,
        use_stdin=args.stdin,
        fmt=args.format,
        recursive=args.recursive,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        quiet=args.quiet,
        verbose=args.verbose,
    )
    try:
        config.validate()
        if config.use_stdin and _stdin_is_terminal():
            raise UsageError("--stdin needs piped input, but stdin is an interactive terminal")
        return run(config).exit_code
    except DomainDumperError as exc:
        log.error("%s", exc)
        return exc.exit_code
    except KeyboardInterrupt:
        log.error("Interrupted")
        return 130


def _stdin_is_terminal() -> bool:
    isatty = getattr(sys.stdin, "isatty", None)
    return bool(isatty and isatty())


if __name__ == "__main__":
    raise SystemExit(main())
