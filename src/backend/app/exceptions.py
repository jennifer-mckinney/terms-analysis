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


class InvalidTextError(ValueError):
    """Extracted or fetched document text is not valid Unicode text (#184).

    It holds an unpaired UTF-16 surrogate (U+D800-U+DFFF), which can't be
    encoded as UTF-8, so it would fail later in the LLM request, the DB or the
    JSON response. The message is fixed: it never echoes the document text.
    A ``ValueError`` so that a caller without its own branch still treats it
    as bad input, never as a server error.
    """

    MESSAGE = (
        "This document contains characters that are not valid text "
        "(an unpaired surrogate), so it can't be analysed. "
        "Save it again as UTF-8, or paste the policy text instead."
    )

    def __init__(self) -> None:
        super().__init__(self.MESSAGE)
