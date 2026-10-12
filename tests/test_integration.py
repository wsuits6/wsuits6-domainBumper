"""End-to-end tests through the pipeline (no mocks of the code under test)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from conftest import domain_files

from domain_dumper.config import Config
from domain_dumper.exceptions import EXIT_OK, EXIT_WARNING
from domain_dumper.pipeline import run

FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

MIXED = """\
# a comment
example.com
EXAMPLE.com
api.example.com
https://www.example.net:8443/login?next=/a.b#frag
http://user:pw@admin.example.com/panel
*.wild.example.io
bücher.example
Nmap scan report for mail.example.org (10.0.0.5)
mail me: bob@example.com
see notes.txt and 1.2.3
../../etc/passwd
http://exa mple.com
"""


def cfg(out, *inputs, **kw) -> Config:
    return Config(inputs=tuple(inputs), output=out, **kw)


def read_summary(out):
    return json.loads((out / "reports" / "summary.json").read_text(encoding="utf-8"))


def test_mixed_input_produces_expected_records_and_files(write_input, out_dir):
    f = write_input("mixed.txt", MIXED)
    result = run(cfg(out_dir, f), now=FIXED_NOW)
    expected = [
        "admin.example.com",
        "api.example.com",
        "example.com",
        "mail.example.org",
        "wild.example.io",
        "www.example.net",
        "xn--bcher-kva.example",
    ]
    # "http://exa mple.com" is split by the space: "exa" is rejected, "mple.com" is a (known,
    # documented) false positive of free-text extraction.
    assert result.domains == sorted([*expected, "mple.com"])
    for domain in result.domains:
        file = out_dir / "domains" / f"{domain}.txt"
        assert file.read_text(encoding="utf-8") == f"{domain}\n"
    assert len(domain_files(out_dir)) == len(result.domains)
    assert "example.com.txt" in domain_files(out_dir) and "api.example.com.txt" in domain_files(
        out_dir
    )


def test_summary_statistics_are_accurate(write_input, out_dir):
    f = write_input(
        "a.txt", "example.com\nexample.com\nEXAMPLE.COM.\napi.example.com\n10.0.0.1\nfoo.txt\n"
    )
    run(cfg(out_dir, f), now=FIXED_NOW)
    s = read_summary(out_dir)
    assert s["schema_version"] == 1
    assert s["timestamp_utc"] == "2026-01-02T03:04:05Z"
    assert s["output_directory"] == str(out_dir.resolve())
    assert s["input_files_processed"] == 1
    assert s["candidates_extracted"] == 6
    assert s["valid_unique_domains"] == 2
    assert s["duplicates_removed"] == 2
    assert s["rejected_candidates"] == 2
    assert s["domain_files_written"] == 2
    assert s["domain_files_failed"] == 0
    assert s["manifest_entries"] == 2
    assert s["input_errors"] == []
    assert s["candidates_extracted"] == (
        s["valid_unique_domains"] + s["duplicates_removed"] + s["rejected_candidates"]
    )
    assert {r["value"] for r in s["rejected_samples"]} == {"10.0.0.1", "foo.txt"}


def test_counting_invariant_holds_on_messy_input(write_input, out_dir):
    f = write_input("mixed.txt", MIXED)
    run(cfg(out_dir, f), now=FIXED_NOW)
    s = read_summary(out_dir)
    assert s["candidates_extracted"] == (
        s["valid_unique_domains"] + s["duplicates_removed"] + s["rejected_candidates"]
    )
    assert s["domain_files_written"] == s["valid_unique_domains"]
    assert s["rejected_candidates"] >= 3


def test_manifest_lists_every_written_domain_sorted(write_input, out_dir):
    f = write_input("a.txt", "b.example.com\na.example.com\nc.example.org\n")
    run(cfg(out_dir, f))
    assert (out_dir / "manifest.txt").read_text() == "a.example.com\nb.example.com\nc.example.org\n"


def test_output_is_deterministic_across_runs_and_input_order(write_input, tmp_path):
    names = ["z.example.com", "a.example.com", "m.example.org", "a.example.com"]
    f1 = write_input("one.txt", "\n".join(names) + "\n")
    f2 = write_input("two.txt", "\n".join(reversed(names)) + "\n")
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    run(cfg(out1, f1), now=FIXED_NOW)
    run(cfg(out2, f2), now=FIXED_NOW)
    for rel in ("manifest.txt", "reports/summary.json"):
        a = (out1 / rel).read_text().replace(str(out1.resolve()), "OUT")
        b = (out2 / rel).read_text().replace(str(out2.resolve()), "OUT")
        assert a == b
    assert domain_files(out1) == domain_files(out2)


def test_multiple_files_are_merged_and_deduplicated(write_input, out_dir):
    a = write_input("a.txt", "shared.example.com\nonly-a.example.com\n")
    b = write_input("b.txt", "shared.example.com\nonly-b.example.com\n")
    result = run(cfg(out_dir, a, b))
    assert result.stats.input_files_processed == 2
    assert result.stats.duplicates == 1
    assert domain_files(out_dir) == [
        "only-a.example.com.txt",
        "only-b.example.com.txt",
        "shared.example.com.txt",
    ]


def test_recursive_directory(tmp_path, out_dir):
    root = tmp_path / "data"
    (root / "a" / "b").mkdir(parents=True)
    (root / "top.txt").write_text("top.example.com\n")
    (root / "a" / "mid.log").write_text("mid.example.com\n")
    (root / "a" / "b" / "low.csv").write_text("h\nlow.example.com\n")
    (root / "a" / "b" / "ignored.dat").write_text("ignored.example.com\n")
    flat = run(cfg(out_dir / "flat", root))
    deep = run(cfg(out_dir / "deep", root, recursive=True))
    assert flat.domains == ["top.example.com"]
    assert deep.domains == ["low.example.com", "mid.example.com", "top.example.com"]


def test_output_inside_input_directory_is_not_reread(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "a.txt").write_text("a.example.com\n")
    out = root / "dump"
    first = run(cfg(out, root, recursive=True))
    second = run(cfg(out, root, recursive=True))
    assert first.domains == second.domains == ["a.example.com"]
    assert second.stats.input_files_processed == 1  # the generated files were not read


def test_empty_inputs_succeed_with_zero_counts(write_input, out_dir):
    empty = write_input("empty.txt", "")
    blank = write_input("blank.txt", "\n\n   \n# only a comment\n")
    empty_json = write_input("empty.json", "")
    result = run(cfg(out_dir, empty, blank, empty_json), now=FIXED_NOW)
    assert result.exit_code == EXIT_OK
    assert result.domains == []
    assert domain_files(out_dir) == []
    assert (out_dir / "manifest.txt").read_text() == ""
    s = read_summary(out_dir)
    assert (s["candidates_extracted"], s["domain_files_written"], s["input_files_processed"]) == (
        0,
        0,
        3,
    )


def test_rerun_is_idempotent_and_reports_unchanged(write_input, out_dir):
    f = write_input("a.txt", "a.example.com\nb.example.com\n")
    first = run(cfg(out_dir, f))
    second = run(cfg(out_dir, f))
    assert first.write.written == 2
    assert second.write.written == 0
    assert len(second.write.unchanged) == 2
    assert read_summary(out_dir)["domain_files_unchanged"] == 2


def test_rerun_preserves_unrelated_and_previous_files_and_accumulates_manifest(
    write_input, out_dir
):
    first_in = write_input("first.txt", "old.example.com\n")
    run(cfg(out_dir, first_in))
    unrelated = out_dir / "domains" / "my-notes.md"
    unrelated.write_text("keep me")
    stray = out_dir / "keep.txt"
    stray.write_text("keep me too")

    second_in = write_input("second.txt", "new.example.com\n")
    run(cfg(out_dir, second_in))

    assert (out_dir / "domains" / "old.example.com.txt").read_text() == "old.example.com\n"
    assert (out_dir / "domains" / "new.example.com.txt").exists()
    assert unrelated.read_text() == "keep me"
    assert stray.read_text() == "keep me too"
    assert (out_dir / "manifest.txt").read_text() == "new.example.com\nold.example.com\n"
    assert read_summary(out_dir)["manifest_entries"] == 2


def test_conflicts_are_reported_and_data_preserved_by_default(write_input, out_dir):
    f = write_input("a.txt", "example.com\n")
    run(cfg(out_dir, f))
    target = out_dir / "domains" / "example.com.txt"
    target.write_text("hand edited\n")

    kept = run(cfg(out_dir, f))
    assert kept.exit_code == EXIT_WARNING
    assert kept.write.conflicts == ["example.com"]
    assert target.read_text() == "hand edited\n"
    s = read_summary(out_dir)
    assert s["conflicts"] == ["example.com"] and s["domain_files_conflicting"] == 1
    assert s["manifest_entries"] == 0  # a file with wrong content is not a correct record

    fixed = run(cfg(out_dir, f, overwrite=True))
    assert fixed.exit_code == EXIT_OK
    assert fixed.write.overwritten == ["example.com"]
    assert target.read_text() == "example.com\n"
    assert read_summary(out_dir)["manifest_entries"] == 1


def test_dry_run_creates_nothing_and_reports_plan(write_input, tmp_path):
    f = write_input("a.txt", "a.example.com\n")
    out = tmp_path / "never-created"
    result = run(cfg(out, f, dry_run=True))
    assert result.summary is None
    assert result.write.created == ["a.example.com"]
    assert not out.exists()


def test_path_traversal_attempts_cannot_escape_output(write_input, tmp_path):
    f = write_input(
        "evil.txt",
        "../../evil.com\n/etc/cron.d/x.com\n..\\..\\evil.org\nhttp://../evil.net\n"
        "a/../../b.example.com\nsafe.example.com\n",
    )
    out = tmp_path / "deep" / "out"
    result = run(cfg(out, f))
    created = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    allowed_prefixes = ("in/", "deep/out/")
    assert all(name.startswith(allowed_prefixes) for name in created), created
    assert "safe.example.com" in result.domains
    for name in domain_files(out):
        assert "/" not in name and "\\" not in name and not name.startswith(".")


def test_json_input_via_pipeline(write_input, out_dir):
    f = write_input(
        "scan.json",
        json.dumps(
            {"results": [{"url": "https://Api.Example.com:8443/v1"}, {"host": "db.example.org"}]}
        ),
    )
    result = run(cfg(out_dir, f))
    assert result.domains == ["api.example.com", "db.example.org"]


def test_malformed_json_is_a_recoverable_error(write_input, out_dir):
    bad = write_input("bad.json", "{oops")
    good = write_input("good.txt", "good.example.com\n")
    result = run(cfg(out_dir, bad, good))
    assert result.exit_code == EXIT_WARNING
    assert result.domains == ["good.example.com"]
    assert result.stats.input_errors[0]["source"] == str(bad)


def test_large_input_streams_correctly(write_input, out_dir):
    lines = "".join(f"host{i}.example.com\n" for i in range(20000))
    f = write_input("big.txt", lines + lines)
    result = run(cfg(out_dir, f))
    assert result.stats.valid_unique == 20000
    assert result.stats.duplicates == 20000
    assert len(domain_files(out_dir)) == 20000
