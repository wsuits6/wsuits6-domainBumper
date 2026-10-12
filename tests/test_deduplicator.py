from domain_dumper.deduplicator import Deduplicator


def test_duplicates_are_counted_and_not_repeated():
    d = Deduplicator()
    assert d.add("example.com") is True
    assert d.add("example.com") is False
    assert d.add("example.com") is False
    assert d.unique_count == 1
    assert d.duplicates == 2
    assert d.sorted_domains() == ["example.com"]


def test_subdomains_are_distinct_records():
    d = Deduplicator()
    for name in ("example.com", "api.example.com", "www.example.com", "api.example.com"):
        d.add(name)
    assert d.sorted_domains() == ["api.example.com", "example.com", "www.example.com"]
    assert d.duplicates == 1


def test_sorting_is_deterministic_regardless_of_insertion_order():
    names = ["b.example.com", "a.example.org", "c.example.net", "a.example.com", "xn--a-1.com"]
    forward, backward = Deduplicator(), Deduplicator()
    for n in names:
        forward.add(n)
    for n in reversed(names):
        backward.add(n)
    assert forward.sorted_domains() == backward.sorted_domains() == sorted(names)
