from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.feature_selection import VarianceThreshold


class FoldTopK(SelectKBest):
    def __init__(self, k: int = 100):
        super().__init__(score_func=f_classif, k=k)

    def fit(self, X, y=None):
        self.k = min(int(self.k), X.shape[1])
        return super().fit(X, y)


def build_pipeline(model_name: str, seed: int) -> Pipeline:
    estimators = {
        "logistic_regression": LogisticRegression(
            class_weight="balanced", max_iter=3000, random_state=seed
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=300, class_weight="balanced", min_samples_leaf=2,
            max_features="sqrt", random_state=seed, n_jobs=1,
        ),
        "svm": SVC(C=1.0, kernel="linear", class_weight="balanced", probability=True, random_state=seed),
        "gradient_boosting": GradientBoostingClassifier(
            n_estimators=100, learning_rate=0.05, max_depth=2, random_state=seed
        ),
    }
    if model_name not in estimators:
        raise ValueError(f"Unknown model: {model_name}")
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("variance", VarianceThreshold(threshold=0.0)),
        ("select", FoldTopK(k=100)),
        ("scale", StandardScaler()),
        ("model", estimators[model_name]),
    ])


def make_splits(
    labels: pd.Series,
    groups: pd.Series | None,
    *,
    seed: int,
    max_folds: int = 5,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], int, str]:
    counts = labels.value_counts()
    if len(counts) != 2 or int(counts.min()) < 3:
        raise ValueError("At least three samples from each class are required for cross-validation.")
    folds = min(max_folds, int(counts.min()))
    if groups is not None:
        splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
        splits = list(splitter.split(np.zeros(len(labels)), labels.to_numpy(), groups.to_numpy()))
        for train, test in splits:
            if set(groups.iloc[train]) & set(groups.iloc[test]):
                raise ValueError("Grouped cross-validation split patient groups across folds.")
            if len(np.unique(labels.iloc[test])) != 2:
                raise ValueError("Patient-grouped folds cannot preserve both classes.")
        return splits, folds, "StratifiedGroupKFold"
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    return list(splitter.split(np.zeros(len(labels)), labels.to_numpy())), folds, "StratifiedKFold"


