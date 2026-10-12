"""Turn a raw host string into a canonical ASCII domain name."""

from __future__ import annotations

# Characters that commonly wrap a hostname in prose, JSON, CSV or logs.
_EDGE_CHARS = " \t\r\n\"'`<>()[]{},;"


def normalize_host(raw: str) -> str | None:
    """Return the canonical form of ``raw``, or ``None`` if it cannot be normalized.

    Rules, applied in order:

    * surrounding whitespace, quotes and brackets are removed;
    * a leading wildcard label (``*.``) or leading dot is removed;
    * one trailing DNS root dot is removed;
    * ASCII names are lowercased;
    * names containing non-ASCII characters are converted to IDNA/punycode
      (``bücher.example`` -> ``xn--bcher-kva.example``).

    Subdomains are never reduced: ``api.example.com`` stays ``api.example.com``.
    This function does not judge validity; see :mod:`domain_dumper.validator`.
    """
    host = raw.strip(_EDGE_CHARS)
    if host.startswith("*."):
        host = host[2:]
    elif host.startswith("."):
        host = host[1:]
    if host.endswith("."):
        host = host[:-1]
    if not host:
        return None
    if host.isascii():
        return host.lower()
    try:
        return host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
