from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import ttest_ind
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.multitest import multipletests

from ..drift.scoring import compute_gene_drift
from ..networks.construction import construct_network
from .evaluation import _metrics, bootstrap_auc_ci, make_splits


EXPERIMENTS = {
    "deg_ranked_expression": "Fold-local DEG-ranked expression",
    "deg_plus_hubs": "Fold-local DEG + network-hub expression",
    "deg_plus_drift": "Fold-local DEG + cross-species drift expression",
    "integrated_biomarker_panel": "Fold-local DEG + hub/drift candidate panel",
}


def _rank_training_degs(
    features: pd.DataFrame,
    labels: pd.Series,
    train_indices: np.ndarray,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    train_features = features.iloc[train_indices].replace([np.inf, -np.inf], np.nan)
    train_labels = labels.iloc[train_indices]
    cancer = train_features.loc[train_labels == 1]
    healthy = train_features.loc[train_labels == 0]
    if len(cancer) < 2 or len(healthy) < 2:
        raise ValueError("Each training fold needs at least two samples per class for DEG ranking.")

    cancer_values = cancer.to_numpy(dtype=float)
    healthy_values = healthy.to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        test = ttest_ind(
            cancer_values,
            healthy_values,
            axis=0,
            equal_var=False,
            nan_policy="omit",
        )
    p_values = np.asarray(test.pvalue, dtype=float)
    p_values[~np.isfinite(p_values)] = 1.0
    adjusted = multipletests(p_values, method="fdr_bh")[1]
    effect = cancer.mean(axis=0) - healthy.mean(axis=0)
    ranked = pd.DataFrame({
        "gene_id": features.columns.astype(str),
        "log2_expression_difference": effect.to_numpy(dtype=float),
        "p_value": p_values,
        "adjusted_p_value": adjusted,
    }).sort_values(
        ["adjusted_p_value", "p_value", "gene_id"],
        ascending=[True, True, True],
    )
    ranked["significant"] = (
        (ranked["adjusted_p_value"] <= 0.05)
        & (ranked["log2_expression_difference"].abs() >= 1.0)
    )
    return ranked.reset_index(drop=True), {
        "method": "Welch t-test on normalized log2 expression; Benjamini-Hochberg within training fold",
        "genes_tested": int(len(ranked)),
        "significant_genes": int(ranked["significant"].sum()),
    }


def _load_drift_references(
    run_directory: Path,
) -> tuple[tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None, str | None]:
    networks = run_directory / "networks"
    orthology_path = run_directory / "orthology" / "orthologs.csv"
    required = (
        networks / "mouse_cancer_nodes.csv",
        networks / "mouse_cancer_edges.csv",
        orthology_path,
    )
    missing = [str(path.relative_to(run_directory)) for path in required if not path.is_file()]
    if missing:
        return None, (
            "Fold-local cross-species drift is unavailable; required saved mouse-network or "
            f"orthology artifacts are missing: {', '.join(missing)}."
        )
    mouse_nodes = pd.read_csv(required[0])
    mouse_edges = pd.read_csv(required[1])
    orthology = pd.read_csv(orthology_path)
    primary_mapping = orthology.loc[
        orthology["relationship_cardinality"].astype(str).eq("one_to_one")
        & pd.to_numeric(orthology["confidence"], errors="coerce").ge(1.0),
        ["human_ensembl_id", "mouse_ensembl_id"],
    ].drop_duplicates()
    if primary_mapping.empty:
        return None, (
            "Fold-local cross-species drift is unavailable because the saved orthology "
            "artifact contains no confident one-to-one human-mouse mappings."
        )
    if primary_mapping["human_ensembl_id"].duplicated().any() or primary_mapping["mouse_ensembl_id"].duplicated().any():
        raise ValueError("Saved primary orthology contains ambiguous one-to-one mappings.")
    return (mouse_nodes, mouse_edges, primary_mapping), None


def _network_support(
    features: pd.DataFrame,
    labels: pd.Series,
    train_indices: np.ndarray,
    fold: int,
    drift_references: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None,
    drift_reference_reason: str | None,
) -> tuple[set[str], dict[str, float], dict[str, Any]]:
    train_labels = labels.iloc[train_indices]
    cancer_indices = train_indices[train_labels.to_numpy() == 1]
    cancer_expression = features.iloc[cancer_indices].T
    if cancer_expression.shape[1] < 4:
        raise ValueError("Training cancer samples are insufficient to estimate a fold-local network.")
    human_network = construct_network(
        cancer_expression,
        species="human",
        method="spearman",
        min_abs_correlation=0.7,
        max_adjusted_p_value=0.05,
        min_gene_variance=0.1,
        max_genes=1000,
        seed=42 + fold,
    )
    human_nodes = human_network["nodes"]
    human_edges = human_network["edges"]
    if human_edges.empty:
        return set(), {}, {
            "status": "NOT_AVAILABLE",
            "reason": "No statistically supported human cancer-network edges were estimable in this training fold.",
            "training_cancer_samples": int(len(cancer_indices)),
            "network_nodes": int(len(human_nodes)),
            "network_edges": 0,
        }

    drift = pd.DataFrame()
    drift_status = "NOT_AVAILABLE"
    drift_reason = drift_reference_reason
    if drift_references is not None:
        mouse_nodes, mouse_edges, mapping = drift_references
        drift = compute_gene_drift(
            human_nodes,
            mouse_nodes,
            human_edges,
            mouse_edges,
            mapping,
        )
        drift_status = "AVAILABLE" if not drift.empty else "NOT_AVAILABLE"
        drift_reason = None if not drift.empty else (
            "No mapped genes were available for the fold-local cross-species drift comparison."
        )
    active_nodes = human_nodes.loc[
        pd.to_numeric(human_nodes["degree"], errors="coerce").fillna(0).gt(0)
    ].copy()
    active_nodes = active_nodes.sort_values(
        ["weighted_degree", "degree", "gene_id"],
        ascending=[False, False, True],
    )
    hubs = set(active_nodes["gene_id"].astype(str).head(50))
    if drift.empty:
        return hubs, {}, {
            "status": "AVAILABLE",
            "drift_status": "NOT_AVAILABLE",
            "drift_reason": (
                "No fold-local human-network genes overlapped the saved mouse network "
                "through confident one-to-one orthology."
            ),
            "training_cancer_samples": int(len(cancer_indices)),
            "network_nodes": int(len(human_nodes)),
            "network_edges": int(len(human_edges)),
            "mapped_drift_genes": 0,
            "hub_genes": int(len(hubs)),
        }
    drift = drift.sort_values(
        ["drift_score", "human_ensembl_id"], ascending=[False, True]
    )
    drift_weights = {
        str(row.human_ensembl_id): float(row.drift_score)
        for row in drift.head(100).itertuples(index=False)
        if pd.notna(row.drift_score) and np.isfinite(float(row.drift_score))
    }
    return hubs, drift_weights, {
        "status": "AVAILABLE",
        "training_cancer_samples": int(len(cancer_indices)),
        "network_nodes": int(len(human_nodes)),
        "network_edges": int(len(human_edges)),
        "mapped_drift_genes": int(len(drift_weights)),
        "hub_genes": int(len(hubs)),
        "drift_status": drift_status,
        "drift_reason": drift_reason,
        "mouse_reference": (
            "Saved mouse cancer network; used as a fixed external biological reference."
            if drift_references is not None else None
        ),
    }


def _fit_fold_model(
    features: pd.DataFrame,
    labels: pd.Series,
    train_indices: np.ndarray,
    test_indices: np.ndarray,
    gene_ids: list[str],
    weights: dict[str, float] | None = None,
    *,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    selected = [gene for gene in gene_ids if gene in features.columns]
    if not selected:
        raise ValueError("The training fold produced no usable biological features.")
    train_x = features.iloc[train_indices].loc[:, selected].copy()
    test_x = features.iloc[test_indices].loc[:, selected].copy()
    if weights is not None:
        multiplier = pd.Series(weights, dtype=float).reindex(selected).fillna(0.0)
        if not multiplier.gt(0).any():
            raise ValueError("No positive training-fold drift weights overlap the selected genes.")
        train_x = train_x.mul(multiplier, axis=1)
        test_x = test_x.mul(multiplier, axis=1)
    model = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(class_weight="balanced", max_iter=3000, random_state=seed),
    )
    model.fit(train_x, labels.iloc[train_indices])
    probability = model.predict_proba(test_x)[:, 1]
    coefficient = model[-1].coef_[0]
    return probability, coefficient


def evaluate_biological_experiments(
    run_directory: Path,
    features: pd.DataFrame,
    labels: pd.Series,
    groups: pd.Series | None,
    baseline_predictions: pd.DataFrame,
    *,
    seed: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    splits, fold_count, splitter_name = make_splits(labels, groups, seed=seed)
    drift_references, drift_reference_reason = _load_drift_references(run_directory)
    baseline = baseline_predictions.loc[
        baseline_predictions["model"].eq("logistic_regression")
    ].set_index("sample_id")["predicted_probability"].reindex(features.index)
    if baseline.isna().any():
        raise ValueError("Expression baseline predictions do not cover all samples.")
    baseline_metrics = _metrics(labels.to_numpy(), baseline.to_numpy(dtype=float))

    prediction_records: list[dict[str, Any]] = []
    importance_records: list[dict[str, Any]] = []
    fold_records: list[dict[str, Any]] = []
    fold_probabilities: dict[str, np.ndarray] = {
        key: np.full(len(labels), np.nan) for key in EXPERIMENTS
    }
    unavailable: dict[str, list[str]] = {key: [] for key in EXPERIMENTS}

    for fold, (train, test) in enumerate(splits, start=1):
        deg_rankings, deg_summary = _rank_training_degs(features, labels, train)
        deg_genes = deg_rankings["gene_id"].head(100).astype(str).tolist()
        hub_genes, drift_weights, network_summary = _network_support(
            features,
            labels,
            train,
            fold,
            drift_references,
            drift_reference_reason,
        )
        hub_genes &= set(features.columns.astype(str))
        drift_genes = set(drift_weights) & set(features.columns.astype(str))
        top_deg = deg_rankings["gene_id"].head(50).astype(str).tolist()
        candidates = set(
            deg_rankings.loc[deg_rankings["significant"], "gene_id"].astype(str)
        )
        integrated_genes = sorted(candidates & (hub_genes | drift_genes))
        panels = {
            "deg_ranked_expression": (deg_genes, None),
            "deg_plus_hubs": (list(dict.fromkeys(top_deg + sorted(hub_genes))), None),
            "deg_plus_drift": (
                list(dict.fromkeys(top_deg + sorted(drift_genes))),
                {
                    gene: 1.0 + drift_weights.get(gene, 0.0)
                    for gene in dict.fromkeys(top_deg + sorted(drift_genes))
                },
            ),
            "integrated_biomarker_panel": (integrated_genes, None),
        }
        supported = {
            "deg_ranked_expression": bool(deg_genes),
            "deg_plus_hubs": bool(hub_genes),
            "deg_plus_drift": bool(drift_genes)
            and network_summary.get("status") == "AVAILABLE"
            and network_summary.get("drift_status") == "AVAILABLE",
            "integrated_biomarker_panel": bool(integrated_genes),
        }
        for name, (gene_ids, feature_weights) in panels.items():
            fold_records.append({
                "fold": fold,
                "experiment": name,
                "selected_feature_count": len(gene_ids),
                "training_significant_degs": deg_summary["significant_genes"],
                "training_hub_genes": len(hub_genes),
                "training_drift_genes": len(drift_genes),
                "human_network_edges": network_summary.get("network_edges", 0),
                "network_status": network_summary.get("status"),
                "drift_status": network_summary.get("drift_status", "NOT_AVAILABLE"),
                "network_reason": network_summary.get(
                    "reason", network_summary.get("drift_reason")
                ),
                "status": "AVAILABLE" if supported[name] else "NOT_AVAILABLE",
            })
            if not supported[name]:
                unavailable[name].append(
                    f"Fold {fold} could not derive the required fold-local "
                    f"{name.replace('_', ' ')} evidence."
                )
                continue
            if not gene_ids:
                unavailable[name].append(f"Fold {fold} produced no eligible features.")
                continue
            try:
                probabilities, coefficients = _fit_fold_model(
                    features,
                    labels,
                    train,
                    test,
                    gene_ids,
                    feature_weights,
                    seed=seed + fold,
                )
            except ValueError as error:
                unavailable[name].append(f"Fold {fold}: {error}")
                continue
            fold_probabilities[name][test] = probabilities
            for sample_index, probability in zip(test, probabilities):
                prediction_records.append({
                    "sample_id": str(features.index[sample_index]),
                    "fold": fold,
                    "experiment": name,
                    "true_label": int(labels.iloc[sample_index]),
                    "predicted_probability": float(probability),
                    "predicted_label": int(probability >= 0.5),
                })
            for gene_id, coefficient in zip(gene_ids, coefficients):
                selected_for_drift = (
                    name in {"deg_plus_drift", "integrated_biomarker_panel"}
                    and gene_id in drift_genes
                )
                importance_records.append({
                    "experiment": name,
                    "fold": fold,
                    "gene_id": gene_id,
                    "coefficient": float(coefficient),
                    "selected_as_deg": gene_id in set(top_deg) or gene_id in candidates,
                    "selected_as_hub": gene_id in hub_genes,
                    "cross_species_drift_score": (
                        drift_weights.get(gene_id) if selected_for_drift else None
                    ),
                    "fold_local": True,
                })

    experiment_summaries: dict[str, Any] = {}
    importance_frame = pd.DataFrame(importance_records)
    for name, label in EXPERIMENTS.items():
        probabilities = fold_probabilities[name]
        candidate_features: list[dict[str, Any]] = []
        experiment_importance = (
            importance_frame.loc[importance_frame["experiment"].eq(name)]
            if not importance_frame.empty
            else pd.DataFrame()
        )
        if not experiment_importance.empty:
            grouped_importance = experiment_importance.groupby("gene_id", as_index=False).agg(
                folds_selected=("fold", "nunique"),
                mean_absolute_coefficient=("coefficient", lambda values: float(values.abs().mean())),
                selected_as_deg=("selected_as_deg", "max"),
                selected_as_hub=("selected_as_hub", "max"),
                selected_as_drift=("cross_species_drift_score", lambda values: values.notna().any()),
                mean_drift_score=("cross_species_drift_score", "mean"),
            )
            grouped_importance["selection_frequency"] = (
                grouped_importance["folds_selected"] / fold_count
            )
            grouped_importance["biological_evidence_priority"] = (
                grouped_importance["selected_as_hub"]
                | grouped_importance["selected_as_drift"]
            )
            grouped_importance = grouped_importance.sort_values(
                [
                    "biological_evidence_priority",
                    "selection_frequency",
                    "mean_absolute_coefficient",
                    "gene_id",
                ],
                ascending=[False, False, False, True],
            )
            candidate_features = [
                {
                    "gene_id": str(row.gene_id),
                    "folds_selected": int(row.folds_selected),
                    "selection_frequency": float(row.selection_frequency),
                    "mean_absolute_coefficient": float(row.mean_absolute_coefficient),
                    "selected_as_deg": bool(row.selected_as_deg),
                    "selected_as_hub": bool(row.selected_as_hub),
                    "selected_as_drift": bool(row.selected_as_drift),
                    "mean_drift_score": (
                        float(row.mean_drift_score)
                        if pd.notna(row.mean_drift_score)
                        else None
                    ),
                }
                for row in grouped_importance.head(25).itertuples(index=False)
            ]
        if unavailable[name] or np.isnan(probabilities).any():
            experiment_summaries[name] = {
                "label": label,
                "status": "NOT_AVAILABLE",
                "reason": "; ".join(unavailable[name]) or (
                    "At least one validation fold did not produce a prediction."
                ),
                "metrics": None,
                "delta_from_expression_baseline": None,
                "folds_completed": int(np.isfinite(probabilities).sum()),
                "folds_total": fold_count,
                "candidate_features": candidate_features,
            }
            continue
        metrics = _metrics(labels.to_numpy(), probabilities)
        auc_interval = bootstrap_auc_ci(
            labels.to_numpy(),
            probabilities,
            seed=seed,
            groups=groups.to_numpy() if groups is not None else None,
        )
        experiment_summaries[name] = {
            "label": label,
            "status": "EVALUATED",
            "metrics": metrics,
            "roc_auc_95_percentile_interval": auc_interval,
            "delta_from_expression_baseline": {
                key: float(metrics[key] - baseline_metrics[key])
                for key in ("roc_auc", "pr_auc", "f1")
            },
            "folds_completed": fold_count,
            "folds_total": fold_count,
            "candidate_features": candidate_features,
        }

    summary = {
        "status": "COMPLETED",
        "scientific_scope": (
            "Exploratory patient-grouped cross-validation. DEG ranking, human networks, "
            "hub selection, and human-mouse drift are re-estimated within each training fold. "
            "The mouse cancer network is a fixed external biological reference."
        ),
        "split": {
            "name": splitter_name,
            "folds": fold_count,
            "grouped_by_patient": groups is not None,
        },
        "baseline": {
            "model": "logistic_regression",
            "metrics": baseline_metrics,
            "roc_auc_95_percentile_interval": bootstrap_auc_ci(
                labels.to_numpy(),
                baseline.to_numpy(dtype=float),
                seed=seed,
                groups=groups.to_numpy() if groups is not None else None,
            ),
        },
        "experiments": experiment_summaries,
        "fold_evidence": fold_records,
        "limitations": [
            "DEG rankings use Welch tests on normalized log2 expression inside training folds; they are not PyDESeq2 count-model results.",
            "The 20-sample cohort yields unstable training-fold network estimates; a fold without supported human network edges cannot support hub or cross-species drift features.",
            "Human fold networks are compared with a fixed mouse cancer network from a separate study; network-density differences may dominate drift scores, so these are not sample-level drift measurements or independent validation.",
            "Full-cohort Phase 5 biomarker candidates and hub/drift annotations are reported separately and are not used for cross-validation feature selection.",
            "No result constitutes clinical validation.",
        ],
    }
    return (
        summary,
        pd.DataFrame(prediction_records),
        pd.DataFrame(importance_records),
    )