def _metrics(y_true: np.ndarray, probabilities: np.ndarray, threshold: float = 0.5) -> dict[str, Any]:
    predicted = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()
    return {
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "pr_auc": float(average_precision_score(y_true, probabilities)),
        "accuracy": float(accuracy_score(y_true, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predicted)),
        "sensitivity": float(recall_score(y_true, predicted, zero_division=0)),
        "specificity": float(tn / (tn + fp)) if tn + fp else None,
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "brier_score": float(brier_score_loss(y_true, probabilities)),
        "threshold": threshold,
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def bootstrap_auc_ci(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    *,
    seed: int,
    iterations: int = 1000,
    groups: np.ndarray | None = None,
) -> list[float] | None:
    rng = np.random.default_rng(seed)
    class_indices = [np.flatnonzero(y_true == value) for value in (0, 1)]
    if any(len(indices) < 2 for indices in class_indices):
        return None
    group_indices = None
    if groups is not None:
        group_indices = [
            np.flatnonzero(groups == group)
            for group in pd.unique(groups)
        ]
    values = []
    for _ in range(iterations):
        if group_indices is not None:
            selected_groups = rng.integers(0, len(group_indices), size=len(group_indices))
            sampled = np.concatenate([group_indices[index] for index in selected_groups])
        else:
            sampled = np.concatenate([
                rng.choice(indices, size=len(indices), replace=True) for indices in class_indices
            ])
        if len(np.unique(y_true[sampled])) != 2:
            continue
        values.append(roc_auc_score(y_true[sampled], probabilities[sampled]))
    if not values:
        return None
    return [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]


def evaluate_models(
    features: pd.DataFrame,
    labels: pd.Series,
    groups: pd.Series | None,
    *,
    seed: int,
) -> tuple[
    dict[str, dict[str, Any]],
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Pipeline],
    dict[str, Any],
]:
    splits, folds, splitter_name = make_splits(labels, groups, seed=seed)
    names = ("logistic_regression", "random_forest", "svm", "gradient_boosting")
    summaries: dict[str, dict[str, Any]] = {}
    all_predictions: list[dict[str, Any]] = []
    all_importances: list[dict[str, Any]] = []
    fitted_models: dict[str, Pipeline] = {}

    for model_name in names:
        oof = np.full(len(labels), np.nan)
        fold_scores = []
        for fold, (train, test) in enumerate(splits, start=1):
            model = build_pipeline(model_name, seed + fold)
            model.fit(features.iloc[train], labels.iloc[train])
            probability = model.predict_proba(features.iloc[test])[:, 1]
            oof[test] = probability
            fold_scores.append(_metrics(labels.iloc[test].to_numpy(), probability))
            selected_support = model.named_steps["select"].get_support()
            variance_support = model.named_steps["variance"].get_support()
            selected_names = features.columns[variance_support][selected_support]
            estimator = model.named_steps["model"]
            if hasattr(estimator, "feature_importances_"):
                values = estimator.feature_importances_
                signed = np.full(len(values), np.nan)
                importance_method = "fold-local tree impurity importance"
            elif hasattr(estimator, "coef_"):
                signed = estimator.coef_[0]
                values = np.abs(signed)
                importance_method = "fold-local absolute standardized coefficient"
            else:
                values = np.zeros(len(selected_names), dtype=float)
                signed = np.full(len(selected_names), np.nan)
                importance_method = "fold-local importance unavailable"
            for gene_id, value, direction in zip(selected_names, values, signed):
                all_importances.append({
                    "model": model_name,
                    "fold": fold,
                    "gene_id": str(gene_id),
                    "importance": float(value),
                    "signed_weight": float(direction) if np.isfinite(direction) else None,
                    "method": importance_method,
                })
            for index, score in zip(test, probability):
                all_predictions.append({
                    "sample_id": str(features.index[index]),
                    "model": model_name,
                    "fold": fold,
                    "true_label": int(labels.iloc[index]),
                    "predicted_probability": float(score),
                    "predicted_label": int(score >= 0.5),
                })

        if np.isnan(oof).any():
            raise RuntimeError(f"Cross-validation did not produce predictions for every sample ({model_name}).")
        fitted = build_pipeline(model_name, seed)
        fitted.fit(features, labels)
        fitted_models[model_name] = fitted
        selected_fold_importances = pd.DataFrame(
            [row for row in all_importances if row["model"] == model_name]
        )
        if not selected_fold_importances.empty:
            fold_importance_summary = (
                selected_fold_importances.groupby("gene_id", as_index=False)
                .agg(
                    mean_absolute_importance=("importance", "sum"),
                    selected_folds=("fold", "nunique"),
                    mean_signed_weight=("signed_weight", "mean"),
                    importance_method=("method", "first"),
                )
            )
            fold_importance_summary["importance"] = (
                fold_importance_summary["mean_absolute_importance"] / len(splits)
            )
            fold_importance_summary["selection_frequency"] = (
                fold_importance_summary["selected_folds"] / len(splits)
            )
            fold_importance_summary["direction"] = fold_importance_summary[
                "mean_signed_weight"
            ].map(
                lambda value: (
                    "higher in cancer" if pd.notna(value) and value > 0
                    else "higher in healthy" if pd.notna(value) and value < 0
                    else "not applicable"
                )
            )
            for row in fold_importance_summary.to_dict("records"):
                row["model"] = model_name
                row["importance_method"] = str(row["importance_method"])
                row["mean_signed_weight"] = (
                    float(row["mean_signed_weight"])
                    if pd.notna(row["mean_signed_weight"])
                    else None
                )
                row["importance"] = float(row["importance"])
                row["selection_frequency"] = float(row["selection_frequency"])
                row["selected_folds"] = int(row["selected_folds"])
                all_importances.append(row)
        summaries[model_name] = {
            "out_of_fold_metrics": _metrics(labels.to_numpy(), oof),
            "auc_95_percentile_interval": bootstrap_auc_ci(
                labels.to_numpy(),
                oof,
                seed=seed,
                groups=groups.to_numpy() if groups is not None else None,
            ),
            "auc_interval_resampling_unit": "patient_group" if groups is not None else "sample",
            "fold_metrics": fold_scores,
            "calibration_curve": _calibration(labels.to_numpy(), oof),
            "n_samples": int(len(labels)),
            "n_features_before_fold_selection": int(features.shape[1]),
            "n_features_selected_per_fold": 100,
            "feature_selection": "ANOVA F-score fitted independently inside every training fold",
        }
    feature_importance = pd.DataFrame(
        [row for row in all_importances if "selection_frequency" in row],
        columns=[
            "model", "gene_id", "importance", "mean_signed_weight", "direction",
            "selected_folds", "selection_frequency", "importance_method",
        ],
    )
    return summaries, pd.DataFrame(all_predictions), feature_importance, fitted_models, {
        "name": splitter_name,
        "folds": folds,
        "grouped_by_patient": groups is not None,
        "feature_importance_method": "Aggregated from fold-local fitted models; full-cohort model is not used for rankings.",
    }


def _calibration(labels: np.ndarray, probabilities: np.ndarray) -> list[dict[str, float]]:
    fraction_positive, mean_predicted = calibration_curve(
        labels, probabilities, n_bins=min(5, max(2, len(labels) // 3)), strategy="quantile"
    )
    return [
        {"mean_predicted_probability": float(pred), "fraction_positive": float(obs)}
        for obs, pred in zip(fraction_positive, mean_predicted)
    ]
