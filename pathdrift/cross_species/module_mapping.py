from __future__ import annotations

from collections import defaultdict

import pandas as pd


def align_modules(
    human_modules: pd.DataFrame,
    human_module_genes: pd.DataFrame,
    mouse_modules: pd.DataFrame,
    mouse_module_genes: pd.DataFrame,
    primary_mapping: pd.DataFrame,
    *,
    conserved_threshold: float = 0.7,
    partial_threshold: float = 0.3,
) -> pd.DataFrame:
    if not 0 <= partial_threshold <= conserved_threshold <= 1:
        raise ValueError("Module thresholds must satisfy 0 <= partial <= conserved <= 1.")
    h_to_m = dict(zip(primary_mapping["human_ensembl_id"], primary_mapping["mouse_ensembl_id"]))
    h_genes_by_module: dict[str, set[str]] = defaultdict(set)
    m_genes_by_module: dict[str, set[str]] = defaultdict(set)
    for row in human_module_genes.to_dict(orient="records"):
        h_genes_by_module[str(row["module_id"])].add(str(row["gene_id"]))
    for row in mouse_module_genes.to_dict(orient="records"):
        m_genes_by_module[str(row["module_id"])].add(str(row["gene_id"]))
    mouse_module_sizes = {
        str(row["module_id"]): int(row.get("size", len(m_genes_by_module[str(row["module_id"])])))
        for row in mouse_modules.to_dict(orient="records")
    }
    rows = []
    for module in human_modules.to_dict(orient="records"):
        human_module_id = str(module["module_id"])
        genes = h_genes_by_module.get(human_module_id, set())
        mapped = {h_to_m[gene] for gene in genes if gene in h_to_m}
        candidates = []
        for mouse_module_id, mouse_genes in m_genes_by_module.items():
            overlap = mapped & mouse_genes
            if not overlap:
                continue
            union = mapped | mouse_genes
            score = len(overlap) / len(union) if union else 0.0
            candidates.append((mouse_module_id, mouse_genes, len(overlap), score))
        if not candidates:
            rows.append({
                "human_module_id": human_module_id,
                "candidate_mouse_module_id": None,
                "human_module_size": int(module.get("size", len(genes))),
                "mapped_gene_count": len(mapped),
                "mouse_module_overlap": 0,
                "overlap_fraction": 0.0,
                "module_conservation_score": 0.0,
                "internal_edge_conservation": None,
                "classification": "NOT_ALIGNED" if mapped else "NOT_ALIGNED",
            })
            continue
        candidate_union = set().union(*(entry[1] for entry in candidates))
        fragmented = sum(entry[2] > 0 for entry in candidates) > 1
        best_score = max(entry[3] for entry in candidates)
        if fragmented and len(candidate_union & mapped) == len(mapped):
            classification = "FRAGMENTED"
        elif best_score >= conserved_threshold:
            classification = "CONSERVED"
        elif best_score >= partial_threshold:
            classification = "PARTIALLY_CONSERVED"
        else:
            classification = "REWIRED"
        for mouse_module_id, mouse_genes, overlap, score in candidates:
            rows.append({
                "human_module_id": human_module_id,
                "candidate_mouse_module_id": mouse_module_id,
                "human_module_size": int(module.get("size", len(genes))),
                "mapped_gene_count": len(mapped),
                "mouse_module_overlap": overlap,
                "overlap_fraction": overlap / len(mapped) if mapped else 0.0,
                "module_conservation_score": score,
                "internal_edge_conservation": None,
                "classification": classification,
                "candidate_mouse_module_size": mouse_module_sizes.get(mouse_module_id, len(mouse_genes)),
            })
    return pd.DataFrame(rows)
