from __future__ import annotations

import math
from typing import Any

import pandas as pd


DEFAULT_CONFIGURATION: dict[str, Any] = {
    "gene_loss_weights": {"network_drift": 0.5, "human_expression_loss": 0.5},
    "risk_thresholds": {"moderate": 0.33, "high": 0.66},
    "deg_fdr_threshold": 0.05,
    "deg_lfc_threshold": 1.0,
    "biomarker_selection": (
        "A candidate must be a significant human DEG, include at least one additional evidence "
        "category, and have at least one cross-dimensional network support category (hub support "
        "across at least two centrality metrics, measured network drift, or observed "
        "lost/gained interactions). DEG alone, module association alone, and orthology alone do "
        "not qualify. Eligible candidates are ordered by evidence-category count, adjusted p-value, "
        "and absolute log2 fold change; no composite biomarker score is used."
    ),
}


def _validate_configuration(configuration: dict[str, Any]) -> None:
    weights = configuration["gene_loss_weights"]
    if set(weights) != {"network_drift", "human_expression_loss"}:
        raise ValueError("Gene-loss weights must define network_drift and human_expression_loss.")
    values = [float(value) for value in weights.values()]
    if any(not math.isfinite(value) or value < 0 for value in values) or sum(values) <= 0:
        raise ValueError("Gene-loss weights must be finite, non-negative, and have a positive sum.")
    thresholds = configuration["risk_thresholds"]
    moderate, high = float(thresholds["moderate"]), float(thresholds["high"])
    if not 0 <= moderate < high <= 1:
        raise ValueError("Risk thresholds must satisfy 0 <= moderate < high <= 1.")
    fdr = float(configuration["deg_fdr_threshold"])
    if not 0 < fdr <= 1:
        raise ValueError("The DEG FDR threshold must be in (0, 1].")
    lfc_threshold = float(configuration["deg_lfc_threshold"])
    if not math.isfinite(lfc_threshold) or lfc_threshold < 0:
        raise ValueError("The DEG log2FC threshold must be finite and non-negative.")


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def compute_hub_metrics(
    nodes: pd.DataFrame,
    edges: pd.DataFrame | None = None,
    *,
    hub_percentile_threshold: float = 0.9,
) -> pd.DataFrame:
    """Calculate a documented within-module multi-centrality hub measure."""
    if "gene_id" not in nodes.columns:
        raise ValueError("Network node artifact must contain gene_id.")
    if not math.isfinite(hub_percentile_threshold) or not 0 < hub_percentile_threshold <= 1:
        raise ValueError("Hub percentile threshold must be in (0, 1].")
    result = nodes.drop_duplicates("gene_id", keep="first").copy()
    result["gene_id"] = result["gene_id"].astype(str)
    if "module_id" not in result.columns:
        result["module_id"] = pd.NA
    result["_hub_module"] = result["module_id"].fillna("__unassigned__").astype(str)

    if edges is not None and {"source_gene", "target_gene"}.issubset(edges.columns):
        module_by_gene = dict(zip(result["gene_id"], result["module_id"]))
        intramodular_counts: dict[str, int] = {}
        for left, right in edges[["source_gene", "target_gene"]].dropna().astype(str).itertuples(index=False, name=None):
            if pd.notna(module_by_gene.get(left)) and module_by_gene.get(left) == module_by_gene.get(right):
                intramodular_counts[left] = intramodular_counts.get(left, 0) + 1
                intramodular_counts[right] = intramodular_counts.get(right, 0) + 1
        result["intramodular_connectivity"] = result["gene_id"].map(intramodular_counts).fillna(0)

    source_metrics = [
        column for column in (
            "degree", "weighted_degree", "betweenness_centrality",
            "eigenvector_centrality", "closeness_centrality",
        )
        if column in result.columns
    ]
    metric_percentiles = []
    for metric in source_metrics:
        percentile = f"{metric}_module_percentile"
        values = pd.to_numeric(result[metric], errors="coerce")
        result[percentile] = values.groupby(result["_hub_module"]).rank(pct=True, method="average")
        metric_percentiles.append(percentile)
    if "intramodular_connectivity" in result.columns:
        percentile = "intramodular_connectivity_module_percentile"
        values = pd.to_numeric(result["intramodular_connectivity"], errors="coerce")
        result[percentile] = values.groupby(result["_hub_module"]).rank(pct=True, method="average")
        metric_percentiles.append(percentile)

    if not metric_percentiles:
        result["hub_score"] = pd.NA
        result["hub_metric_count"] = 0
        result["hub_supported"] = pd.NA
    else:
        result["hub_metric_count"] = result[metric_percentiles].notna().sum(axis=1)
        result["hub_score"] = result[metric_percentiles].mean(axis=1)
        result["hub_supported"] = (
            result["hub_score"].ge(hub_percentile_threshold)
            & result["hub_metric_count"].ge(2)
        ).astype("boolean")
        result.loc[result["hub_metric_count"] < 2, "hub_supported"] = pd.NA
        result.loc[result["_hub_module"] == "__unassigned__", "hub_supported"] = pd.NA
    result["hub_percentile_threshold"] = hub_percentile_threshold
    result["hub_score_method"] = (
        "Arithmetic mean of within-module percentiles for available degree, weighted degree, "
        "betweenness, eigenvector centrality, closeness, and intramodular connectivity; "
        f"hub support requires at least two available metrics and score >= "
        f"{hub_percentile_threshold:.2f} in an assigned module."
    )
    return result.drop(columns=["_hub_module"])


