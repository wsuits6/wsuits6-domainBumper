"""Locate input sources and turn them into streams of text fragments.

Each format parser takes a text stream and yields text fragments; the extractor then looks
for hostnames inside each fragment. To add a format, write a parser and register it in
:data:`PARSERS`.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import TextIO

from .exceptions import InputError

MAX_LINE_CHARS = 1 << 20  # long lines are read in chunks of this size
MAX_STRUCTURED_CHARS = 64 * 1024 * 1024  # JSON must be loaded whole, so it is capped
SUPPORTED_SUFFIXES = frozenset({".txt", ".log", ".list", ".lst", ".out", ".tsv", ".json", ".csv"})
_FORMAT_BY_SUFFIX = {".json": "json", ".csv": "csv"}


# --------------------------------------------------------------------------- discovery


def discover_inputs(
    paths: Sequence[Path], *, recursive: bool, exclude_dir: Path | None = None
) -> tuple[list[Path], list[tuple[str, str]]]:
    """Expand ``paths`` into a de-duplicated file list plus ``(source, message)`` problems.

    Directories contribute files with a supported suffix (top level only unless
    ``recursive``). ``exclude_dir`` (the output directory) is never descended into.
    """
    files: list[Path] = []
    problems: list[tuple[str, str]] = []
    seen: set[Path] = set()
    excluded = exclude_dir.resolve() if exclude_dir is not None else None

    def add(path: Path) -> None:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            files.append(path)

    for path in paths:
        if not path.exists():
            problems.append((str(path), "path does not exist"))
        elif path.is_file():
            add(path)
        elif path.is_dir():
            found = list(_walk(path, recursive, excluded))
            if not found:
                hint = "" if recursive else " (subdirectories are only searched with --recursive)"
                problems.append((str(path), f"no supported input files found{hint}"))
            for item in found:
                add(item)
        else:
            problems.append((str(path), "not a regular file or directory"))
    return files, problems


def _walk(root: Path, recursive: bool, excluded: Path | None) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and (excluded is None or (current / d).resolve() != excluded)
        )
        if not recursive:
            dirnames[:] = []
        for name in sorted(filenames):
            if Path(name).suffix.lower() in SUPPORTED_SUFFIXES:
                yield current / name


# --------------------------------------------------------------------------- reading


def source_format(path: Path | None, requested: str) -> str:
    """Resolve ``auto`` to a concrete format. Stdin is plain text unless a format is given."""
    if requested != "auto":
        return requested
    if path is None:
        return "txt"
    return _FORMAT_BY_SUFFIX.get(path.suffix.lower(), "txt")


def read_fragments(path: Path | None, fmt: str) -> Iterator[str]:
    """Yield text fragments from ``path`` (or stdin when ``None``) using parser ``fmt``.

    Raises :class:`InputError` for unreadable, binary or malformed input.
    """
    parser = PARSERS[fmt]
    if path is None:
        stream, detach = _stdin_stream()
        try:
            yield from parser(stream)
        finally:
            if detach:
                stream.detach()
        return
    with _open_text(path) as stream:
        yield from parser(stream)


def _stdin_stream() -> tuple[TextIO, bool]:
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin, False
    return io.TextIOWrapper(buffer, encoding="utf-8-sig", errors="replace"), True


def _open_text(path: Path) -> TextIO:
    try:
        with path.open("rb") as raw:
            if b"\0" in raw.read(8192):
                raise InputError(f"{path}: binary file (contains NUL bytes), skipped")
        return path.open("r", encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise InputError(f"{path}: cannot read ({exc.strerror or exc})") from exc


# --------------------------------------------------------------------------- parsers


def iter_lines(stream: TextIO, limit: int = MAX_LINE_CHARS) -> Iterator[str]:
    """Yield lines without ever holding more than about ``limit`` characters at once.

    A line longer than ``limit`` is split at whitespace so a hostname is not cut in half.
    """
    carry = ""
    while True:
        raw = stream.readline(limit)
        if not raw:
            break
        chunk = carry + raw
        carry = ""
        if raw.endswith("\n") or len(raw) < limit:
            yield chunk
            continue
        cut = max(chunk.rfind(" "), chunk.rfind("\t"))
        if cut > 0:
            yield chunk[:cut]
            carry = chunk[cut + 1 :]
        else:
            yield chunk
    if carry:
        yield carry


def parse_txt(stream: TextIO) -> Iterator[str]:
    """Plain text: one fragment per non-blank line; lines starting with ``#`` are comments."""
    for line in iter_lines(stream):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            yield stripped


def parse_csv(stream: TextIO) -> Iterator[str]:
    """CSV: every non-empty cell is a fragment, so no column name has to be configured."""
    csv.field_size_limit(MAX_LINE_CHARS)
    try:
        for row in csv.reader(stream):
            for cell in row:
                cell = cell.strip()
                if cell:
                    yield cell
    except csv.Error as exc:
        raise InputError(f"invalid CSV: {exc}") from exc


def parse_json(stream: TextIO) -> Iterator[str]:
    """JSON (or JSON Lines): every string key and value, at any depth, is a fragment."""
    text = stream.read(MAX_STRUCTURED_CHARS + 1)
    if len(text) > MAX_STRUCTURED_CHARS:
        raise InputError(f"JSON input exceeds {MAX_STRUCTURED_CHARS} characters")
    if not text.strip():
        return
    try:
        documents: list[object] = [json.loads(text)]
    except (ValueError, RecursionError) as exc:
        documents = _parse_json_lines(text, exc)
    for document in documents:
        yield from _json_strings(document)


def _parse_json_lines(text: str, original: Exception) -> list[object]:
    documents: list[object] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            documents.append(json.loads(line))
        except (ValueError, RecursionError):
            raise InputError(f"invalid JSON: {original}") from original
    return documents


def _json_strings(root: object) -> Iterable[str]:
    stack = [root]  # iterative, so deeply nested input cannot overflow the call stack
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            yield from item
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))


PARSERS: dict[str, Callable[[TextIO], Iterator[str]]] = {
    "txt": parse_txt,
    "json": parse_json,
    "csv": parse_csv,
}
