import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import domain_files, running_as_root

from domain_dumper import __version__, sources
from domain_dumper.exceptions import EXIT_INPUT, EXIT_OK, EXIT_OUTPUT, EXIT_USAGE, EXIT_WARNING


def fake_stdin(monkeypatch, data: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data.encode("utf-8"))))


def test_version(run_cli, capsys):
    assert run_cli("--version") == EXIT_OK
    assert __version__ in capsys.readouterr().out


def test_help_lists_every_option(run_cli, capsys):
    assert run_cli("--help") == EXIT_OK
    text = capsys.readouterr().out
    for option in (
        "--input", "--output", "--stdin", "--format", "--recursive",
        "--overwrite", "--dry-run", "--quiet", "--verbose", "--version", "--help",
    ):  # fmt: skip
        assert option in text


def test_single_file(run_cli, write_input, out_dir, capsys):
    f = write_input("d.txt", "example.com\nGoogle.com\n")
    assert run_cli("--input", f, "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["example.com.txt", "google.com.txt"]
    out = capsys.readouterr().out
    assert "[INFO] Starting domain extraction" in out
    assert "[INFO] Valid unique domains: 2" in out
    assert "[INFO] Completed successfully" in out


def test_repeated_and_multi_value_input_options(run_cli, write_input, out_dir):
    a = write_input("a.txt", "a.example.com\n")
    b = write_input("b.txt", "b.example.com\n")
    c = write_input("c.txt", "c.example.com\n")
    assert run_cli("--input", a, "--input", b, c, "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["a.example.com.txt", "b.example.com.txt", "c.example.com.txt"]


def test_recursive_flag(run_cli, tmp_path, out_dir):
    (tmp_path / "in" / "sub").mkdir(parents=True)
    (tmp_path / "in" / "top.txt").write_text("top.example.com\n")
    (tmp_path / "in" / "sub" / "deep.txt").write_text("deep.example.com\n")
    assert run_cli("--input", tmp_path / "in", "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["top.example.com.txt"]
    assert run_cli("--input", tmp_path / "in", "--recursive", "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["deep.example.com.txt", "top.example.com.txt"]


def test_stdin(run_cli, monkeypatch, out_dir):
    fake_stdin(monkeypatch, "from-stdin.example.com\nhttps://Other.Example.org:8080/x\n")
    assert run_cli("--stdin", "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["from-stdin.example.com.txt", "other.example.org.txt"]


def test_stdin_with_explicit_json_format(run_cli, monkeypatch, out_dir):
    # JSON escapes "/" as "\/": only a real JSON parser recovers this URL.
    fake_stdin(monkeypatch, r'{"hosts": ["https:\/\/json.example.com\/x"]}')
    assert run_cli("--stdin", "--format", "json", "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["json.example.com.txt"]


def test_stdin_combined_with_files(run_cli, monkeypatch, write_input, out_dir):
    f = write_input("a.txt", "file.example.com\n")
    fake_stdin(monkeypatch, "pipe.example.com\n")
    assert run_cli("--input", f, "--stdin", "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["file.example.com.txt", "pipe.example.com.txt"]


def test_stdin_that_is_a_terminal_is_a_usage_error(run_cli, monkeypatch, out_dir, capsys):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty(""))
    assert run_cli("--stdin", "--output", out_dir) == EXIT_USAGE
    assert "interactive terminal" in capsys.readouterr().err


def test_csv_and_json_detected_by_extension(run_cli, write_input, out_dir):
    j = write_input("a.json", '{"h": "https://j.example.com/x"}')
    c = write_input("b.csv", "host,port\nc.example.com,443\n")
    assert run_cli("--input", j, c, "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["c.example.com.txt", "j.example.com.txt"]


def test_explicit_format_overrides_extension(run_cli, write_input, out_dir):
    f = write_input("data.txt", "host,port\nc.example.com,443\n")
    assert run_cli("--input", f, "--format", "csv", "--output", out_dir) == EXIT_OK
    assert domain_files(out_dir) == ["c.example.com.txt"]


def test_dry_run_writes_nothing(run_cli, write_input, out_dir, capsys):
    f = write_input("a.txt", "example.com\n")
    assert run_cli("--input", f, "--output", out_dir, "--dry-run") == EXIT_OK
    assert not out_dir.exists()
    out = capsys.readouterr().out
    assert "Dry run: no files were written" in out
    assert "would be created: 1" in out


def test_dry_run_does_not_touch_existing_output(run_cli, write_input, out_dir):
    f = write_input("a.txt", "example.com\n")
    assert run_cli("--input", f, "--output", out_dir) == EXIT_OK
    before = {p: p.read_bytes() for p in out_dir.rglob("*") if p.is_file()}
    g = write_input("b.txt", "new.example.com\n")
    assert run_cli("--input", g, "--output", out_dir, "--dry-run") == EXIT_OK
    after = {p: p.read_bytes() for p in out_dir.rglob("*") if p.is_file()}
    assert before == after


def test_quiet_prints_no_info_lines(run_cli, write_input, out_dir, capsys):
    f = write_input("a.txt", "example.com\n")
    assert run_cli("--input", f, "--output", out_dir, "--quiet") == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_verbose_prints_diagnostics(run_cli, write_input, out_dir, capsys):
    f = write_input("a.txt", "example.com\n10.0.0.1\n")
    assert run_cli("--input", f, "--output", out_dir, "--verbose") == EXIT_OK
    out = capsys.readouterr().out
    assert "[DEBUG] Reading" in out
    assert "[DEBUG] Rejected '10.0.0.1'" in out


def test_verbose_output_never_shows_url_credentials(run_cli, write_input, out_dir, capsys):
    f = write_input("a.txt", "http://admin:hunter2@[bad/x\nhttp://admin:hunter2@10.0.0.1/\n")
    run_cli("--input", f, "--output", out_dir, "--verbose")
    captured = capsys.readouterr()
    assert "hunter2" not in captured.out + captured.err
    assert "hunter2" not in (out_dir / "reports" / "summary.json").read_text()


def test_quiet_and_verbose_conflict(run_cli, write_input, out_dir, capsys):
    f = write_input("a.txt", "example.com\n")
    assert run_cli("--input", f, "--output", out_dir, "--quiet", "--verbose") == EXIT_USAGE
    assert "cannot be used together" in capsys.readouterr().err
    assert not out_dir.exists()


def test_no_input_is_usage_error(run_cli, out_dir, capsys):
    assert run_cli("--output", out_dir) == EXIT_USAGE
    assert "no input given" in capsys.readouterr().err


def test_recursive_without_input_is_usage_error(run_cli, monkeypatch, out_dir, capsys):
    fake_stdin(monkeypatch, "example.com\n")
    assert run_cli("--stdin", "--recursive", "--output", out_dir) == EXIT_USAGE
    assert "--recursive" in capsys.readouterr().err


def test_unknown_format_is_usage_error(run_cli, write_input, out_dir):
    f = write_input("a.txt", "example.com\n")
    assert run_cli("--input", f, "--format", "xml", "--output", out_dir) == EXIT_USAGE


def test_unknown_option_is_usage_error(run_cli):
    assert run_cli("--bogus") == EXIT_USAGE


def test_input_inside_output_is_refused(run_cli, out_dir, capsys):
    (out_dir / "domains").mkdir(parents=True)
    generated = out_dir / "domains" / "example.com.txt"
    generated.write_text("example.com\n")
    assert run_cli("--input", generated, "--output", out_dir) == EXIT_USAGE
    assert "inside the output directory" in capsys.readouterr().err
    assert generated.read_text() == "example.com\n"


def test_missing_input_is_input_error(run_cli, tmp_path, out_dir, capsys):
    assert run_cli("--input", tmp_path / "nope.txt", "--output", out_dir) == EXIT_INPUT
    assert "no input could be read" in capsys.readouterr().err
    assert not out_dir.exists()


def test_input_directory_without_supported_files_is_input_error(run_cli, tmp_path, out_dir):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_cli("--input", empty, "--output", out_dir) == EXIT_INPUT


def test_partial_input_failure_still_writes_and_returns_warning_code(
    run_cli, write_input, tmp_path, out_dir
):
    good = write_input("good.txt", "good.example.com\n")
    assert run_cli("--input", good, tmp_path / "missing.txt", "--output", out_dir) == EXIT_WARNING
    assert domain_files(out_dir) == ["good.example.com.txt"]
    summary = json.loads((out_dir / "reports" / "summary.json").read_text())
    assert summary["input_files_failed"] == 1
    assert summary["input_errors"][0]["message"] == "path does not exist"


def test_unreadable_input_is_reported_not_fatal(run_cli, write_input, out_dir, monkeypatch):
    good = write_input("good.txt", "good.example.com\n")
    bad = write_input("bad.txt", "bad.example.com\n")
    real_open = type(bad).open

    def fake_open(self, *args, **kwargs):
        if self.name == "bad.txt":
            raise PermissionError(13, "Permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(type(bad), "open", fake_open)
    assert run_cli("--input", good, bad, "--output", out_dir) == EXIT_WARNING
    assert domain_files(out_dir) == ["good.example.com.txt"]


@pytest.mark.skipif(running_as_root, reason="root ignores file permissions")
def test_chmod_unreadable_input(run_cli, write_input, out_dir):
    bad = write_input("bad.txt", "bad.example.com\n")
    bad.chmod(0)
    try:
        assert run_cli("--input", bad, "--output", out_dir) == EXIT_INPUT
    finally:
        bad.chmod(0o600)


def test_output_path_that_is_a_file_is_output_error(run_cli, write_input, tmp_path, capsys):
    f = write_input("a.txt", "example.com\n")
    blocker = tmp_path / "blocker"
    blocker.write_text("file")
    assert run_cli("--input", f, "--output", blocker) == EXIT_OUTPUT
    assert "cannot create output directory" in capsys.readouterr().err


def test_write_failures_give_output_exit_code_and_are_never_reported_as_written(
    run_cli, write_input, out_dir, monkeypatch, capsys
):
    from domain_dumper import writer

    f = write_input("a.txt", "example.com\n")
    real_replace = writer.os.replace

    def fail_for_domains(src, dst):
        if str(dst).endswith("example.com.txt"):
            raise PermissionError(13, "Permission denied")
        return real_replace(src, dst)

    monkeypatch.setattr(writer.os, "replace", fail_for_domains)
    assert run_cli("--input", f, "--output", out_dir) == EXIT_OUTPUT
    assert "Could not write example.com: Permission denied" in capsys.readouterr().err
    summary = json.loads((out_dir / "reports" / "summary.json").read_text())
    assert summary["domain_files_written"] == 0
    assert summary["domain_files_failed"] == 1
    assert summary["manifest_entries"] == 0
    assert (out_dir / "manifest.txt").read_text() == ""


@pytest.mark.skipif(running_as_root, reason="root ignores file permissions")
def test_read_only_output_directory(run_cli, write_input, out_dir):
    f = write_input("a.txt", "example.com\n")
    out_dir.mkdir()
    out_dir.chmod(0o500)
    try:
        assert run_cli("--input", f, "--output", out_dir) == EXIT_OUTPUT
    finally:
        out_dir.chmod(0o700)


def test_overwrite_flag_changes_conflict_behaviour(run_cli, write_input, out_dir, capsys):
    f = write_input("a.txt", "example.com\n")
    (out_dir / "domains").mkdir(parents=True)
    target = out_dir / "domains" / "example.com.txt"
    target.write_text("unexpected\n")
    assert run_cli("--input", f, "--output", out_dir) == EXIT_WARNING
    assert target.read_text() == "unexpected\n"
    assert "--overwrite" in capsys.readouterr().err
    assert run_cli("--input", f, "--output", out_dir, "--overwrite") == EXIT_OK
    assert target.read_text() == "example.com\n"


def test_input_files_are_never_modified(run_cli, write_input, out_dir):
    f = write_input("a.txt", "example.com\nexample.com\n")
    before = f.read_bytes()
    run_cli("--input", f, "--output", out_dir, "--overwrite")
    assert f.read_bytes() == before


def test_runs_as_python_module(write_input, out_dir):
    f = write_input("a.txt", "example.com\n")
    package_parent = Path(sources.__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "domain_dumper.cli", "--input", str(f), "--output", str(out_dir)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(package_parent)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "[INFO] Completed successfully" in proc.stdout
    assert domain_files(out_dir) == ["example.com.txt"]
