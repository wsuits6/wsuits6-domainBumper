import pytest

from domain_dumper.normalizer import normalize_host


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.COM", "example.com"),
        ("EXAMPLE.com.", "example.com"),
        ("  example.com  ", "example.com"),
        ('"example.com",', "example.com"),
        ("(api.example.com)", "api.example.com"),
        ("*.example.com", "example.com"),
        (".example.com", "example.com"),
        ("API.Example.COM", "api.example.com"),  # subdomain preserved, not reduced
    ],
)
def test_ascii_normalization(raw, expected):
    assert normalize_host(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("bücher.example", "xn--bcher-kva.example"),
        ("MÜNCHEN.de", "xn--mnchen-3ya.de"),
        ("sub.bücher.example", "sub.xn--bcher-kva.example"),
        ("bücher。example", "xn--bcher-kva.example"),  # ideographic full stop
    ],
)
def test_idn_converted_to_punycode(raw, expected):
    assert normalize_host(raw) == expected


def test_already_punycode_is_stable():
    assert normalize_host("xn--bcher-kva.example") == "xn--bcher-kva.example"


@pytest.mark.parametrize("raw", ["", "   ", ".", "*.", '""'])
def test_empty_results_return_none(raw):
    assert normalize_host(raw) is None


def test_unconvertible_idn_label_returns_none():
    assert normalize_host("ü" * 70 + ".com") is None  # label too long after IDNA
    assert normalize_host("ü..com") is None  # empty label
