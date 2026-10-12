"""Syntax validation for normalized domain names."""

from __future__ import annotations

import re

MAX_DOMAIN_LENGTH = 253
MAX_LABEL_LENGTH = 63

# Letters, digits and hyphens, never starting or ending with a hyphen. Underscores are
# tolerated because they occur in real DNS names (e.g. _dmarc.example.com).
_LABEL_RE = re.compile(r"[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?")
# A top-level label is alphabetic (2+ letters) or punycode. Digits-only labels would be IPs.
_TLD_RE = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")

# Common file extensions that are not real TLDs, so "notes.txt" is not taken for a domain.
# Extensions that are also real TLDs (.py, .md, .sh, .zip, ...) are intentionally not listed.
_FILE_EXTENSIONS = frozenset(
    "txt json csv tsv html htm css js jsx png jpg jpeg gif svg pdf log xml yml yaml gz tar tgz "
    "php exe dll conf cfg ini bak tmp doc docx xls xlsx ppt pptx lst out".split()
)


def validate_domain(domain: str) -> str | None:
    """Return ``None`` if ``domain`` is a valid normalized name, else the reason it is not."""
    if not domain:
        return "empty"
    if not domain.isascii():
        return "contains non-ASCII characters (expected IDNA/punycode form)"
    if len(domain) > MAX_DOMAIN_LENGTH:
        return f"longer than {MAX_DOMAIN_LENGTH} characters"
    labels = domain.split(".")
    if len(labels) < 2:
        return "single label (a dotted domain name is required)"
    for label in labels:
        if not label:
            return "empty label (leading, trailing or doubled dot)"
        if len(label) > MAX_LABEL_LENGTH:
            return f"label longer than {MAX_LABEL_LENGTH} characters"
        if not _LABEL_RE.fullmatch(label):
            return "label has invalid characters or starts/ends with a hyphen"
        if label.startswith("xn--") and not _is_valid_punycode(label):
            return "malformed punycode label"
    tld = labels[-1]
    if tld.isdigit():
        return "numeric top-level label (IP address or version number)"
    if not _TLD_RE.fullmatch(tld):
        return "invalid top-level label"
    if tld in _FILE_EXTENSIONS:
        return "looks like a file name, not a domain"
    return None


def is_valid_domain(domain: str) -> bool:
    """Return True if ``domain`` passes :func:`validate_domain`."""
    return validate_domain(domain) is None


def _is_valid_punycode(label: str) -> bool:
    try:
        label.encode("ascii").decode("idna")
    except UnicodeError:
        return False
    return True
