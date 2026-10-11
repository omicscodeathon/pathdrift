from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_curve

from ..acquisition.registry import ROOT, json_safe
from .biological import evaluate_biological_experiments
from .dataset import LabeledExpression, load_labeled_expression, summarize_labeled_cohorts
from .evaluation import evaluate_models

logger = logging.getLogger("pathdrift.phase6")
MODEL_NAMES = ("logistic_regression", "random_forest", "svm", "gradient_boosting")


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(json_safe(content), indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _plot_svg(
    path: Path,
    title: str,
    x_label: str,
    y_label: str,
    curves: dict[str, list[tuple[float, float]]],
) -> None:
    width, height, margin = 720, 480, 60
    palette = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728")
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">{escape(title)}</text>',
        f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="#333"/>',
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="#333"/>',
        f'<text x="{width/2}" y="{height-12}" text-anchor="middle" font-family="sans-serif" font-size="13">{escape(x_label)}</text>',
        f'<text x="16" y="{height/2}" transform="rotate(-90 16 {height/2})" text-anchor="middle" font-family="sans-serif" font-size="13">{escape(y_label)}</text>',
    ]
    for index, (name, points) in enumerate(curves.items()):
        color = palette[index % len(palette)]
        coords = " ".join(
            f"{margin + x * (width - 2 * margin):.2f},{height - margin - y * (height - 2 * margin):.2f}"
            for x, y in points
        )
        elements.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
        elements.append(
            f'<text x="{width-margin-145}" y="{margin+index*20}" font-family="sans-serif" font-size="12" fill="{color}">{escape(name)}</text>'
        )
    elements.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elements), encoding="utf-8")


def _write_curves(
    output_directory: Path,
    predictions: pd.DataFrame,
    metrics: dict[str, dict[str, Any]],
) -> list[str]:
    roc_curves: dict[str, list[tuple[float, float]]] = {}
    pr_curves: dict[str, list[tuple[float, float]]] = {}
    calibration_curves: dict[str, list[tuple[float, float]]] = {}
    for model_name in MODEL_NAMES:
        model_rows = predictions[predictions["model"] == model_name]
        y = model_rows["true_label"].to_numpy()
        p = model_rows["predicted_probability"].to_numpy()
        fpr, tpr, _ = roc_curve(y, p)
        precision, recall, _ = precision_recall_curve(y, p)
        roc_curves[model_name] = list(zip(fpr.tolist(), tpr.tolist()))
        pr_curves[model_name] = list(zip(recall.tolist(), precision.tolist()))
        calibration_curves[model_name] = [
            (item["mean_predicted_probability"], item["fraction_positive"])
            for item in metrics[model_name]["calibration_curve"]
        ]
    outputs = ("roc_curves.svg", "precision_recall_curves.svg", "calibration_curves.svg")
    _plot_svg(
        output_directory / outputs[0], "Out-of-fold ROC curves",
        "False positive rate", "True positive rate", roc_curves,
    )
    _plot_svg(
        output_directory / outputs[1], "Out-of-fold precision-recall curves",
        "Recall", "Precision", pr_curves,
    )
    _plot_svg(
        output_directory / outputs[2], "Out-of-fold calibration curves",
        "Mean predicted probability", "Observed positive fraction", calibration_curves,
    )
    return list(outputs)


def _save_feature_importances(
    output_directory: Path,
    importance: pd.DataFrame,
) -> None:
    importance.sort_values(
        ["model", "importance"], ascending=[True, False]
    ).to_csv(output_directory / "feature_importance.csv", index=False)


def _read_annotations(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=columns)
    header = pd.read_csv(path, nrows=0).columns.tolist()
    available = [column for column in columns if column in header]
    if not available:
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(path, usecols=available)
    for column in columns:
        if column not in frame:
            frame[column] = pd.NA
    return frame[columns]


