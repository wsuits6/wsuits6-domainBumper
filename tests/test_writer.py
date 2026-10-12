import os
from pathlib import Path

import pytest
from conftest import running_as_root

from domain_dumper import writer
from domain_dumper.exceptions import OutputError, UnsafePathError
from domain_dumper.manifest import render_manifest, scan_recorded_domains
from domain_dumper.writer import (
    atomic_write_text,
    domain_path,
    ensure_directories,
    write_domain_files,
    write_manifest,
    write_summary,
)


@pytest.fixture
def domains_dir(tmp_path: Path) -> Path:
    d = tmp_path / "out" / "domains"
    d.mkdir(parents=True)
    return d


def test_one_correctly_named_file_per_domain(domains_dir):
    names = ["example.com", "api.example.com", "google.com"]
    result = write_domain_files(domains_dir, names, overwrite=False, dry_run=False)
    assert sorted(result.created) == sorted(names)
    assert sorted(p.name for p in domains_dir.iterdir()) == [
        "api.example.com.txt",
        "example.com.txt",
        "google.com.txt",
    ]
    for name in names:
        assert (domains_dir / f"{name}.txt").read_bytes() == f"{name}\n".encode()


def test_no_temp_files_left_behind(domains_dir):
    write_domain_files(domains_dir, ["example.com"], overwrite=False, dry_run=False)
    assert [p.name for p in domains_dir.iterdir()] == ["example.com.txt"]


def test_unchanged_file_is_not_rewritten(domains_dir):
    write_domain_files(domains_dir, ["example.com"], overwrite=False, dry_run=False)
    target = domains_dir / "example.com.txt"
    os.utime(target, (1_000_000, 1_000_000))
    result = write_domain_files(domains_dir, ["example.com"], overwrite=False, dry_run=False)
    assert result.unchanged == ["example.com"]
    assert result.written == 0
    assert target.stat().st_mtime == 1_000_000


def test_existing_different_file_is_kept_without_overwrite(domains_dir):
    target = domains_dir / "example.com.txt"
    target.write_text("something else\n")
    result = write_domain_files(domains_dir, ["example.com"], overwrite=False, dry_run=False)
    assert result.conflicts == ["example.com"]
    assert result.written == 0
    assert target.read_text() == "something else\n"


def test_existing_different_file_is_replaced_with_overwrite(domains_dir):
    target = domains_dir / "example.com.txt"
    target.write_text("something else\n")
    result = write_domain_files(domains_dir, ["example.com"], overwrite=True, dry_run=False)
    assert result.overwritten == ["example.com"]
    assert target.read_text() == "example.com\n"


def test_missing_trailing_newline_counts_as_different(domains_dir):
    (domains_dir / "example.com.txt").write_text("example.com")
    result = write_domain_files(domains_dir, ["example.com"], overwrite=False, dry_run=False)
    assert result.conflicts == ["example.com"]


def test_dry_run_reports_but_writes_nothing(tmp_path):
    missing_dir = tmp_path / "does-not-exist" / "domains"
    result = write_domain_files(missing_dir, ["example.com"], overwrite=False, dry_run=True)
    assert result.created == ["example.com"]
    assert result.dry_run
    assert not (tmp_path / "does-not-exist").exists()


def test_symlink_target_is_refused_and_not_followed(domains_dir, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (domains_dir / "example.com.txt").symlink_to(victim)
    result = write_domain_files(domains_dir, ["example.com"], overwrite=True, dry_run=False)
    assert "example.com" in result.failed
    assert victim.read_text() == "precious"


def test_directory_in_the_way_is_a_failure_not_a_crash(domains_dir):
    (domains_dir / "example.com.txt").mkdir()
    result = write_domain_files(
        domains_dir, ["example.com", "ok.example.org"], overwrite=True, dry_run=False
    )
    assert "example.com" in result.failed
    assert result.created == ["ok.example.org"]


@pytest.mark.parametrize(
    "evil",
    [
        "../evil.com",
        "a/../../evil.com",
        "/etc/passwd",
        "..",
        "a\\b.com",
        "x.com/../y.com",
        "a\0b.com",
    ],
)
def test_path_traversal_is_rejected(domains_dir, evil):
    with pytest.raises(UnsafePathError):
        domain_path(domains_dir, evil)
    result = write_domain_files(domains_dir, [evil], overwrite=True, dry_run=False)
    assert list(result.failed) == [evil]
    assert not (domains_dir.parent / "evil.com.txt").exists()
    assert list(domains_dir.iterdir()) == []


def test_atomic_write_failure_leaves_no_partial_or_temp_file(domains_dir, monkeypatch):
    def boom(src, dst):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(writer.os, "replace", boom)
    result = write_domain_files(domains_dir, ["example.com"], overwrite=False, dry_run=False)
    assert result.failed == {"example.com": "Permission denied"}
    assert result.written == 0
    assert list(domains_dir.iterdir()) == []


def test_atomic_write_replaces_whole_file(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("old")
    atomic_write_text(target, "new\n", durable=True)
    assert target.read_text() == "new\n"
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]


@pytest.mark.skipif(running_as_root, reason="root ignores file permissions")
def test_read_only_domains_dir_is_reported(domains_dir):
    domains_dir.chmod(0o500)
    try:
        result = write_domain_files(domains_dir, ["example.com"], overwrite=False, dry_run=False)
    finally:
        domains_dir.chmod(0o700)
    assert "example.com" in result.failed and result.written == 0


def test_ensure_directories_error_is_output_error(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")
    with pytest.raises(OutputError, match="cannot create output directory"):
        ensure_directories(blocker / "out")


def test_manifest_is_sorted_unique_and_skips_rewrite_when_identical(tmp_path):
    text = render_manifest(["b.example.com", "a.example.com", "b.example.com"])
    assert text == "a.example.com\nb.example.com\n"
    assert write_manifest(tmp_path, text) is True
    assert write_manifest(tmp_path, text) is False
    assert (tmp_path / "manifest.txt").read_text() == text


def test_empty_manifest_is_an_empty_file(tmp_path):
    assert render_manifest([]) == ""
    write_manifest(tmp_path, "")
    assert (tmp_path / "manifest.txt").read_text() == ""


def test_manifest_write_failure_is_output_error(tmp_path):
    with pytest.raises(OutputError, match="manifest"):
        write_manifest(tmp_path / "missing-dir", "x\n")


def test_summary_write_failure_is_output_error(tmp_path):
    with pytest.raises(OutputError, match="summary"):
        write_summary(tmp_path, "{}\n")  # reports/ does not exist


def test_scan_only_lists_correct_domain_files(domains_dir):
    (domains_dir / "good.example.com.txt").write_text("good.example.com\n")
    (domains_dir / "wrong-content.example.com.txt").write_text("other.example.com\n")
    (domains_dir / "notes.txt").write_text("notes\n")  # not a valid domain name
    (domains_dir / "README").write_text("x")
    (domains_dir / ".tmp-abc.part").write_text("x")
    (domains_dir / "dir.example.com.txt").mkdir()
    assert scan_recorded_domains(domains_dir) == ["good.example.com"]


def test_scan_of_missing_directory_is_empty(tmp_path):
    assert scan_recorded_domains(tmp_path / "nope") == []