def build_gene_loss_tables(
    human_deg: pd.DataFrame,
    mouse_deg: pd.DataFrame,
    drift: pd.DataFrame,
    orthology: pd.DataFrame,
    *,
    configuration: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build transparent gene-loss evidence and scores from observed run artifacts."""
    config = {**DEFAULT_CONFIGURATION, **(configuration or {})}
    config["gene_loss_weights"] = dict(
        DEFAULT_CONFIGURATION["gene_loss_weights"],
        **(configuration or {}).get("gene_loss_weights", {}),
    )
    config["risk_thresholds"] = dict(
        DEFAULT_CONFIGURATION["risk_thresholds"],
        **(configuration or {}).get("risk_thresholds", {}),
    )
    _validate_configuration(config)

    required_drift = {"human_ensembl_id", "mouse_ensembl_id", "drift_score", "drift_category"}
    if not required_drift.issubset(drift.columns):
        raise ValueError(f"Drift artifact is missing required columns: {sorted(required_drift - set(drift.columns))}.")
    if not {"human_ensembl_id", "mouse_ensembl_id"}.issubset(orthology.columns):
        raise ValueError("Orthology artifact must contain human_ensembl_id and mouse_ensembl_id.")
    if "gene_id" not in human_deg.columns or "gene_id" not in mouse_deg.columns:
        raise ValueError("Both DEG artifacts must contain gene_id.")

    human_by_id = human_deg.drop_duplicates("gene_id", keep="first").set_index("gene_id")
    mouse_by_id = mouse_deg.drop_duplicates("gene_id", keep="first").set_index("gene_id")
    one_to_one = orthology.loc[
        orthology.get("orthology_type", pd.Series(index=orthology.index, dtype=object)).eq("ortholog_one2one")
    ]
    mapped_pairs = set(zip(one_to_one["human_ensembl_id"].astype(str), one_to_one["mouse_ensembl_id"].astype(str)))
    rows: list[dict[str, Any]] = []

    for pair in drift.to_dict(orient="records"):
        human_id, mouse_id = str(pair["human_ensembl_id"]), str(pair["mouse_ensembl_id"])
        human_stats = human_by_id.loc[human_id].to_dict() if human_id in human_by_id.index else {}
        mouse_stats = mouse_by_id.loc[mouse_id].to_dict() if mouse_id in mouse_by_id.index else {}
        human_lfc = _number(human_stats.get("log2fc", human_stats.get("log2FoldChange")))
        human_fdr = _number(human_stats.get("adjusted_p_value", human_stats.get("padj")))
        mouse_lfc = _number(mouse_stats.get("log2fc", mouse_stats.get("log2FoldChange")))
        mouse_fdr = _number(mouse_stats.get("adjusted_p_value", mouse_stats.get("padj")))
        human_testable = human_lfc is not None and human_fdr is not None
        mouse_testable = mouse_lfc is not None and mouse_fdr is not None
        human_down = (
            human_testable
            and human_lfc <= -float(config["deg_lfc_threshold"])
            and human_fdr <= float(config["deg_fdr_threshold"])
        )
        mouse_down = (
            mouse_testable
            and mouse_lfc <= -float(config["deg_lfc_threshold"])
            and mouse_fdr <= float(config["deg_fdr_threshold"])
        )
        drift_score = _number(pair.get("drift_score"))
        network_component = drift_score
        expression_component = 1.0 if human_down else (0.0 if human_testable else None)
        available = {
            "network_drift": network_component,
            "human_expression_loss": expression_component,
        }
        active = [
            (float(config["gene_loss_weights"][name]), value)
            for name, value in available.items()
            if value is not None
        ]
        score = sum(weight * value for weight, value in active) / sum(weight for weight, _ in active) if active and sum(weight for weight, _ in active) > 0 else None
        thresholds = config["risk_thresholds"]
        category = (
            "HIGH" if score is not None and score >= float(thresholds["high"])
            else "MODERATE" if score is not None and score >= float(thresholds["moderate"])
            else "LOW" if score is not None
            else "NOT_SCORED"
        )
        rows.append({
            "human_gene_id": human_id,
            "mouse_gene_id": mouse_id,
            "human_symbol": pair.get("human_symbol") or human_stats.get("gene_symbol"),
            "mouse_symbol": pair.get("mouse_symbol") or mouse_stats.get("gene_symbol"),
            "one_to_one_orthology_recorded": (human_id, mouse_id) in mapped_pairs,
            "human_log2fc": human_lfc,
            "human_adjusted_p_value": human_fdr,
            "human_expression_loss": human_down if human_testable else None,
            "mouse_exploratory_log2fc": mouse_lfc,
            "mouse_exploratory_adjusted_p_value": mouse_fdr,
            "mouse_exploratory_downregulated": mouse_down if mouse_testable else None,
            "mouse_expression_caveat": "Independent-study comparison; exploratory and excluded from risk score.",
            "drift_score": drift_score,
            "drift_category": pair.get("drift_category"),
            "edge_loss_rate": _number(pair.get("edge_loss_rate")),
            "network_drift_component": network_component,
            "human_expression_loss_component": expression_component,
            "risk_score": score,
            "risk_category": category,
            "score_evidence_count": len(active),
            "score_method": "Configured weighted mean over observed components; missing components are excluded and remaining weights renormalized.",
            "score_limitations": "Research prioritization only; cross-species network density is highly imbalanced and mouse expression is not matched-control evidence.",
            "ppi_evidence": None,
            "pathway_evidence": None,
            "morphology_evidence": None,
        })

    evidence = pd.DataFrame(rows)
    if evidence.empty:
        return evidence, evidence.copy(), evidence.copy()
    scores = evidence.sort_values(
        ["risk_score", "score_evidence_count", "human_gene_id"],
        ascending=[False, False, True],
        na_position="last",
        ignore_index=True,
    )
    high_risk = scores.loc[scores["risk_category"] == "HIGH"].copy().reset_index(drop=True)
    return evidence, scores, high_risk


def build_biomarker_candidates(
    human_significant_deg: pd.DataFrame,
    human_nodes: pd.DataFrame,
    drift: pd.DataFrame,
    orthology: pd.DataFrame,
    human_edges: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Select research-only candidates supported by at least two evidence dimensions."""
    if "gene_id" not in human_significant_deg.columns:
        raise ValueError("Human significant DEG artifact must contain gene_id.")
    if "gene_id" not in human_nodes.columns:
        raise ValueError("Human network node artifact must contain gene_id.")
    if "human_ensembl_id" not in drift.columns:
        raise ValueError("Gene drift artifact must contain human_ensembl_id.")

    deg = human_significant_deg.drop_duplicates("gene_id", keep="first").copy()
    deg["gene_id"] = deg["gene_id"].astype(str)
    nodes = compute_hub_metrics(human_nodes, human_edges)
    percentile_columns = [column for column in nodes.columns if column.endswith("_module_percentile")]
    nodes = nodes.rename(columns={
        "gene_symbol": "network_gene_symbol",
        "degree": "network_degree",
        "weighted_degree": "network_weighted_degree",
        "betweenness_centrality": "network_betweenness",
        "eigenvector_centrality": "network_eigenvector",
        "module_id": "network_module_id",
    })
    node_keep = ["gene_id"] + [
        column for column in (
            "network_gene_symbol", "network_degree", "network_weighted_degree",
            "network_betweenness", "network_eigenvector", "network_module_id",
            "hub_score", "hub_metric_count", "hub_supported", "hub_score_method",
            "intramodular_connectivity",
            *percentile_columns,
        )
        if column in nodes.columns
    ]
    candidates = deg.merge(nodes[node_keep], on="gene_id", how="left")

    drift_columns_by_name = {
        "human_ensembl_id": "gene_id",
        "mouse_ensembl_id": "one_to_one_mouse_ortholog_id",
        "mouse_symbol": "mouse_ortholog_symbol",
        "human_symbol": "drift_human_symbol",
        "drift_score": "cross_species_network_drift",
        "drift_category": "cross_species_drift_category",
        "edge_loss_rate": "mapped_edge_loss_rate",
        "lost_neighbor_count": "lost_interaction_count",
        "gained_neighbor_count": "gained_interaction_count",
        "conserved_neighbor_count": "conserved_interaction_count",
    }
    drift_by_human = drift.drop_duplicates("human_ensembl_id", keep="first").rename(columns=drift_columns_by_name)
    drift_keep = ["gene_id"] + [
        column for column in (
            "one_to_one_mouse_ortholog_id", "mouse_ortholog_symbol", "drift_human_symbol",
            "cross_species_network_drift", "cross_species_drift_category", "mapped_edge_loss_rate",
            "lost_interaction_count", "gained_interaction_count", "conserved_interaction_count",
        )
        if column in drift_by_human.columns
    ]
    candidates = candidates.merge(drift_by_human[drift_keep], on="gene_id", how="left")

    if {"human_ensembl_id", "mouse_ensembl_id"}.issubset(orthology.columns):
        orthology_columns = ["human_ensembl_id", "mouse_ensembl_id"] + [
            column for column in ("human_symbol", "mouse_symbol", "confidence", "orthology_type")
            if column in orthology.columns
        ]
        mappings = orthology.loc[
            orthology.get("orthology_type", pd.Series(index=orthology.index, dtype=object)).eq("ortholog_one2one"),
            orthology_columns,
        ].drop_duplicates("human_ensembl_id").rename(columns={
            "human_ensembl_id": "gene_id",
            "mouse_ensembl_id": "orthology_mouse_gene_id",
            "human_symbol": "orthology_human_symbol",
            "mouse_symbol": "orthology_mouse_symbol",
            "confidence": "orthology_confidence",
        })
        candidates = candidates.merge(mappings, on="gene_id", how="left")
        if "one_to_one_mouse_ortholog_id" not in candidates:
            candidates["one_to_one_mouse_ortholog_id"] = candidates.get("orthology_mouse_gene_id")
        else:
            candidates["one_to_one_mouse_ortholog_id"] = candidates["one_to_one_mouse_ortholog_id"].fillna(candidates.get("orthology_mouse_gene_id"))
        if "mouse_ortholog_symbol" not in candidates:
            candidates["mouse_ortholog_symbol"] = candidates.get("orthology_mouse_symbol")
        else:
            candidates["mouse_ortholog_symbol"] = candidates["mouse_ortholog_symbol"].fillna(candidates.get("orthology_mouse_symbol"))
        candidates["one_to_one_orthology"] = candidates["one_to_one_mouse_ortholog_id"].notna()

    if "gene_symbol" not in candidates.columns:
        candidates["gene_symbol"] = candidates.get("orthology_human_symbol")
    elif "orthology_human_symbol" in candidates.columns:
        candidates["gene_symbol"] = candidates["gene_symbol"].fillna(candidates["orthology_human_symbol"])
    if "gene_symbol" in candidates.columns and "network_gene_symbol" in candidates.columns:
        candidates["gene_symbol"] = candidates["gene_symbol"].fillna(candidates["network_gene_symbol"])
    if "gene_symbol" in candidates.columns and "drift_human_symbol" in candidates.columns:
        candidates["gene_symbol"] = candidates["gene_symbol"].fillna(candidates["drift_human_symbol"])

    fdr_column = next((name for name in ("adjusted_p_value", "padj", "fdr") if name in candidates.columns), None)
    lfc_column = next((name for name in ("log2fc", "log2FoldChange", "log2_fold_change") if name in candidates.columns), None)
    fdr_values = pd.to_numeric(candidates[fdr_column], errors="coerce") if fdr_column else pd.Series(index=candidates.index, dtype=float)
    lfc_values = pd.to_numeric(candidates[lfc_column], errors="coerce") if lfc_column else pd.Series(index=candidates.index, dtype=float)
    threshold_based_deg = (
        fdr_values.le(DEFAULT_CONFIGURATION["deg_fdr_threshold"])
        & lfc_values.abs().ge(DEFAULT_CONFIGURATION["deg_lfc_threshold"])
    )
    if "significant" in candidates.columns:
        reported_significant = candidates["significant"].astype("string").str.lower().isin({"true", "1", "yes"})
        deg_supported = reported_significant & threshold_based_deg
    else:
        deg_supported = threshold_based_deg
    hub_supported = (
        candidates.get("hub_supported", pd.Series(False, index=candidates.index))
        .eq(True)
        .fillna(False)
    )
    drift_values = pd.to_numeric(
        candidates.get("cross_species_network_drift", pd.Series(index=candidates.index, dtype=float)),
        errors="coerce",
    )
    drift_supported = drift_values.ge(0.66)
    lost_supported = pd.to_numeric(
        candidates.get("lost_interaction_count", pd.Series(index=candidates.index, dtype=float)),
        errors="coerce",
    ).fillna(0).gt(0)
    gained_supported = pd.to_numeric(
        candidates.get("gained_interaction_count", pd.Series(index=candidates.index, dtype=float)),
        errors="coerce",
    ).fillna(0).gt(0)

    categories = []
    evidence_count = []
    for index in candidates.index:
        row_categories = []
        if deg_supported.loc[index]:
            row_categories.append("DEG-supported")
        if hub_supported.loc[index]:
            row_categories.append("hub-supported")
        if drift_supported.loc[index]:
            row_categories.append("drift-supported")
        if lost_supported.loc[index]:
            row_categories.append("interaction-loss-supported")
        if gained_supported.loc[index]:
            row_categories.append("interaction-gain-supported")
        if candidates.loc[index].get("network_module_id") is not None and pd.notna(candidates.loc[index].get("network_module_id")):
            row_categories.append("module-associated")
        if candidates.loc[index].get("one_to_one_orthology", False):
            row_categories.append("orthology-supported")
        categories.append(row_categories)
        evidence_count.append(len(row_categories))
    candidates["evidence_categories"] = categories
    candidates["evidence_category_count"] = evidence_count
    cross_dimensional_support = hub_supported | drift_supported | lost_supported | gained_supported
    candidates["candidate_status"] = (
        (deg_supported & candidates["evidence_category_count"].ge(2) & cross_dimensional_support)
        .map({True: "MULTI_EVIDENCE_CANDIDATE", False: "INSUFFICIENT_CROSS-DIMENSIONAL_EVIDENCE"})
    )
    candidates["selection_basis"] = (
        "Requires a significant human DEG, at least two evidence categories, and at least one "
        "cross-dimensional support category among multi-metric "
        "within-module hub support (at least two available metrics), measured network drift, or observed lost/gained interactions. "
        "Module and orthology context are reported but cannot qualify a DEG alone. No composite "
        "biomarker score is used."
    )
    candidates["mouse_expression_evidence"] = (
        "The available mouse comparison is independent-study exploratory and is not considered "
        "independent validation or sufficient biomarker support."
    )
    candidates["pathway_evidence"] = "Unavailable: no local, versioned pathway gene-set resource is configured."
    candidates["morphology_evidence"] = "Unavailable: this run contains no compatible morphology measurements."
    candidates["independent_validation"] = False
    candidates["clinical_validation"] = False
    candidates = candidates.loc[candidates["candidate_status"] == "MULTI_EVIDENCE_CANDIDATE"].copy()
    candidates["_fdr"] = pd.to_numeric(candidates[fdr_column], errors="coerce") if fdr_column else float("inf")
    candidates["_absolute_lfc"] = pd.to_numeric(candidates[lfc_column], errors="coerce").abs() if lfc_column else 0.0
    return candidates.sort_values(
        ["evidence_category_count", "_fdr", "_absolute_lfc", "gene_id"],
        ascending=[False, True, False, True],
        na_position="last",
        ignore_index=True,
    ).drop(columns=["_fdr", "_absolute_lfc"])
