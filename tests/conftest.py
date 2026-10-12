"""Shared test helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from domain_dumper.cli import main

running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0


@pytest.fixture
def write_input(tmp_path: Path):
    """Return a function that creates an input file under tmp_path/in and returns its path."""

    def _write(name: str, content: str) -> Path:
        path = tmp_path / "in" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    return _write


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path / "out"


@pytest.fixture
def run_cli():
    """Call the CLI in-process and return its exit code."""

    def _run(*args: object) -> int:
        return main([str(a) for a in args])

    return _run


def domain_files(out: Path) -> list[str]:
    """Sorted names of the files in the domains directory."""
    return sorted(p.name for p in (out / "domains").iterdir())
