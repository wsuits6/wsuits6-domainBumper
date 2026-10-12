"""All filesystem writes: domain files, manifest and summary report."""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import OutputError, UnsafePathError
from .manifest import DOMAIN_FILE_SUFFIX, MANIFEST_NAME
from .validator import validate_domain

log = logging.getLogger(__name__)

DOMAINS_DIRNAME = "domains"
REPORTS_DIRNAME = "reports"
SUMMARY_NAME = "summary.json"


@dataclass
class WriteResult:
    """Outcome of writing domain files. In a dry run the lists show what *would* happen."""

    created: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # existing, different, not overwritten
    failed: dict[str, str] = field(default_factory=dict)  # domain -> reason
    dry_run: bool = False

    @property
    def written(self) -> int:
        return len(self.created) + len(self.overwritten)


def ensure_directories(output_dir: Path) -> None:
    """Create the output, domains and reports directories."""
    try:
        (output_dir / DOMAINS_DIRNAME).mkdir(parents=True, exist_ok=True)
        (output_dir / REPORTS_DIRNAME).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"cannot create output directory {output_dir}: {_reason(exc)}") from exc


def domain_path(domains_dir: Path, domain: str) -> Path:
    """Return the file path for ``domain``, refusing anything that could leave ``domains_dir``."""
    reason = validate_domain(domain)
    if reason is not None:
        raise UnsafePathError(f"refusing to build a path for {domain!r}: {reason}")
    path = domains_dir / f"{domain}{DOMAIN_FILE_SUFFIX}"
    if path.parent != domains_dir:
        raise UnsafePathError(f"path for {domain!r} escapes the domains directory")
    return path


def write_domain_files(
    domains_dir: Path, domains: Sequence[str], *, overwrite: bool, dry_run: bool
) -> WriteResult:
    """Write ``<domain>.txt`` (content ``<domain>\\n``) for each domain.

    Missing files are created. Identical files are left untouched. Files with different
    content are left untouched and reported as conflicts unless ``overwrite`` is set.
    Nothing is ever deleted. With ``dry_run`` the filesystem is only read.
    """
    result = WriteResult(dry_run=dry_run)
    for domain in domains:
        try:
            path = domain_path(domains_dir, domain)
            payload = f"{domain}\n"
            state = _existing_state(path, payload)
            if state == "same":
                result.unchanged.append(domain)
            elif state == "different" and not overwrite:
                log.debug("Existing file differs, left untouched: %s", path.name)
                result.conflicts.append(domain)
            else:
                if not dry_run:
                    atomic_write_text(path, payload)
                (result.overwritten if state == "different" else result.created).append(domain)
        except OSError as exc:
            result.failed[domain] = _reason(exc)
        except UnsafePathError as exc:
            result.failed[domain] = str(exc)
    return result


def write_manifest(output_dir: Path, text: str) -> bool:
    """Write the manifest atomically. Return False if it was already up to date."""
    path = output_dir / MANIFEST_NAME
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return False
        atomic_write_text(path, text, durable=True)
    except OSError as exc:
        raise OutputError(f"cannot write manifest {path}: {_reason(exc)}") from exc
    return True


def write_summary(output_dir: Path, text: str) -> Path:
    """Write the summary report atomically and return its path."""
    path = output_dir / REPORTS_DIRNAME / SUMMARY_NAME
    try:
        atomic_write_text(path, text, durable=True)
    except OSError as exc:
        raise OutputError(f"cannot write summary report {path}: {_reason(exc)}") from exc
    return path


def atomic_write_text(path: Path, text: str, *, durable: bool = False) -> None:
    """Write ``text`` to ``path`` via a temp file in the same directory plus ``os.replace``.

    A reader (or an interrupted run) therefore sees either the old file or the complete new
    one, never a partial file. ``durable`` also fsyncs before the rename.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            if durable:
                handle.flush()
                os.fsync(handle.fileno())
        os.chmod(tmp_name, _default_mode())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _existing_state(path: Path, payload: str) -> str:
    """Classify the target: ``missing``, ``same`` or ``different``. Refuse links and dirs."""
    if path.is_symlink():
        raise UnsafePathError(f"{path.name} is a symbolic link; refusing to write through it")
    if path.is_dir():
        raise UnsafePathError(f"{path.name} is a directory")
    expected = payload.encode("utf-8")
    try:
        with path.open("rb") as handle:
            content = handle.read(len(expected) + 1)
    except FileNotFoundError:
        return "missing"
    return "same" if content == expected else "different"


def _default_mode() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def _reason(exc: OSError) -> str:
    return exc.strerror or str(exc)
