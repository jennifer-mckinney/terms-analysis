from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, List

from app.services.rules import PATTERNS, detect_findings


def _default_dataset_path() -> Path:
    return Path(__file__).resolve().parent.parent / "evaluation" / "gold_dataset.json"


def _categories() -> List[str]:
    return sorted({rule.category for rule in PATTERNS})


def _f1_scores(golds: List[bool], preds: List[bool]) -> Dict[str, float]:
    tp = sum(1 for g, p in zip(golds, preds) if g and p)
    fp = sum(1 for g, p in zip(golds, preds) if (not g) and p)
    fn = sum(1 for g, p in zip(golds, preds) if g and (not p))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def _cohens_kappa(golds: List[bool], preds: List[bool]) -> float:
    tp = sum(1 for g, p in zip(golds, preds) if g and p)
    fp = sum(1 for g, p in zip(golds, preds) if (not g) and p)
    fn = sum(1 for g, p in zip(golds, preds) if g and (not p))
    tn = sum(1 for g, p in zip(golds, preds) if (not g) and (not p))
    n = len(golds)
    if n == 0:
        return 0.0
    po = (tp + tn) / n
    p_yes_gold = (tp + fn) / n
    p_yes_pred = (tp + fp) / n
    p_no_gold = (tn + fp) / n
    p_no_pred = (tn + fn) / n
    pe = (p_yes_gold * p_yes_pred) + (p_no_gold * p_no_pred)
    if pe >= 1:
        return 0.0
    return (po - pe) / (1 - pe)


def _analyze_doc(text: str, jurisdictions: List[str], rules_only: bool) -> List[str]:
    if rules_only:
        findings = detect_findings(text, jurisdictions)
        return [finding.category for finding in findings]
    from app.services.analyzer import analyze_text
    result = asyncio.run(analyze_text(text, jurisdictions))
    return [finding.category for finding in result.payload.findings]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate analysis quality against a gold dataset.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_default_dataset_path(),
        help="Path to the gold dataset JSON file.",
    )
    parser.add_argument(
        "--rules-only",
        action="store_true",
        help="Skip LM Studio and evaluate using rule-based findings only.",
    )
    args = parser.parse_args()

    data = json.loads(args.dataset.read_text())
    categories = _categories()
    per_category: Dict[str, Dict[str, List[bool]]] = {
        category: {"gold": [], "pred": []} for category in categories
    }

    for item in data:
        text = item["text"]
        jurisdictions = item.get("jurisdictions") or ["US-CA", "GDPR"]
        expected = set(item.get("expected_categories", []))
        predicted = set(_analyze_doc(text, jurisdictions, args.rules_only))
        for category in categories:
            per_category[category]["gold"].append(category in expected)
            per_category[category]["pred"].append(category in predicted)

    print("Category | Precision | Recall | F1 | Kappa")
    print("-" * 60)
    f1_values = []
    kappa_values = []
    for category in categories:
        golds = per_category[category]["gold"]
        preds = per_category[category]["pred"]
        scores = _f1_scores(golds, preds)
        kappa = _cohens_kappa(golds, preds)
        f1_values.append(scores["f1"])
        kappa_values.append(kappa)
        print(
            f"{category:<16} | {scores['precision']:.2f}     | {scores['recall']:.2f}  | {scores['f1']:.2f} | {kappa:.2f}"
        )
    macro_f1 = sum(f1_values) / len(f1_values) if f1_values else 0.0
    macro_kappa = sum(kappa_values) / len(kappa_values) if kappa_values else 0.0
    print("-" * 60)
    print(f"Macro averages     | {macro_f1:.2f} (F1) | {macro_kappa:.2f} (Kappa)")


if __name__ == "__main__":
    main()
