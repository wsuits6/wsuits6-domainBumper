"""Run statistics and the ``reports/summary.json`` document."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .writer import WriteResult

SCHEMA_VERSION = 1
MAX_REJECTED_SAMPLES = 20
MAX_LISTED_ITEMS = 100


@dataclass
class ExtractionStats:
    """Counters collected while reading inputs.

    Invariant: ``candidates == valid_unique + duplicates + rejected``.
    """

    input_files_processed: int = 0
    input_files_failed: int = 0
    candidates: int = 0
    valid_unique: int = 0
    duplicates: int = 0
    rejected: int = 0
    rejected_samples: list[dict[str, str]] = field(default_factory=list)
    input_errors: list[dict[str, str]] = field(default_factory=list)

    def record_rejection(self, value: str, reason: str) -> None:
        self.rejected += 1
        if len(self.rejected_samples) < MAX_REJECTED_SAMPLES:
            self.rejected_samples.append({"value": value, "reason": reason})

    def record_input_error(self, source: str, message: str) -> None:
        self.input_files_failed += 1
        self.input_errors.append({"source": source, "message": message})


def build_summary(
    *,
    stats: ExtractionStats,
    write: WriteResult,
    manifest_entries: int,
    output_dir: Path,
    timestamp: datetime,
    overwrite: bool,
    tool_version: str,
) -> dict[str, Any]:
    """Assemble the summary document (schema documented in the README)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": tool_version,
        "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output_directory": str(output_dir.resolve()),
        "overwrite": overwrite,
        "input_files_processed": stats.input_files_processed,
        "input_files_failed": stats.input_files_failed,
        "candidates_extracted": stats.candidates,
        "valid_unique_domains": stats.valid_unique,
        "duplicates_removed": stats.duplicates,
        "rejected_candidates": stats.rejected,
        "domain_files_written": write.written,
        "domain_files_created": len(write.created),
        "domain_files_overwritten": len(write.overwritten),
        "domain_files_unchanged": len(write.unchanged),
        "domain_files_conflicting": len(write.conflicts),
        "domain_files_failed": len(write.failed),
        "manifest_entries": manifest_entries,
        "input_errors": stats.input_errors,
        "write_errors": [
            {"domain": domain, "message": message}
            for domain, message in sorted(write.failed.items())[:MAX_LISTED_ITEMS]
        ],
        "conflicts": sorted(write.conflicts)[:MAX_LISTED_ITEMS],
        "rejected_samples": stats.rejected_samples,
    }


def render_summary(summary: dict[str, Any]) -> str:
    """Serialize the summary as indented UTF-8 JSON with a trailing newline."""
    return json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
