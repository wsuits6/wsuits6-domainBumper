# domain-dumper

Extracts domain names from files, directories or standard input, normalizes and deduplicates
them, and writes **one text file per domain** plus a manifest and a JSON summary report.
The core pipeline is standard-library only and works fully offline. It never scans or contacts
anything: it only reads the data you give it.

```
output/domain-dump/
├── domains/
│   ├── api.example.com.txt      # contains: api.example.com
│   ├── example.com.txt          # contains: example.com
│   └── xn--bcher-kva.example.txt
├── reports/
│   └── summary.json
└── manifest.txt
```

## Requirements and installation

* Python **3.10 or newer** (developed and tested on 3.13 only; 3.10-3.12 are declared but not
  tested here).
* No runtime dependencies. `pytest` and `ruff` are needed only for development.

```bash
cd domain-dumper
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # installs the `domain-dumper` command plus pytest and ruff
```

Without installing, run it straight from the source tree:

```bash
PYTHONPATH=src python3 -m domain_dumper.cli --help
```

## Usage

```bash
# one file
python -m domain_dumper.cli --input data/input/sample.txt --output output/domain-dump

# several files (repeat --input, or pass several paths after one --input)
python -m domain_dumper.cli --input a.txt --input b.json --output output/domain-dump
python -m domain_dumper.cli --input a.txt b.json c.csv --output output/domain-dump

# a directory (top level only), or recursively
python -m domain_dumper.cli --input data/input --output output/domain-dump
python -m domain_dumper.cli --input data/input --recursive --output output/domain-dump

# standard input (can be combined with --input)
cat domains.txt | python -m domain_dumper.cli --stdin --output output/domain-dump
subfinder -d example.com -silent | python -m domain_dumper.cli --stdin --output output/domain-dump

# preview without writing anything
python -m domain_dumper.cli --input data/input --output output/domain-dump --dry-run
```

| Option | Meaning |
| --- | --- |
| `--input PATH [PATH ...]` | File or directory. Repeatable. |
| `--output PATH` | Destination directory (default `output/domain-dump`). |
| `--stdin` | Also read piped input. Fails with a usage error if stdin is a terminal. |
| `--format {auto,txt,json,csv}` | Force a parser for every input. `auto` picks by extension. |
| `--recursive` | Search input directories recursively. |
| `--overwrite` | Replace existing domain files whose content differs. |
| `--dry-run` | Extract and validate, report what would change, write nothing. |
| `--quiet` / `--verbose` | Warnings only / diagnostic detail. Cannot be combined. |
| `--version`, `--help` | As expected. |

Exit codes: `0` success; `1` finished with recoverable input errors or untouched conflicting
files; `2` invalid or incompatible arguments; `3` no usable input could be read; `4` output
could not be written.

## Supported input

| Format | Selected when | What is read |
| --- | --- | --- |
| Plain text | `.txt .log .list .lst .out .tsv`, any other extension given explicitly, and stdin | Every line; hostnames, domains and URLs are found inside surrounding text (scan output, logs). Lines starting with `#` are comments. |
| JSON / JSON Lines | `.json`, or `--format json` | Every string key and value at any depth, so `{"url": "https://a.example.com/x"}` works. |
| CSV | `.csv`, or `--format csv` | Every non-empty cell, so no column name needs configuring. |

Directory scans only pick up the suffixes above and skip hidden directories and the output
directory. A file given explicitly with `--input` is always read. Stdin is treated as plain
text unless you pass `--format json` or `--format csv`. New formats are added by writing a
parser in `sources.py` and registering it in `PARSERS`.

## How normalization works

Candidates are found by parsing URLs with `urllib.parse` (any `scheme://`, including ports,
paths, queries, fragments and credentials) and by scanning the remaining text for dotted
hostnames. Each candidate is then normalized, validated, deduplicated and sorted.

* Lowercased. One trailing root dot removed (`Example.COM.` -> `example.com`).
* Internationalized names converted to punycode with the stdlib IDNA codec
  (`bücher.example` -> `xn--bcher-kva.example`).
* **Subdomains are never reduced**: `api.example.com` and `example.com` are separate records.
* A leading wildcard (`*.example.com`) or dot is stripped, so it yields `example.com`.
* Rejected, and counted as rejected: IPv4/IPv6 addresses, version numbers (`1.2.3`), e-mail
  addresses (the local part is masked in reports), single-label names (`localhost`), names with
  empty labels, bad hyphens or invalid characters, labels over 63 or names over 253 characters,
  malformed punycode, and names ending in a common file extension that is not a real TLD
  (`notes.txt`, `data.json`). Real TLDs that look like extensions (`.py`, `.md`, `.sh`, `.zip`)
  are accepted.
* Underscores are allowed in labels (`_dmarc.example.com`). The TLD must be alphabetic
  (2+ letters) or punycode. There is no public-suffix list, so `example.invalid` and
  `foo.bar` are both accepted.
