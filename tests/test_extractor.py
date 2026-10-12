import pytest

from domain_dumper.extractor import extract_hosts, redact


def hosts(text: str) -> list[str]:
    return list(extract_hosts(text))


def test_plain_domains():
    assert hosts("example.com") == ["example.com"]
    assert hosts("example.com google.com, api.example.org.") == [
        "example.com",
        "google.com",
        "api.example.org.",
    ]


def test_no_dot_means_no_candidates():
    assert hosts("just some words") == []
    assert hosts("") == []


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("http://example.com", "example.com"),
        ("https://example.com/", "example.com"),
        ("https://Example.COM/Path", "example.com"),
        ("http://example.com:8080", "example.com"),
        ("https://example.com:8443/a/b/c.html", "example.com"),
        ("https://example.com/search?q=a.b.c&next=http://other.org", "example.com"),
        ("https://example.com/page#section.two", "example.com"),
        ("https://example.com?x=1", "example.com"),
        ("https://user:pw@example.com/x", "example.com"),
        ("ftp://files.example.org/pub", "files.example.org"),
        ("https://bücher.example/", "bücher.example"),
    ],
)
def test_urls_yield_only_the_hostname(url, host):
    assert hosts(url)[0] == host


def test_url_keeps_subdomain_and_is_not_reduced():
    assert hosts("https://api.example.com/v1") == ["api.example.com"]


def test_url_inside_text_with_trailing_punctuation():
    assert hosts("see (https://example.com/a), then https://x.example.org.") == [
        "example.com",
        "x.example.org",
    ]


def test_bare_host_with_port_and_path():
    assert hosts("example.com:8080/index.html") == ["example.com"]


def test_scan_style_text():
    line = "Nmap scan report for mail.example.org (10.0.0.5)"
    assert hosts(line) == ["mail.example.org", "10.0.0.5"]


def test_wildcards_keep_their_base_name():
    assert hosts("*.example.com") == ["example.com"]
    assert hosts("cert SAN: *.api.example.com, example.com") == ["api.example.com", "example.com"]


def test_email_is_not_a_domain_and_is_masked():
    assert hosts("contact first.last@example.com now") == ["***@example.com"]


def test_ipv6_url_hostname_has_no_brackets():
    assert hosts("http://[::1]:8080/x") == ["::1"]


def test_malformed_url_is_yielded_redacted_not_dropped():
    result = hosts("http://user:secret@[bad/path")
    assert len(result) == 1
    assert "secret" not in result[0]


def test_hostless_url_is_yielded_so_it_can_be_counted_as_rejected():
    assert hosts("file:///etc/passwd") == ["file:///etc/passwd"]


def test_path_segments_are_not_hosts():
    assert hosts("open /var/log/app.example.log please") == []


def test_redact_masks_credentials_and_truncates():
    assert redact("http://u:p@host/x") == "http://***@host/x"
    assert redact("x" * 200).endswith("...")
    assert len(redact("x" * 200)) == 103
