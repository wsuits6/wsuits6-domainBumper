"""Find candidate hostnames inside free-form text."""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlsplit

# scheme://anything-up-to-whitespace-or-quote
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s<>\"'`]+")
_EMAIL_RE = re.compile(r"[\w.+%\-]+@([\w\-]+(?:\.[\w\-]+)+)")
# A leading "*." or "." glued to the start of a token (wildcard / cookie-style domains).
_WILDCARD_RE = re.compile(r"(?<![\w@.\-])\*?\.(?=\w)")
# dotted tokens: not part of a longer word, path, or e-mail address.
_HOST_RE = re.compile(r"(?<![\w@./\-])(?:[\w\-]+\.)+[\w\-]+\.?(?![\w@\-])")
_CREDENTIALS_RE = re.compile(r"(?<=://)[^/@\s]*@")
_URL_TRAILING = ".,;:!?)}>'\""


def extract_hosts(text: str) -> Iterator[str]:
    """Yield every host-like candidate found in ``text``, in order, duplicates included.

    Candidates are *not* guaranteed to be valid domains: IP addresses, version numbers and
    e-mail addresses are yielded too, so that the caller can count them as rejected rather
    than silently dropping them. E-mail local parts are masked.
    """
    if "." not in text and "://" not in text:
        return  # fast path: nothing host-like (URLs such as http://[::1]/ have no dot)
    for match in _URL_RE.finditer(text):
        yield _host_from_url(match.group())
    remainder = _URL_RE.sub(" ", text)
    for match in _EMAIL_RE.finditer(remainder):
        yield "***@" + match.group(1)
    remainder = _EMAIL_RE.sub(" ", remainder)
    remainder = _WILDCARD_RE.sub(" ", remainder)
    for match in _HOST_RE.finditer(remainder):
        yield match.group()


def redact(text: str, limit: int = 100) -> str:
    """Mask URL credentials and truncate, so rejected values are safe to log or report."""
    cleaned = _CREDENTIALS_RE.sub("***@", text)
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "..."


def _host_from_url(url: str) -> str:
    url = url.rstrip(_URL_TRAILING if "[" in url else _URL_TRAILING + "]")
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return redact(url)
    return host or redact(url)
