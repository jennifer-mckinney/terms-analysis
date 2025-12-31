from __future__ import annotations

import hashlib
import difflib
from typing import Tuple


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def diff_summary(old: str, new: str, max_lines: int = 8) -> Tuple[int, str]:
    old_lines = old.splitlines() if old else []
    new_lines = new.splitlines() if new else []
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    change_count = max(added + removed, 0)
    summary_lines = [line for line in diff if line.startswith(("+", "-")) and line[1:].strip()]
    summary = "\n".join(summary_lines[:max_lines]).strip()
    return change_count, summary
