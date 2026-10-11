from __future__ import annotations

import math

import pandas as pd

from .validation import ValidatedExpression, validate_raw_counts


def filter_raw_counts(
    validated: ValidatedExpression,
    *,
    min_count: int,
    min_samples_fraction: float,
) -> tuple[pd.DataFrame, dict[str, int | float]]:
    if min_count < 0 or not 0 < min_samples_fraction <= 1:
        raise ValueError("Count filtering requires min_count >= 0 and 0 < min_samples_fraction <= 1.")
    samples = validated.control_samples + validated.case_samples
    counts = validate_raw_counts(validated.expression.loc[:, samples])
    required_samples = max(1, math.ceil(len(samples) * min_samples_fraction))
    keep = (counts >= min_count).sum(axis=1) >= required_samples
    filtered = counts.loc[keep]
    if filtered.empty:
        raise ValueError("No genes passed the configured raw-count filter.")
    return filtered, {
        "genes_before": int(counts.shape[0]),
        "genes_after": int(filtered.shape[0]),
        "min_count": int(min_count),
        "min_samples_fraction": float(min_samples_fraction),
        "required_samples": int(required_samples),
    }
