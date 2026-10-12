import pytest

from domain_dumper.validator import is_valid_domain, validate_domain


@pytest.mark.parametrize(
    "domain",
    [
        "example.com",
        "api.example.com",
        "a.b.c.d.example.co.uk",
        "xn--bcher-kva.example",
        "my-host.example.org",
        "_dmarc.example.com",
        "123.example.com",
        "a.io",
        "example.xn--p1ai",
        ("a" * 63) + ".com",
    ],
)
def test_valid_domains(domain):
    assert validate_domain(domain) is None
    assert is_valid_domain(domain)


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "localhost",  # single label
        "1.2.3.4",  # IPv4
        "10.0.0.5",
        "1.2.3",  # version number
        "::1",  # IPv6
        "-bad.example.com",
        "bad-.example.com",
        "a..example.com",  # empty label
        ".example.com",
        "example.com.",  # not normalized: root dot must already be gone
        "exa mple.com",
        "foo@example.com",
        "example.c",  # one-letter TLD
        "example.c0m",
        "Example.com",  # not lowercased
        "bücher.example",  # not IDNA-encoded
        ("a" * 64) + ".com",  # label too long
        ("a." * 130) + "com",  # name too long
        "xn--.com",
        "xn--abc.com",  # malformed punycode
        "notes.txt",
        "data.json",
        "https://example.com",
    ],
)
def test_invalid_domains(domain):
    assert validate_domain(domain) is not None
    assert not is_valid_domain(domain)


def test_longest_legal_name_is_accepted():
    domain = ".".join(["a" * 61] * 4 + ["com"])[:253].rstrip(".")
    assert len(domain) <= 253
    assert is_valid_domain(domain)


def test_real_tlds_that_look_like_extensions_are_accepted():
    for tld in ("py", "md", "sh", "zip", "so"):
        assert is_valid_domain(f"example.{tld}")
