"""Build the manifest from what is actually on disk."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from .validator import is_valid_domain

MANIFEST_NAME = "manifest.txt"
DOMAIN_FILE_SUFFIX = ".txt"


def render_manifest(domains: Iterable[str]) -> str:
    """One domain per line, sorted and unique. Empty input gives an empty file."""
    ordered = sorted(set(domains))
    return "".join(f"{domain}\n" for domain in ordered)


def scan_recorded_domains(domains_dir: Path) -> list[str]:
    """Return the sorted domains whose file in ``domains_dir`` is present and correct.

    A file counts only if it is a regular file named ``<valid domain>.txt`` whose content is
    exactly ``<domain>\\n``. Unrelated files and files with unexpected content are ignored,
    so the manifest never lists something that is not a correct domain record.
    """
    found: list[str] = []
    try:
        entries = list(os.scandir(domains_dir))
    except FileNotFoundError:
        return found
    for entry in entries:
        name = entry.name
        if not name.endswith(DOMAIN_FILE_SUFFIX) or entry.is_symlink() or not entry.is_file():
            continue
        domain = name[: -len(DOMAIN_FILE_SUFFIX)]
        if not is_valid_domain(domain):
            continue
        expected = f"{domain}\n".encode()
        try:
            with open(entry.path, "rb") as handle:
                content = handle.read(len(expected) + 1)
        except OSError:
            continue
        if content == expected:
            found.append(domain)
    return sorted(found)
