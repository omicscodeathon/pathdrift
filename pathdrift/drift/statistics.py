from __future__ import annotations

import math
from collections import Counter

import pandas as pd


def summarize_drift(edges: pd.DataFrame, genes: pd.DataFrame, modules: pd.DataFrame) -> dict:
    if not genes.empty and (
        not genes["drift_score"].map(math.isfinite).all()
        or not genes["drift_score"].between(0, 1).all()
    ):
        raise ValueError("Gene drift scores must be finite and within [0, 1].")
    edge_counts = Counter(edges["status"].astype(str)) if not edges.empty else Counter()
    module_counts = Counter(modules["classification"].astype(str)) if not modules.empty else Counter()
    top = genes.sort_values("drift_score", ascending=False).head(50)
    top_genes = []
    for rank, row in enumerate(top.to_dict(orient="records"), start=1):
        top_genes.append({
            "rank": rank,
            "human_gene_id": row["human_ensembl_id"],
            "human_symbol": row.get("human_symbol"),
            "mouse_gene_id": row["mouse_ensembl_id"],
            "mouse_symbol": row.get("mouse_symbol"),
            "drift_score": row["drift_score"],
            "edge_loss_rate": row["edge_loss_rate"],
            "neighbor_similarity": row["neighbor_similarity"],
            "degree_difference": row["degree_difference"],
            "module_conservation": row.get("module_conservation"),
        })
    return {
        "edge_status_counts": dict(edge_counts),
        "module_classification_counts": dict(module_counts),
        "aligned_gene_count": len(genes),
        "mean_gene_drift_score": float(genes["drift_score"].mean()) if not genes.empty else None,
        "top_drifted_genes": top_genes,
    }
