from __future__ import annotations


class CorpusMismatchError(Exception):
    """Corpus bundle MANIFEST does not match expected state."""

    def __init__(self, dimension: str, expected: str, actual: str) -> None:
        self.dimension = dimension
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Corpus mismatch on {dimension}: expected {expected!r}, got {actual!r}"
        )
