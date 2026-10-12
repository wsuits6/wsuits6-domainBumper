import io
import sys
from pathlib import Path

import pytest

from domain_dumper.exceptions import InputError
from domain_dumper.sources import (
    discover_inputs,
    iter_lines,
    parse_csv,
    parse_json,
    parse_txt,
    read_fragments,
    source_format,
)


def test_parse_txt_skips_blank_and_comment_lines():
    text = "# comment\n\nexample.com\n   \n  # indented comment\n  google.com  \n"
    assert list(parse_txt(io.StringIO(text))) == ["example.com", "google.com"]


def test_parse_txt_keeps_text_after_a_hash_inside_a_line():
    assert list(parse_txt(io.StringIO("found #1 example.com\n"))) == ["found #1 example.com"]


def test_parse_json_reads_keys_and_values_at_any_depth():
    text = '{"a.example.com": ["b.example.com", {"x": "https://c.example.com/p", "n": 5}]}'
    fragments = set(parse_json(io.StringIO(text)))
    assert fragments == {"a.example.com", "b.example.com", "x", "n", "https://c.example.com/p"}


def test_parse_json_lines():
    text = '{"host": "a.example.com"}\n\n{"host": "b.example.com"}\n'
    assert set(parse_json(io.StringIO(text))) == {"host", "a.example.com", "b.example.com"}


def test_parse_json_invalid_raises_input_error():
    with pytest.raises(InputError, match="invalid JSON"):
        list(parse_json(io.StringIO("{not json")))


def test_parse_json_empty_is_empty():
    assert list(parse_json(io.StringIO("  \n"))) == []


def test_parse_csv_yields_every_cell():
    text = 'host,note\na.example.com,"hello, b.example.com"\n,\n'
    assert list(parse_csv(io.StringIO(text))) == [
        "host",
        "note",
        "a.example.com",
        "hello, b.example.com",
    ]


def test_iter_lines_splits_long_lines_at_whitespace():
    line = "aaa.example.com bbb.example.com ccc.example.com"
    pieces = list(iter_lines(io.StringIO(line + "\nnext.example.org\n"), limit=20))
    # no hostname is cut in half, even though each chunk read is only 20 characters
    assert [p.strip() for p in pieces] == [
        "aaa.example.com",
        "bbb.example.com",
        "ccc.example.com",
        "next.example.org",
    ]


def test_iter_lines_handles_unbroken_token_longer_than_limit():
    assert list(iter_lines(io.StringIO("x" * 50), limit=20)) == ["x" * 20, "x" * 20, "x" * 10]


def test_iter_lines_without_trailing_newline():
    assert list(iter_lines(io.StringIO("a.example.com"))) == ["a.example.com"]


def test_source_format_resolution():
    assert source_format(Path("a.json"), "auto") == "json"
    assert source_format(Path("a.CSV"), "auto") == "csv"
    assert source_format(Path("a.txt"), "auto") == "txt"
    assert source_format(Path("a.log"), "auto") == "txt"
    assert source_format(Path("a.json"), "txt") == "txt"
    assert source_format(None, "auto") == "txt"
    assert source_format(None, "json") == "json"


def test_discover_non_recursive_only_lists_top_level(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.json").write_text("{}")
    (tmp_path / "ignored.bin").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("x")
    files, problems = discover_inputs([tmp_path], recursive=False)
    assert [f.name for f in files] == ["a.txt", "b.json"]
    assert problems == []


def test_discover_recursive_is_sorted_and_skips_hidden_dirs(tmp_path):
    (tmp_path / "z.txt").write_text("x")
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "sub" / "deep" / "d.csv").write_text("x")
    (tmp_path / "sub" / "c.txt").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "h.txt").write_text("x")
    files, _ = discover_inputs([tmp_path], recursive=True)
    assert [f.relative_to(tmp_path).as_posix() for f in files] == [
        "z.txt",
        "sub/c.txt",
        "sub/deep/d.csv",
    ]


def test_discover_deduplicates_and_reports_problems(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    (tmp_path / "empty").mkdir()
    files, problems = discover_inputs(
        [f, f, tmp_path / "missing.txt", tmp_path / "empty"], recursive=False
    )
    assert files == [f]
    assert {source for source, _ in problems} == {
        str(tmp_path / "missing.txt"),
        str(tmp_path / "empty"),
    }


def test_discover_excludes_output_directory(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    out = tmp_path / "out" / "domains"
    out.mkdir(parents=True)
    (out / "example.com.txt").write_text("example.com\n")
    files, _ = discover_inputs([tmp_path], recursive=True, exclude_dir=tmp_path / "out")
    assert [f.name for f in files] == ["a.txt"]


def test_read_fragments_rejects_binary_file(tmp_path):
    f = tmp_path / "blob.txt"
    f.write_bytes(b"example.com\x00\x01\x02")
    with pytest.raises(InputError, match="binary"):
        list(read_fragments(f, "txt"))


def test_read_fragments_missing_file(tmp_path):
    with pytest.raises(InputError, match="cannot read"):
        list(read_fragments(tmp_path / "nope.txt", "txt"))


def test_read_fragments_tolerates_bad_utf8_and_bom(tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"\xef\xbb\xbfexample.com\n\xff\xfebad.example.org\n")
    assert list(read_fragments(f, "txt"))[0] == "example.com"


def test_read_fragments_from_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"a.example.com\n")))
    assert list(read_fragments(None, "txt")) == ["a.example.com"]
