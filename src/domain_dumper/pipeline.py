"""Orchestrates one run: read -> extract -> normalize -> validate -> dedupe -> write."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config
from .deduplicator import Deduplicator
from .exceptions import EXIT_OK, EXIT_OUTPUT, EXIT_WARNING, InputError
from .extractor import extract_hosts
from .manifest import render_manifest, scan_recorded_domains
from .normalizer import normalize_host
from .reporting import ExtractionStats, build_summary, render_summary
from .sources import discover_inputs, read_fragments, source_format
from .validator import validate_domain
from .writer import (
    DOMAINS_DIRNAME,
    WriteResult,
    ensure_directories,
    write_domain_files,
    write_manifest,
    write_summary,
)

log = logging.getLogger(__name__)
STDIN_NAME = "<stdin>"
_MAX_LOGGED_FAILURES = 10


@dataclass
class RunResult:
    """What a run did. ``summary`` is ``None`` for a dry run (nothing is reported to disk)."""

    domains: list[str]
    stats: ExtractionStats
    write: WriteResult
    summary: dict[str, Any] | None
    exit_code: int


def run(config: Config, *, now: datetime | None = None) -> RunResult:
    """Execute a run. Raises :class:`InputError` / :class:`OutputError` for fatal problems."""
    log.info("Starting domain extraction")
    sources, problems = discover_inputs(
        config.inputs, recursive=config.recursive, exclude_dir=config.output
    )
    stats = ExtractionStats()
    for source, message in problems:
        stats.record_input_error(source, message)
        log.warning("%s: %s", source, message)

    targets: list[Path | None] = list(sources)
    if config.use_stdin:
        targets.append(None)

    dedup = Deduplicator()
    for path in targets:
        _process_source(path, config, stats, dedup)

    if stats.input_files_processed == 0:
        detail = "; ".join(f"{e['source']}: {e['message']}" for e in stats.input_errors)
        raise InputError(f"no input could be read ({detail or 'no input sources'})")

    domains = dedup.sorted_domains()
    stats.valid_unique = dedup.unique_count
    stats.duplicates = dedup.duplicates
    _log_extraction(stats)

    domains_dir = config.output / DOMAINS_DIRNAME
    if not config.dry_run:
        ensure_directories(config.output)
    write = write_domain_files(
        domains_dir, domains, overwrite=config.overwrite, dry_run=config.dry_run
    )
    _log_writes(write, config)

    summary = None
    if not config.dry_run:
        entries = scan_recorded_domains(domains_dir)
        manifest_changed = write_manifest(config.output, render_manifest(entries))
        summary = build_summary(
            stats=stats,
            write=write,
            manifest_entries=len(entries),
            output_dir=config.output,
            timestamp=now or datetime.now(timezone.utc),
            overwrite=config.overwrite,
            tool_version=__version__,
        )
        write_summary(config.output, render_summary(summary))
        log.info(
            "Manifest %s (%d entries)", "updated" if manifest_changed else "unchanged", len(entries)
        )
        log.info("Summary report written")

    exit_code = _exit_code(stats, write)
    if exit_code == EXIT_OK:
        log.info("Completed successfully")
    else:
        log.warning("Completed with problems (exit code %d)", exit_code)
    return RunResult(domains, stats, write, summary, exit_code)


def _process_source(
    path: Path | None, config: Config, stats: ExtractionStats, dedup: Deduplicator
) -> None:
    name = STDIN_NAME if path is None else str(path)
    fmt = source_format(path, config.fmt)
    log.debug("Reading %s (format: %s)", name, fmt)
    before = stats.candidates
    try:
        for fragment in read_fragments(path, fmt):
            for raw in extract_hosts(fragment):
                _consider(raw, stats, dedup)
    except InputError as exc:
        # Candidates found before the error are kept; the source is reported as failed.
        stats.record_input_error(name, str(exc))
        log.warning("%s", exc)
        return
    stats.input_files_processed += 1
    log.debug("%s: %d candidates", name, stats.candidates - before)


def _consider(raw: str, stats: ExtractionStats, dedup: Deduplicator) -> None:
    stats.candidates += 1
    host = normalize_host(raw)
    reason = "could not be normalized" if host is None else validate_domain(host)
    if reason is not None or host is None:
        stats.record_rejection(raw, reason or "invalid")
        log.debug("Rejected %r: %s", raw, reason)
        return
    dedup.add(host)


def _log_extraction(stats: ExtractionStats) -> None:
    log.info("Input sources processed: %d", stats.input_files_processed)
    log.info("Candidates extracted: %d", stats.candidates)
    log.info("Valid unique domains: %d", stats.valid_unique)
    log.info("Duplicates removed: %d", stats.duplicates)
    log.info("Invalid candidates rejected: %d", stats.rejected)


def _log_writes(write: WriteResult, config: Config) -> None:
    if config.dry_run:
        log.info("Dry run: no files were written")
        log.info(
            "Domain files that would be created: %d, overwritten: %d, unchanged: %d",
            len(write.created),
            len(write.overwritten),
            len(write.unchanged),
        )
    else:
        log.info(
            "Domain files written: %d (created %d, overwritten %d, unchanged %d)",
            write.written,
            len(write.created),
            len(write.overwritten),
            len(write.unchanged),
        )
    if write.conflicts:
        log.warning(
            "%d existing domain file(s) have unexpected content and were left untouched "
            "(use --overwrite to replace them)",
            len(write.conflicts),
        )
    for domain, reason in sorted(write.failed.items())[:_MAX_LOGGED_FAILURES]:
        log.error("Could not write %s: %s", domain, reason)
    if len(write.failed) > _MAX_LOGGED_FAILURES:
        log.error("... and %d more write failures", len(write.failed) - _MAX_LOGGED_FAILURES)


def _exit_code(stats: ExtractionStats, write: WriteResult) -> int:
    if write.failed:
        return EXIT_OUTPUT
    if stats.input_errors or write.conflicts:
        return EXIT_WARNING
    return EXIT_OK
