"""Run configuration and its validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .exceptions import UsageError
from .sources import PARSERS

DEFAULT_OUTPUT = Path("output/domain-dump")
FORMATS: tuple[str, ...] = ("auto", *PARSERS)


@dataclass(frozen=True)
class Config:
    """Everything a run needs, independent of how it was requested."""

    inputs: tuple[Path, ...] = ()
    output: Path = DEFAULT_OUTPUT
    use_stdin: bool = False
    fmt: str = "auto"
    recursive: bool = False
    overwrite: bool = False
    dry_run: bool = False
    quiet: bool = False
    verbose: bool = False

    def validate(self) -> None:
        """Raise :class:`UsageError` for missing or incompatible options."""
        if self.quiet and self.verbose:
            raise UsageError("--quiet and --verbose cannot be used together")
        if self.fmt not in FORMATS:
            raise UsageError(f"unknown format {self.fmt!r} (choose from: {', '.join(FORMATS)})")
        if not self.inputs and not self.use_stdin:
            raise UsageError("no input given: use --input PATH and/or --stdin")
        if self.recursive and not self.inputs:
            raise UsageError("--recursive only applies to --input directories; none were given")

        output = self.output.resolve()
        for path in self.inputs:
            if path.exists() and path.resolve().is_relative_to(output):
                raise UsageError(
                    f"input {str(path)!r} is inside the output directory {str(self.output)!r}; "
                    "refusing to read generated files as input"
                )