* Sorting is plain code-point order on the normalized ASCII names.

## Output files

* `domains/<domain>.txt` contains exactly `<domain>\n` (UTF-8). The name is the normalized
  domain; the writer re-validates every name so nothing can escape `domains/`.
* `manifest.txt` lists the domains whose file exists in `domains/` and contains the correct
  content, one per line, sorted. It is rebuilt from the directory on every run, so after reruns
  it lists old and new records alike. Files that are unrelated, mis-named or have unexpected
  content are not listed.
* `reports/summary.json` (schema version 1):

| Key | Meaning |
| --- | --- |
| `schema_version`, `tool_version` | Schema and tool versions. |
| `timestamp_utc` | `YYYY-MM-DDTHH:MM:SSZ`. |
| `output_directory` | Absolute path. |
| `overwrite` | Whether `--overwrite` was used. |
| `input_files_processed` / `input_files_failed` | Sources read successfully / failed (stdin counts as one). |
| `candidates_extracted` | Every host-like candidate found, duplicates and rejects included. |
| `valid_unique_domains` | Distinct valid domains. |
| `duplicates_removed` | Repeat occurrences dropped. |
| `rejected_candidates` | Candidates that failed normalization or validation. |
| `domain_files_written` | Files created or replaced this run (`created` + `overwritten`). |
| `domain_files_created`, `_overwritten`, `_unchanged` | Breakdown. Unchanged files are not rewritten. |
| `domain_files_conflicting` | Existing files with different content, left alone. |
| `domain_files_failed` | Files that could not be written. Never counted as written. |
| `manifest_entries` | Lines in `manifest.txt`. |
| `input_errors`, `write_errors`, `conflicts`, `rejected_samples` | Details (lists are capped at 100, 100, 100 and 20 entries). |

Invariant: `candidates_extracted = valid_unique_domains + duplicates_removed + rejected_candidates`.

## Reruns, overwrite and dry run

Defaults favor data preservation. A rerun creates missing files, leaves identical files
untouched (no rewrite, mtime unchanged), and **never deletes anything**, including domain
files for domains absent from the latest input and any unrelated files in the output tree.
Every write goes to a temporary file in the same directory followed by an atomic rename, so an
interruption leaves either the old file or the complete new one.

If a domain file already exists with different content it is reported as a conflict and left
as is (exit code 1). `--overwrite` replaces such files. A symlink or directory in the way is
reported as a write failure and never followed.

`--dry-run` reads inputs and inspects existing output, prints what would be created,
overwritten or left unchanged, and writes nothing, not even the output directory. Inputs
located inside the output directory are refused so generated files are never read back or
overwritten; an output directory nested inside an input directory is skipped during scans.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest              # or: PYTHONPATH=src python3 -m pytest
ruff check . && ruff format --check .
```

Tests use temporary directories only and need no network. Three tests that rely on `chmod`
are skipped when run as root (equivalent monkeypatched tests still run); run the suite as a
normal user to execute them.

## Layout

```
src/domain_dumper/
  cli.py          argument parsing, logging setup, exit codes
  config.py       Config dataclass and option validation
  pipeline.py     orchestration: read -> extract -> normalize -> validate -> dedupe -> write
  sources.py      input discovery, safe reading, format parsers (txt/json/csv)
  extractor.py    finds hostname candidates in text and URLs
  normalizer.py   lowercase / IDNA / wildcard / root-dot handling
  validator.py    domain syntax rules
  deduplicator.py unique set and duplicate counter
  writer.py       every write: domain files, manifest, summary (atomic)
  manifest.py     manifest rendering and on-disk verification scan
  reporting.py    run statistics and summary.json
  exceptions.py   error types and exit codes
  __main__.py     enables `python -m domain_dumper`
tests/            pytest suite
data/input/       sample input
output/           default output location (contents git-ignored)
```

## Known limitations

* No live collection or enumeration is implemented, by design. Import results from your own
  authorized tools via files or stdin instead.
* Free-text extraction can produce false positives, such as `end.Next` in prose or `README.md`
  (`.md` is a real TLD). It can also split a name with a space in it. There is no
  public-suffix or TLD list; rejected candidates are visible with `--verbose` and in
  `rejected_samples`.
* `.invalid`, `.test` and similar reserved names are accepted.
* Domains of 252 or 253 characters (253 is the DNS maximum) exceed the 255-byte filename limit
  once `.txt` is added; such writes fail with exit code 4 and are reported, not skipped
  silently.
* JSON must be loaded whole (capped at 64 Mi characters); text and CSV are streamed. Binary
  files, including UTF-16 text, are skipped with an input error.
* Stdin format is never auto-detected; use `--format` for JSON or CSV on stdin.
* A manifest scan reads every file in `domains/`, which adds time for very large outputs.
* Developed and tested on Linux with Python 3.13 only.
