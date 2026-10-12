"""Exception types and the process exit codes they map to."""

EXIT_OK = 0
EXIT_WARNING = 1  # finished, but with recoverable input errors or untouched conflicts
EXIT_USAGE = 2  # invalid or incompatible command-line arguments
EXIT_INPUT = 3  # no usable input could be read
EXIT_OUTPUT = 4  # output could not be written


class DomainDumperError(Exception):
    """Base class for all expected, user-facing errors."""

    exit_code: int = EXIT_WARNING


class UsageError(DomainDumperError):
    """Invalid or incompatible command-line options."""

    exit_code = EXIT_USAGE


class InputError(DomainDumperError):
    """An input source could not be read or parsed."""

    exit_code = EXIT_INPUT


class OutputError(DomainDumperError):
    """The output directory or a report file could not be written."""

    exit_code = EXIT_OUTPUT


class UnsafePathError(OutputError):
    """A write was refused because the target path is not safe."""
