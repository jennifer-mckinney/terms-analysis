import json
from pathlib import Path

from app.services.rules import PATTERNS, detect_findings


def load_dataset(path: Path):
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Dataset must be a list of examples.")
    return data


def compute_metrics(dataset):
    categories = sorted({pattern.category for pattern in PATTERNS})
    totals = {category: {"tp": 0, "fp": 0, "fn": 0} for category in categories}

    for item in dataset:
        text = item["text"]
        jurisdictions = item.get("jurisdictions", ["US-CA", "GDPR"])
        gold = set(item.get("labels", []))
        predicted = {finding.category for finding in detect_findings(text, jurisdictions)}
        for category in categories:
            if category in gold and category in predicted:
                totals[category]["tp"] += 1
            elif category not in gold and category in predicted:
                totals[category]["fp"] += 1
            elif category in gold and category not in predicted:
                totals[category]["fn"] += 1

    f1_scores = {}
    for category, stats in totals.items():
        tp = stats["tp"]
        fp = stats["fp"]
        fn = stats["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if precision + recall else 0.0
        f1_scores[category] = f1

    macro_f1 = sum(f1_scores.values()) / len(f1_scores) if f1_scores else 0.0
    return categories, f1_scores, macro_f1


def compute_kappa(dataset, categories):
    if not dataset:
        return 0.0
    pairs = []
    for item in dataset:
        text = item["text"]
        jurisdictions = item.get("jurisdictions", ["US-CA", "GDPR"])
        gold = set(item.get("labels", []))
        predicted = {finding.category for finding in detect_findings(text, jurisdictions)}
        for category in categories:
            pairs.append((category in gold, category in predicted))

    total = len(pairs)
    observed = sum(1 for gold, pred in pairs if gold == pred) / total if total else 0.0
    gold_yes = sum(1 for gold, _ in pairs if gold) / total if total else 0.0
    pred_yes = sum(1 for _, pred in pairs if pred) / total if total else 0.0
    expected = gold_yes * pred_yes + (1 - gold_yes) * (1 - pred_yes)
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)


def main():
    dataset_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "gold_dataset.json"
    dataset = load_dataset(dataset_path)
    categories, f1_scores, macro_f1 = compute_metrics(dataset)
    kappa = compute_kappa(dataset, categories)

    print("Macro F1:", round(macro_f1, 3))
    print("Cohen's kappa:", round(kappa, 3))
    for category in categories:
        print(f"{category}: {round(f1_scores[category], 3)}")


if __name__ == "__main__":
    main()
