from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def score_geo_dataset(dataset: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Transparent scoring heuristic for GEO candidate datasets."""
    score = 0
    reasons: List[str] = []

    checks = [
        ("species", dataset.get("species") == "Mouse" or dataset.get("species") == "mouse", "Mouse"),
        ("tissue", "mammary" in (dataset.get("tissue") or "").lower() or "breast" in (dataset.get("tissue") or "").lower(), "Mammary tissue"),
        ("disease", dataset.get("condition") in {"Cancer", "Tumor", "Breast cancer", "Disease"}, "Cancer / disease state"),
        ("rna_seq", dataset.get("data_type") in {"RNA-seq", "rna_seq", "RNAseq"}, "RNA-seq"),
        ("controls", dataset.get("normal_controls") is True, "Normal controls"),
        ("replicates", dataset.get("biological_replicates") is True, "Biological replicates"),
        ("metadata", dataset.get("metadata_available") is True, "Metadata available"),
        ("expression", dataset.get("expression_available") is True, "Expression matrix available"),
        ("study_quality", dataset.get("study_quality") in {"high", "good"}, "Study quality"),
    ]

    for field, condition, label in checks:
        if condition:
            score += 10
            reasons.append(f"✓ {label}")
        else:
            reasons.append(f"✗ {label}")

    score = max(0, min(100, score))
    return score, reasons


def score_dataset_list(datasets: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scored: List[Dict[str, Any]] = []
    for dataset in datasets:
        score, reasons = score_geo_dataset(dataset)
        dataset = dict(dataset)
        dataset["suitability_score"] = score
        dataset["suitability_reasons"] = reasons
        scored.append(dataset)
    return sorted(scored, key=lambda item: item["suitability_score"], reverse=True)
