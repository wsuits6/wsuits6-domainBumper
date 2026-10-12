"""Track unique domains and count the duplicates that were dropped."""

from __future__ import annotations


class Deduplicator:
    """Collects normalized domains; ``api.example.com`` and ``example.com`` stay distinct."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.duplicates = 0

    def add(self, domain: str) -> bool:
        """Record ``domain``. Return True if it was new, False if it was a duplicate."""
        if domain in self._seen:
            self.duplicates += 1
            return False
        self._seen.add(domain)
        return True

    @property
    def unique_count(self) -> int:
        return len(self._seen)

    def sorted_domains(self) -> list[str]:
        """Unique domains in plain lexicographic (code point) order."""
        return sorted(self._seen)