def _coalesce_columns(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    available = [column for column in columns if column in frame]
    if not available:
        return pd.Series(pd.NA, index=frame.index, dtype=object)
    result = frame[available[0]].copy()
    for column in available[1:]:
        result = result.where(result.notna(), frame[column])
    return result


def _saved_feature_groups(run_directory: Path, species: str) -> dict[str, dict[str, Any]]:
    definitions = {
        "differential_expression": (
            [f"deg/{species}/all_genes.csv"],
            "Saved cohort-level differential-expression results are available as gene annotations; they are not per-sample predictors.",
        ),
        "network_features": (
            [f"networks/{species}_cancer_nodes.csv", f"networks/{species}_healthy_nodes.csv"],
            "Saved network topology is available as cohort-level gene annotation; it is not a per-sample predictor.",
        ),
        "module_features": (
            [f"modules/{species}/module_genes.csv", f"modules/{species}/modules.csv"],
            "Saved module assignments are available as cohort-level gene annotation; they are not per-sample predictors.",
        ),
        "orthology_features": (
            ["orthology/orthologs.csv"],
            "Saved orthology mappings are available as gene-level cross-species annotations; they are not per-sample predictors.",
        ),
        "network_drift_features": (
            ["drift/gene_drift.csv"],
            "Saved network drift is available as a cohort-level comparison; it is not a per-sample predictor.",
        ),
        "pathway_features": (
            ["pathways/enrichment_results.csv", "pathways/key_drifted_pathways.csv"],
            "Saved pathway enrichment and drift comparisons are available as cohort-level annotations; they are not per-sample predictors.",
        ),
        "morphology_features": (
            ["morphology/phenotype_variables.csv", "morphology/morphology_summary.json"],
            "Saved clinical pathology metadata is descriptive. No image-derived, sample-linked morphology features or gene-level morphology association were calculated.",
        ),
    }
    groups: dict[str, dict[str, Any]] = {}
    for name, (sources, available_reason) in definitions.items():
        available_sources = [
            source for source in sources if (run_directory / source).is_file()
        ]
        if name == "morphology_features" and available_sources:
            status = "DESCRIPTIVE_METADATA_AVAILABLE"
        else:
            status = "ANNOTATION_AVAILABLE" if available_sources else "UNAVAILABLE"
        groups[name] = {
            "status": status,
            "reason": (
                available_reason
                if available_sources
                else "No saved result artifact for this evidence group exists in this analysis run."
            ),
            "sources": available_sources,
            "source": available_sources[0] if available_sources else None,
            "sample_level": False,
        }
    return groups


def _pathway_annotations(
    run_directory: Path,
    species: str,
    gene_ids: set[str],
) -> pd.DataFrame:
    enrichment_path = run_directory / "pathways" / "enrichment_results.csv"
    if not enrichment_path.is_file() or not gene_ids:
        return pd.DataFrame(columns=[
            "gene_id", "pathway_annotation_names", "key_drifted_annotation_names"
        ])

    key_path = run_directory / "pathways" / "key_drifted_pathways.csv"
    key_pathways: set[tuple[str, str, str]] = set()
    key_columns = [
        f"{species}_gene_set_key", "database", "pathway_id", "key_drifted_pathway"
    ]
    if key_path.is_file():
        key_header = pd.read_csv(key_path, nrows=0).columns.tolist()
        if all(column in key_header for column in key_columns):
            key_rows = pd.read_csv(key_path, usecols=key_columns, dtype=str)
            is_key = key_rows["key_drifted_pathway"].str.lower().isin({"true", "1"})
            key_pathways = {
                (str(row[0]), str(row[1]), str(row[2]))
                for row in key_rows.loc[is_key, [
                    f"{species}_gene_set_key", "database", "pathway_id"
                ]].itertuples(index=False, name=None)
            }

    columns = [
        "species", "gene_set_key", "database", "pathway_id", "pathway_name",
        "adjusted_p_value", "overlapping_gene_ids",
    ]
    header = pd.read_csv(enrichment_path, nrows=0).columns.tolist()
    if not set(columns).issubset(header):
        return pd.DataFrame(columns=[
            "gene_id", "pathway_annotation_names", "key_drifted_annotation_names"
        ])

    annotations: dict[str, dict[tuple[str, str], tuple[float, str, bool]]] = {}
    for chunk in pd.read_csv(enrichment_path, usecols=columns, chunksize=2000):
        chunk = chunk.loc[chunk["species"].astype(str).str.lower() == species.lower()].copy()
        chunk["adjusted_p_value"] = pd.to_numeric(
            chunk["adjusted_p_value"], errors="coerce"
        )
        chunk = chunk.loc[chunk["adjusted_p_value"].le(0.05)]
        for row in chunk.itertuples(index=False):
            gene_set_key = str(row.gene_set_key)
            database = str(row.database)
            pathway_id = str(row.pathway_id)
            pathway_name = str(row.pathway_name)
            fdr = float(row.adjusted_p_value)
            is_key_drifted = (gene_set_key, database, pathway_id) in key_pathways
            for gene_id in str(row.overlapping_gene_ids or "").split("|"):
                if gene_id not in gene_ids:
                    continue
                pathway_key = (database, pathway_id)
                gene_annotations = annotations.setdefault(gene_id, {})
                previous = gene_annotations.get(pathway_key)
                if previous is None or fdr < previous[0]:
                    gene_annotations[pathway_key] = (
                        fdr, pathway_name, is_key_drifted
                    )
                elif is_key_drifted:
                    gene_annotations[pathway_key] = (
                        previous[0], previous[1], True
                    )

    rows = []
    for gene_id, pathways in annotations.items():
        ranked = sorted(pathways.values(), key=lambda item: (item[0], item[1]))
        names = list(dict.fromkeys(name for _, name, _ in ranked))
        key_names = list(dict.fromkeys(
            name for _, name, is_key in ranked if is_key
        ))
        rows.append({
            "gene_id": gene_id,
            "pathway_annotation_names": "; ".join(names[:5]),
            "key_drifted_annotation_names": "; ".join(key_names[:5]),
        })
    return pd.DataFrame(rows, columns=[
        "gene_id", "pathway_annotation_names", "key_drifted_annotation_names"
    ])


def _reference_gene_symbols(species: str, gene_ids: set[str]) -> dict[str, str]:
    reference_root = ROOT / "data" / "pathdrift" / "reference" / "pathways"
    candidates = sorted(
        reference_root.glob(f"*/ensembl_{species}_gene_ids.tsv"),
        reverse=True,
    )
    for path in candidates:
        mapping = pd.read_csv(
            path,
            sep="\t",
            usecols=["Gene stable ID", "Gene name"],
            dtype=str,
        ).dropna(subset=["Gene stable ID", "Gene name"])
        mapping = mapping.loc[
            mapping["Gene stable ID"].isin(gene_ids)
            & mapping["Gene name"].ne("")
        ].drop_duplicates("Gene stable ID", keep="first")
        if not mapping.empty:
            return dict(zip(mapping["Gene stable ID"], mapping["Gene name"]))
    return {}


def _biological_annotations(
    run_directory: Path,
    species: str,
    importance: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if importance.empty:
        return pd.DataFrame(), pd.DataFrame()

    candidates = importance.copy()
    candidates["model_rank"] = candidates.groupby("model")["importance"].rank(
        method="min", ascending=False
    ).astype(int)
    candidates["feature_type"] = "normalized expression"
    candidates["biological_interpretation"] = (
        "Selected within training folds as predictive expression. Association is not causal or a clinically validated biomarker."
    )
    candidate_path = run_directory / "biomarkers" / "candidate_biomarkers.csv"
    candidate_columns = [
        "gene_id", "gene_symbol", "log2fc", "adjusted_p_value", "significant",
        "network_degree", "network_weighted_degree", "network_betweenness",
        "network_eigenvector", "network_module_id", "hub_supported",
        "one_to_one_mouse_ortholog_id", "mouse_ortholog_symbol",
        "cross_species_network_drift", "cross_species_drift_category",
        "mapped_edge_loss_rate", "orthology_confidence", "orthology_type",
        "one_to_one_orthology", "enriched_pathway_names",
        "key_drifted_pathway_names", "pathway_evidence_status",
        "morphology_association_status", "morphology_evidence",
    ]
    biological = _read_annotations(candidate_path, candidate_columns)
    if not biological.empty:
        biological = biological.drop_duplicates(subset=["gene_id"], keep="first")
        candidates = candidates.merge(
            biological,
            left_on="gene_id",
            right_on="gene_id",
            how="left",
            validate="many_to_one",
        )

    deg = _read_annotations(
        run_directory / "deg" / species / "all_genes.csv",
        ["gene_id", "log2fc", "adjusted_p_value", "significant", "direction"],
    ).drop_duplicates(subset=["gene_id"], keep="first")
    if not deg.empty:
        deg = deg.rename(columns={
            "log2fc": "deg_log2fc",
            "adjusted_p_value": "deg_adjusted_p_value",
            "significant": "deg_significant",
            "direction": "deg_direction",
        })
        candidates = candidates.merge(deg, on="gene_id", how="left", validate="many_to_one")

    nodes = _read_annotations(
        run_directory / "networks" / f"{species}_cancer_nodes.csv",
        [
            "gene_id", "gene_symbol", "degree", "weighted_degree",
            "betweenness_centrality", "closeness_centrality",
            "eigenvector_centrality", "module_id",
        ],
    ).drop_duplicates(subset=["gene_id"], keep="first")
    if not nodes.empty:
        nodes = nodes.rename(columns={
            "gene_symbol": "network_gene_symbol",
            "degree": "network_degree_from_nodes",
            "weighted_degree": "network_weighted_degree_from_nodes",
            "betweenness_centrality": "network_betweenness_from_nodes",
            "closeness_centrality": "network_closeness_from_nodes",
            "eigenvector_centrality": "network_eigenvector_from_nodes",
            "module_id": "network_module_from_nodes",
        })
        candidates = candidates.merge(nodes, on="gene_id", how="left", validate="many_to_one")
    else:
        candidates["network_gene_symbol"] = pd.NA
    node_fallbacks = {
        "network_degree": "network_degree_from_nodes",
        "network_weighted_degree": "network_weighted_degree_from_nodes",
        "network_betweenness": "network_betweenness_from_nodes",
        "network_closeness": "network_closeness_from_nodes",
        "network_eigenvector": "network_eigenvector_from_nodes",
        "network_module_id": "network_module_from_nodes",
    }
    for target, fallback in node_fallbacks.items():
        if fallback in candidates:
            if target in candidates:
                candidates[target] = candidates[target].fillna(candidates[fallback])
            else:
                candidates[target] = candidates[fallback]

    if species == "human":
        drift = _read_annotations(
            run_directory / "drift" / "gene_drift.csv",
            [
                "human_ensembl_id", "mouse_ensembl_id", "human_symbol", "mouse_symbol",
                "drift_score", "drift_category", "neighbor_similarity",
                "edge_loss_rate", "lost_neighbor_count", "gained_neighbor_count",
                "conserved_neighbor_count",
            ],
        ).drop_duplicates(subset=["human_ensembl_id"], keep="first")
        if not drift.empty:
            candidates = candidates.merge(
                drift,
                left_on="gene_id",
                right_on="human_ensembl_id",
                how="left",
                validate="many_to_one",
            )
        orthology = _read_annotations(
            run_directory / "orthology" / "orthologs.csv",
            [
                "human_ensembl_id", "mouse_ensembl_id", "human_symbol",
                "mouse_symbol", "orthology_type", "confidence",
                "relationship_cardinality",
            ],
        )
        if not orthology.empty:
            orthology = orthology.sort_values(
                "relationship_cardinality", ascending=True, na_position="last"
            ).drop_duplicates(subset=["human_ensembl_id"], keep="first")
            candidates = candidates.merge(
                orthology,
                left_on="gene_id",
                right_on="human_ensembl_id",
                how="left",
                suffixes=("", "_orthology"),
                validate="many_to_one",
            )
        candidates["mouse_ensembl_id"] = _coalesce_columns(
            candidates,
            [
                "mouse_ensembl_id", "mouse_ensembl_id_x", "mouse_ensembl_id_y",
                "mouse_ensembl_id_orthology", "one_to_one_mouse_ortholog_id",
            ],
        )
        candidates["mouse_symbol"] = _coalesce_columns(
            candidates,
            [
                "mouse_symbol", "mouse_symbol_x", "mouse_symbol_y",
                "mouse_symbol_orthology", "mouse_ortholog_symbol",
            ],
        ).replace("", pd.NA)
        candidates["orthology_type"] = _coalesce_columns(
            candidates,
            ["orthology_type", "orthology_type_x", "orthology_type_y", "orthology_type_orthology"],
        )
        candidates["confidence"] = _coalesce_columns(
            candidates,
            ["confidence", "confidence_x", "confidence_y", "confidence_orthology"],
        )
        mouse_deg = _read_annotations(
            run_directory / "deg" / "mouse" / "cross_study_exploratory" / "all_genes.csv",
            ["gene_id", "log2fc", "adjusted_p_value", "significant", "direction"],
        ).drop_duplicates(subset=["gene_id"], keep="first")
        if not mouse_deg.empty:
            mouse_deg = mouse_deg.rename(columns={
                "gene_id": "mouse_ensembl_id",
                "log2fc": "mouse_exploratory_log2fc",
                "adjusted_p_value": "mouse_exploratory_adjusted_p_value",
                "significant": "mouse_exploratory_significant",
                "direction": "mouse_exploratory_direction",
            })
            candidates = candidates.merge(
                mouse_deg,
                on="mouse_ensembl_id",
                how="left",
                validate="many_to_one",
            )
        mouse_nodes = _read_annotations(
            run_directory / "networks" / "mouse_cancer_nodes.csv",
            ["gene_id"],
        )
        mouse_node_ids = set(mouse_nodes["gene_id"].dropna().astype(str))
        ortholog_ids = candidates.get("mouse_ensembl_id")
        if ortholog_ids is None:
            ortholog_ids = candidates.get("one_to_one_mouse_ortholog_id", pd.Series(index=candidates.index, dtype=object))
        candidates["mouse_cancer_network_status"] = ortholog_ids.map(
            lambda value: (
                "Present in mouse cancer network"
                if pd.notna(value) and str(value) in mouse_node_ids
                else "Not present in saved mouse cancer network"
                if pd.notna(value)
                else "No mapped mouse ortholog in saved mapping"
            )
        )
        if "mouse_exploratory_significant" in candidates:
            candidates["mouse_expression_status"] = candidates.apply(
                lambda row: (
                    "Exploratory cross-study DEG significant"
                    if pd.notna(row["mouse_exploratory_significant"])
                    and bool(row["mouse_exploratory_significant"])
                    else "Not significant in exploratory cross-study DEG"
                    if pd.notna(row["mouse_exploratory_significant"])
                    else "No matching ortholog gene in saved exploratory mouse DEG results."
                ),
                axis=1,
            )
        else:
            candidates["mouse_expression_status"] = (
                "No exploratory mouse DEG results saved for this run."
            )
    else:
        candidates["mouse_cancer_network_status"] = "Not applicable for mouse-trained ranking"
        candidates["mouse_expression_status"] = "Not applicable for mouse-trained ranking"

    if "gene_symbol" not in candidates:
        candidates["gene_symbol"] = pd.NA
    network_symbols = candidates.get(
        "network_gene_symbol", pd.Series(index=candidates.index, dtype=object)
    )
    candidates["gene_symbol"] = (
        candidates["gene_symbol"].replace("", pd.NA).fillna(network_symbols)
    )
    reference_symbols = _reference_gene_symbols(
        species, set(candidates["gene_id"].dropna().astype(str))
    )
    candidates["gene_symbol"] = candidates["gene_symbol"].fillna(
        candidates["gene_id"].astype(str).map(reference_symbols)
    )

    pathway_annotations = _pathway_annotations(
        run_directory,
        species,
        set(candidates["gene_id"].dropna().astype(str)),
    )
    if not pathway_annotations.empty:
        candidates = candidates.merge(
            pathway_annotations, on="gene_id", how="left", validate="many_to_one"
        )
        candidates["enriched_pathway_names"] = (
            candidates.get("enriched_pathway_names", pd.Series(index=candidates.index, dtype=object))
            .replace("", pd.NA)
            .fillna(candidates["pathway_annotation_names"])
        )
        candidates["key_drifted_pathway_names"] = (
            candidates.get("key_drifted_pathway_names", pd.Series(index=candidates.index, dtype=object))
            .replace("", pd.NA)
            .fillna(candidates["key_drifted_annotation_names"])
        )
    pathway_outputs_exist = (
        (run_directory / "pathways" / "enrichment_results.csv").is_file()
        or (run_directory / "pathways" / "key_drifted_pathways.csv").is_file()
    )
    if "enriched_pathway_names" not in candidates:
        candidates["enriched_pathway_names"] = pd.NA
    if "key_drifted_pathway_names" not in candidates:
        candidates["key_drifted_pathway_names"] = pd.NA
    pathway_missing = (
        "No significant matching pathway membership in saved results."
        if pathway_outputs_exist
        else "No pathway enrichment results saved for this run."
    )
    candidates["enriched_pathway_names"] = (
        candidates["enriched_pathway_names"].replace("", pd.NA).fillna(pathway_missing)
    )
    candidates["key_drifted_pathway_names"] = (
        candidates["key_drifted_pathway_names"].replace("", pd.NA).fillna(
            "No matching key-drifted pathway in saved results."
            if pathway_outputs_exist
            else "No key-drifted pathway results saved for this run."
        )
    )

    morphology_summary_path = run_directory / "morphology" / "morphology_summary.json"
    morphology_summary = (
        json.loads(morphology_summary_path.read_text(encoding="utf-8"))
        if morphology_summary_path.is_file()
        else {}
    )
    if morphology_summary:
        morphology_detail = (
            "Clinical pathology metadata available; no gene-level morphology association was calculated."
            if morphology_summary.get("status") == "DESCRIPTIVE_METADATA_ONLY"
            else "Morphology results are available, but no gene-level association was calculated."
        )
    else:
        morphology_detail = "No morphology result artifact is saved for this run."
    if "morphology_status" not in candidates:
        candidates["morphology_status"] = pd.NA
    if "morphology_evidence" not in candidates:
        candidates["morphology_evidence"] = pd.NA
    candidates["morphology_status"] = candidates["morphology_status"].replace(
        "", pd.NA
    ).fillna(morphology_detail)
    candidates["morphology_evidence"] = candidates["morphology_evidence"].replace(
        "", pd.NA
    ).fillna(morphology_summary.get(
        "interpretation", morphology_detail
    ))
    candidates["drift_score"] = _coalesce_columns(
        candidates, ["drift_score", "cross_species_network_drift"]
    )
    candidates["drift_category"] = _coalesce_columns(
        candidates, ["drift_category", "cross_species_drift_category"]
    )
    if "module_id" not in candidates:
        candidates["module_id"] = candidates.get("network_module_id", pd.NA)
    if "pathway_names" not in candidates:
        candidates["pathway_names"] = candidates.get("enriched_pathway_names", pd.NA)
    if "morphology_status" not in candidates:
        candidates["morphology_status"] = candidates.get(
            "morphology_association_status", pd.NA
        )
    for column in (
        "gene_symbol", "mouse_ensembl_id", "mouse_symbol", "orthology_type",
        "relationship_cardinality", "confidence", "drift_score", "drift_category",
        "network_module_id",
    ):
        if column in candidates:
            candidates[column] = candidates[column].fillna(pd.NA)
    candidates["gene_symbol"] = candidates["gene_symbol"].fillna(
        "No gene symbol found in saved annotations."
    )

    evidence_columns = [
        "gene_id", "gene_symbol", "model", "model_rank", "feature_type",
        "importance", "mean_signed_weight", "direction", "selected_folds",
        "selection_frequency", "deg_log2fc", "deg_adjusted_p_value",
        "deg_significant", "deg_direction", "network_degree",
        "network_weighted_degree", "network_betweenness", "network_eigenvector",
        "network_module_id", "hub_supported", "mouse_ensembl_id",
        "mouse_symbol", "mouse_expression_status", "mouse_cancer_network_status", "orthology_type",
        "relationship_cardinality", "confidence", "drift_score",
        "drift_category", "edge_loss_rate", "neighbor_similarity",
        "lost_neighbor_count", "gained_neighbor_count", "conserved_neighbor_count",
        "enriched_pathway_names", "key_drifted_pathway_names",
        "morphology_status", "morphology_evidence",
        "biological_interpretation",
    ]
    for column in evidence_columns:
        if column not in candidates:
            candidates[column] = pd.NA
    evidence = candidates[evidence_columns].sort_values(
        ["model", "model_rank"], ascending=[True, True]
    )

    ranks = candidates.pivot_table(
        index="gene_id", columns="model", values="model_rank", aggfunc="min"
    )
    selections = candidates.pivot_table(
        index="gene_id", columns="model", values="selection_frequency", aggfunc="max"
    )
    consensus = pd.DataFrame(index=ranks.index)
    consensus["mean_model_rank"] = ranks.mean(axis=1)
    consensus["models_with_gene_selected"] = ranks.notna().sum(axis=1).astype(int)
    consensus["mean_selection_frequency_across_models"] = selections.fillna(0).mean(axis=1)
    consensus = consensus.reset_index().sort_values(
        ["mean_model_rank", "models_with_gene_selected", "mean_selection_frequency_across_models"],
        ascending=[True, False, False],
    )
    annotation_columns = [
        "gene_id", "gene_symbol", "deg_log2fc", "deg_adjusted_p_value",
        "deg_significant", "deg_direction", "network_degree",
        "network_weighted_degree", "network_betweenness", "network_eigenvector",
        "network_module_id", "hub_supported", "mouse_ensembl_id", "mouse_symbol",
        "mouse_expression_status", "mouse_cancer_network_status", "orthology_type",
        "relationship_cardinality", "confidence", "drift_score",
        "drift_category", "edge_loss_rate", "neighbor_similarity",
        "lost_neighbor_count", "gained_neighbor_count", "conserved_neighbor_count",
        "enriched_pathway_names", "key_drifted_pathway_names",
        "morphology_status", "morphology_evidence",
    ]
    annotations = evidence[annotation_columns].drop_duplicates(
        subset=["gene_id"], keep="first"
    )
    consensus = consensus.merge(annotations, on="gene_id", how="left", validate="one_to_one")
    consensus["candidate_interpretation"] = (
        "Machine-learning predictive feature with PathDrift annotations shown as context only; not a clinically validated biomarker."
    )
    return evidence, consensus


def run_phase6(
    run_id: str,
    *,
    species: str = "human",
    seed: int = 42,
    force: bool = False,
) -> dict[str, Any]:
    run_directory = (ROOT / "results" / "runs" / run_id).resolve()
    if species.lower() == "mouse":
        output_directory = run_directory / "ml" / "mouse"
        summary_path = output_directory / "phase6_summary.json"
        if summary_path.is_file() and not force:
            cached = json.loads(summary_path.read_text(encoding="utf-8"))
            if (
                cached.get("analysis_version") == "phase6-mouse-availability-1"
                and cached.get("run_id") == run_id
            ):
                return cached
        cohorts = summarize_labeled_cohorts(run_id, "mouse")
        estimable_cohorts = [
            cohort for cohort in cohorts
            if cohort["healthy_samples"] >= 3 and cohort["cancer_samples"] >= 3
        ]
        summary = {
            "analysis_version": "phase6-mouse-availability-1",
            "run_id": run_id,
            "species": "mouse",
            "status": "NOT_ESTIMABLE" if not estimable_cohorts else "NOT_RUN",
            "scientific_scope": (
                "Mouse-only classification is assessed within individual studies; separate "
                "GEO studies are not pooled because study and disease labels would be confounded."
            ),
            "reason": (
                "No individual mouse cohort contains both healthy and cancer samples in "
                "sufficient numbers for patient-independent classification. Combining "
                "cancer-only and healthy-only studies would make disease status inseparable "
                "from study, producing a misleading evaluation."
                if not estimable_cohorts else
                "A cohort has sufficient class counts, but mouse-model evaluation has not been run."
            ),
            "cohorts": cohorts,
            "estimable_cohorts": [cohort["accession"] for cohort in estimable_cohorts],
            "next_step": (
                "Add a matched mouse cancer-and-healthy cohort within the same study before "
                "running mouse-only classification."
            ),
        }
        _write_json(summary_path, summary)
        return summary
    if species.lower() != "human":
        raise ValueError("Phase 6 species must be either 'human' or 'mouse'.")

    summary_path = run_directory / "ml" / "phase6_summary.json"
    if summary_path.is_file() and not force:
        cached = json.loads(summary_path.read_text(encoding="utf-8"))
        if (
            cached.get("analysis_version") == "phase6-biological-cv-2"
            and cached.get("run_id") == run_id
            and cached.get("species") == species
            and cached.get("seed") == seed
            and all(
                (run_directory / artifact).is_file()
                for artifact in (
                    "ml/out_of_fold_predictions.csv",
                    "ml/feature_importance.csv",
                    "ml/predictive_biomarkers.csv",
                    "ml/cross_species_predictors.csv",
                    "ml/biological_oof_predictions.csv",
                    "ml/biological_feature_importance.csv",
                    "ml/biological_fold_evidence.csv",
                )
            )
        ):
            return cached

    dataset: LabeledExpression = load_labeled_expression(run_id, species)
    output_directory = run_directory / "ml"
    model_directory = output_directory / "models"
    output_directory.mkdir(parents=True, exist_ok=True)
    model_directory.mkdir(parents=True, exist_ok=True)
    labels = dataset.labels
    class_counts = {
        "healthy": int((labels == 0).sum()),
        "cancer": int((labels == 1).sum()),
    }
    metrics, predictions, fold_importance, models, split = evaluate_models(
        dataset.features, labels, dataset.groups, seed=seed
    )
    biological_experiments, biological_predictions, biological_importance = (
        evaluate_biological_experiments(
            run_directory,
            dataset.features,
            labels,
            dataset.groups,
            predictions,
            seed=seed,
        )
    )
    biological_predictions.to_csv(
        output_directory / "biological_oof_predictions.csv", index=False
    )
    biological_importance.to_csv(
        output_directory / "biological_feature_importance.csv", index=False
    )
    pd.DataFrame(biological_experiments["fold_evidence"]).to_csv(
        output_directory / "biological_fold_evidence.csv", index=False
    )
    predictions.to_csv(output_directory / "out_of_fold_predictions.csv", index=False)
    _save_feature_importances(output_directory, fold_importance)
    feature_annotations, predictive_biomarkers = _biological_annotations(
        run_directory, species, fold_importance
    )
    fold_candidate_ids = {
        candidate["gene_id"]
        for experiment in biological_experiments["experiments"].values()
        for candidate in experiment["candidate_features"]
    }
    candidate_symbols = _reference_gene_symbols(species, fold_candidate_ids)
    for experiment in biological_experiments["experiments"].values():
        for candidate in experiment["candidate_features"]:
            candidate["gene_symbol"] = candidate_symbols.get(candidate["gene_id"])
    feature_annotations.to_csv(output_directory / "feature_evidence.csv", index=False)
    predictive_biomarkers.to_csv(output_directory / "predictive_biomarkers.csv", index=False)
    cross_species_columns = [
        "gene_id", "gene_symbol", "mouse_ensembl_id", "mouse_symbol",
        "mouse_expression_status", "mouse_cancer_network_status", "orthology_type", "relationship_cardinality",
        "confidence", "drift_score", "drift_category", "edge_loss_rate",
        "neighbor_similarity", "lost_neighbor_count", "gained_neighbor_count",
        "conserved_neighbor_count", "mean_model_rank",
        "models_with_gene_selected", "mean_selection_frequency_across_models",
        "enriched_pathway_names", "key_drifted_pathway_names",
        "network_module_id", "morphology_status", "morphology_evidence",
    ]
    cross_species_table = predictive_biomarkers[
        [column for column in cross_species_columns if column in predictive_biomarkers]
    ].copy()
    cross_species_table.to_csv(output_directory / "cross_species_predictors.csv", index=False)
    plot_files = _write_curves(output_directory, predictions, metrics)
    for model_name, model in models.items():
        joblib.dump(model, model_directory / f"{model_name}.joblib")

    validation = {
        "run_id": run_id,
        "status": "UNAVAILABLE",
        "reason": (
            "Not available from current PathDrift data. No independent, matched human "
            "validation cohort with compatible labels and measurement provenance is present "
            "in this run. The mouse tumor and normal "
            "datasets are separate studies with different sample types and platforms; "
            "they are not used as an external validation set."
        ),
        "cross_species_transfer": {
            "status": "UNAVAILABLE",
            "reason": "Mouse cohorts do not provide a matched, compatible independent evaluation design.",
        },
        "permutation_test": {
            "status": "NOT_RUN",
            "reason": "A small, exploratory cohort and model comparison are not a prespecified confirmatory test.",
        },
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }
    validation_path = run_directory / "validation" / "phase6_validation.json"
    _write_json(validation_path, validation)

    expression_metrics = {
        model_name: {
            metric: model_result["out_of_fold_metrics"].get(metric)
            for metric in ("roc_auc", "f1", "sensitivity", "specificity")
        }
        for model_name, model_result in metrics.items()
    }
    feature_groups = {
        "expression_only": {
            "status": "EVALUATED",
            "source": str(dataset.expression_path),
            "features": int(dataset.features.shape[1]),
            "sample_level": True,
        },
        **_saved_feature_groups(run_directory, species),
    }
    feature_group_comparison = [
        {
            "comparison": "Model A — expression-only",
            "status": "EVALUATED",
            "feature_groups": ["normalized_expression"],
            "reason": "Uses only Phase 2 sample-level normalized expression values.",
            "model_metrics": expression_metrics,
        },
        {
            "comparison": "DEG-only ablation",
            "status": "NOT_EVALUATED",
            "feature_groups": ["differential_expression"],
            "reason": "Uses training-fold DEG ranking only.",
            "model_metrics": None,
        },
    ]
    experiment_feature_groups = {
        "deg_ranked_expression": ["fold_local_differential_expression"],
        "deg_plus_hubs": [
            "fold_local_differential_expression",
            "fold_local_human_network_hubs",
        ],
        "deg_plus_drift": [
            "fold_local_differential_expression",
            "fold_local_cross_species_network_drift",
        ],
        "integrated_biomarker_panel": [
            "fold_local_differential_expression",
            "fold_local_human_network_hubs",
            "fold_local_cross_species_network_drift",
        ],
    }
    experiment_comparisons = {
        "deg_ranked_expression": "DEG-only ablation",
        "deg_plus_hubs": "Fold-local DEG + human network hubs",
        "deg_plus_drift": "Fold-local DEG + cross-species network drift",
        "integrated_biomarker_panel": "Integrated fold-local candidate panel",
    }
    for experiment_id, comparison_label in experiment_comparisons.items():
        experiment = biological_experiments["experiments"][experiment_id]
        model_metrics = (
            {"logistic_regression": experiment["metrics"]}
            if experiment["metrics"] is not None
            else None
        )
        deltas = experiment.get("delta_from_expression_baseline")
        interval = experiment.get("roc_auc_95_percentile_interval")
        reason = experiment.get("reason")
        if experiment["status"] == "EVALUATED":
            reason = (
                f"Patient-grouped, fold-local feature generation; ROC-AUC delta vs "
                f"expression-only = {deltas['roc_auc']:+.3f}, PR-AUC delta = "
                f"{deltas['pr_auc']:+.3f}, F1 delta = {deltas['f1']:+.3f}. "
                f"ROC-AUC 95% group-bootstrap interval: "
                f"{interval if interval is not None else 'not estimable'}. "
                "Exploratory only; candidate genes are not clinically validated biomarkers."
            )
        if experiment_id == "deg_ranked_expression":
            deg_comparison = next(
                row for row in feature_group_comparison
                if row["comparison"] == "DEG-only ablation"
            )
            deg_comparison.update({
                "status": experiment["status"],
                "reason": reason,
                "model_metrics": model_metrics,
                "delta_from_expression_baseline": deltas,
                "roc_auc_95_percentile_interval": interval,
            })
        else:
            feature_group_comparison.append({
                "comparison": comparison_label,
                "status": experiment["status"],
                "feature_groups": experiment_feature_groups[experiment_id],
                "reason": reason or "Fold-local biological feature experiment was not estimable.",
                "model_metrics": model_metrics,
                "delta_from_expression_baseline": deltas,
                "roc_auc_95_percentile_interval": interval,
            })
    model_comparison = [
        {
            "model": model_name,
            "metrics": model_result["out_of_fold_metrics"],
            "auc_95_percentile_interval": model_result["auc_95_percentile_interval"],
            "interval_resampling_unit": model_result["auc_interval_resampling_unit"],
        }
        for model_name, model_result in metrics.items()
    ]
    summary = {
        "analysis_version": "phase6-biological-cv-2",
        "run_id": run_id,
        "species": species,
        "status": "PARTIAL",
        "scientific_scope": (
            "Exploratory within-cohort classification only. This small cohort does not establish "
            "clinical performance or independent generalization."
        ),
        "sample_counts": {
            "total": int(len(labels)),
            "class_counts": class_counts,
            "independent_patient_groups": (
                int(dataset.groups.nunique()) if dataset.groups is not None else None
            ),
        },
        "preprocessing": dataset.preprocessing,
        "data_provenance": {
            "accession": dataset.accession,
            "expression_path": str(dataset.expression_path),
            "metadata_path": str(dataset.metadata_path),
            "feature_source": "Phase 2 processed expression matrix",
            "feature_ids": "Gene identifiers are preserved as feature names.",
        },
        "validation_split": split,
        "models": metrics,
        "model_comparison": model_comparison,
        "feature_group_comparison": feature_group_comparison,
        "biological_experiments": biological_experiments,
        "feature_groups": feature_groups,
        "predictive_features": {
            "status": "AVAILABLE" if not predictive_biomarkers.empty else "UNAVAILABLE",
            "ranking_method": (
                "Mean per-model rank and model selection support, derived from fold-local model "
                "importance. Raw importance values remain model-specific and are not averaged."
            ),
            "feature_count": int(len(predictive_biomarkers)),
            "interpretation": (
                "Genes are exploratory predictive expression features. Phase 3–5 values are annotation "
                "context only; they are not used as sample-level predictors or clinically validated biomarkers."
            ),
        },
        "cross_species_analysis": {
            "status": "ANNOTATIONS_AVAILABLE" if not predictive_biomarkers.empty else "UNAVAILABLE",
            "interpretation": (
                "Orthology, saved mouse network presence, and cohort-level drift are annotations for "
                "ranked human predictive features. Missing mappings are not evidence of biological "
                "species-specificity; no expression-preserving/network-rewired claim is inferred."
            ),
            "artifact": "ml/cross_species_predictors.csv",
        },
        "independent_validation": validation,
        "model_configuration": {
            name: models[name].named_steps["model"].get_params(deep=False)
            for name in MODEL_NAMES
        },
        "artifacts": {
            "summary": "ml/phase6_summary.json",
            "predictions": "ml/out_of_fold_predictions.csv",
            "feature_importance": "ml/feature_importance.csv",
            "feature_evidence": "ml/feature_evidence.csv",
            "predictive_biomarkers": "ml/predictive_biomarkers.csv",
            "cross_species_predictors": "ml/cross_species_predictors.csv",
            "biological_oof_predictions": "ml/biological_oof_predictions.csv",
            "biological_feature_importance": "ml/biological_feature_importance.csv",
            "biological_fold_evidence": "ml/biological_fold_evidence.csv",
            "models": [f"ml/models/{name}.joblib" for name in MODEL_NAMES],
            "plots": [f"ml/{name}" for name in plot_files],
            "validation": "validation/phase6_validation.json",
        },
        "seed": seed,
        "software": {
            "python": os.sys.version.split()[0],
            "scikit_learn": __import__("sklearn").__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(summary_path, summary)
    return summary


def get_phase6_validation(run_id: str) -> dict[str, Any] | None:
    run_directory = (ROOT / "results" / "runs" / run_id).resolve()
    validation_path = run_directory / "validation" / "phase6_validation.json"
    if not validation_path.is_file():
        return None
    result = json.loads(validation_path.read_text(encoding="utf-8"))
    return result if result.get("run_id") == run_id else None
