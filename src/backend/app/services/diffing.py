from __future__ import annotations

import hashlib
import difflib
import re
from typing import Tuple, List, Dict, Literal


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


def tokenize_text(text: str) -> List[Tuple[str, int]]:
    """
    Tokenize text into words and punctuation.
    Returns list of (token, line_number) tuples.
    """
    tokens = []
    lines = text.splitlines()
    
    for line_num, line in enumerate(lines, start=1):
        # Split by whitespace and punctuation, keeping punctuation as separate tokens
        # This regex keeps words and single punctuation as tokens
        token_pattern = r'\b\w+\b|[.,:;!?"\']'
        matches = re.finditer(token_pattern, line)
        for match in matches:
            tokens.append((match.group(), line_num))
    
    return tokens


def calculate_token_severity(token: str, context: str = "") -> Literal["low", "medium", "high"]:
    """
    Estimate severity of a token change based on keywords.
    """
    critical_keywords = {
        "personal", "data", "liability", "indemnify", "warrant", "confidential",
        "proprietary", "payment", "billing", "credit", "financial", "health",
        "sensitive", "children", "minor", "genetic", "biometric", "tracking",
        "delete", "retention", "terminate", "cancel", "liability", "arbitration",
        "jurisdiction", "governing", "law", "compliance", "privacy", "gdpr",
        "ccpa", "hipaa", "glba", "pci", "algorithm", "automated", "decision"
    }
    
    high_keywords = {
        "use", "store", "share", "disclose", "transfer", "process",
        "collect", "right", "permission", "consent", "liability",
        "limit", "exclude", "restriction", "modification", "change"
    }
    
    token_lower = token.lower().strip('.,;:!?"\' ')
    
    if token_lower in critical_keywords:
        return "high"
    elif token_lower in high_keywords:
        return "medium"
    else:
        return "low"


def diff_tokens(old_text: str, new_text: str) -> Dict[str, List[Dict]]:
    """
    Perform token-level diff between two policy texts.
    Returns dict with 'added', 'removed', 'unchanged' lists containing token diffs.
    """
    old_tokens = tokenize_text(old_text)
    new_tokens = tokenize_text(new_text)
    
    # Get just the token strings for comparison
    old_token_strings = [t[0] for t in old_tokens]
    new_token_strings = [t[0] for t in new_tokens]
    
    # Use SequenceMatcher for token-level diff
    matcher = difflib.SequenceMatcher(None, old_token_strings, new_token_strings)
    
    added = []
    removed = []
    unchanged = []
    
    severity_counts = {"high": 0, "medium": 0, "low": 0}
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            # Unchanged tokens
            for idx in range(j1, j2):
                token, line_num = new_tokens[idx]
                severity = calculate_token_severity(token)
                unchanged.append({
                    "token": token,
                    "line_number": line_num,
                    "severity": severity,
                })
        elif tag == "insert":
            # Added tokens
            for idx in range(j1, j2):
                token, line_num = new_tokens[idx]
                severity = calculate_token_severity(token)
                added.append({
                    "token": token,
                    "line_number": line_num,
                    "severity": severity,
                })
                severity_counts[severity] += 1
        elif tag == "delete":
            # Removed tokens
            for idx in range(i1, i2):
                token, line_num = old_tokens[idx]
                severity = calculate_token_severity(token)
                removed.append({
                    "token": token,
                    "line_number": line_num,
                    "severity": severity,
                })
                severity_counts[severity] += 1
        elif tag == "replace":
            # Both added and removed
            for idx in range(i1, i2):
                token, line_num = old_tokens[idx]
                severity = calculate_token_severity(token)
                removed.append({
                    "token": token,
                    "line_number": line_num,
                    "severity": severity,
                })
                severity_counts[severity] += 1
            for idx in range(j1, j2):
                token, line_num = new_tokens[idx]
                severity = calculate_token_severity(token)
                added.append({
                    "token": token,
                    "line_number": line_num,
                    "severity": severity,
                })
                severity_counts[severity] += 1
    
    change_count = len(added) + len(removed)
    
    return {
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "change_count": change_count,
        "severity_summary": severity_counts,
    }

