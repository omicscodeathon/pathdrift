from __future__ import annotations

import math

import pandas as pd


DEFAULT_WEIGHTS = {"edge_loss": 0.5, "neighbor_discordance": 0.3, "degree_difference": 0.2}
DEFAULT_THRESHOLDS = {"moderate_drift": 0.33, "high_drift": 0.66}


def validate_scoring_configuration(weights: dict, thresholds: dict) -> None:
    required_weights = set(DEFAULT_WEIGHTS)
    if set(weights) != required_weights:
        raise ValueError(f"Drift weights must contain exactly {sorted(required_weights)}.")
    if any(not math.isfinite(float(value)) or float(value) < 0 for value in weights.values()):
        raise ValueError("Drift weights must be finite and non-negative.")
    if not math.isclose(sum(map(float, weights.values())), 1.0, abs_tol=1e-9):
        raise ValueError("Drift weights must sum to 1.")
    moderate = float(thresholds["moderate_drift"])
    high = float(thresholds["high_drift"])
    if not 0 <= moderate < high <= 1:
        raise ValueError("Drift thresholds must satisfy 0 <= moderate < high <= 1.")


def compute_gene_drift(
    human_nodes: pd.DataFrame,
    mouse_nodes: pd.DataFrame,
    human_edges: pd.DataFrame,
    mouse_edges: pd.DataFrame,
    primary_mapping: pd.DataFrame,
    *,
    weights: dict | None = None,
    thresholds: dict | None = None,
    module_alignment: pd.DataFrame | None = None,
) -> pd.DataFrame:
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    thresholds = dict(DEFAULT_THRESHOLDS if thresholds is None else thresholds)
    validate_scoring_configuration(weights, thresholds)
    h_to_m = dict(zip(primary_mapping["human_ensembl_id"], primary_mapping["mouse_ensembl_id"]))
    m_to_h = {mouse: human for human, mouse in h_to_m.items()}
    if len(h_to_m) != len(primary_mapping) or len(m_to_h) != len(primary_mapping):
        raise ValueError("Cannot compute gene drift with ambiguous primary orthology.")
    hn = human_nodes.set_index("gene_id", drop=False)
    mn = mouse_nodes.set_index("gene_id", drop=False)
    aligned = [
        (human, mouse)
        for human, mouse in h_to_m.items()
        if human in hn.index and mouse in mn.index
    ]
    h_neighbors: dict[str, set[str]] = {human: set() for human, _ in aligned}
    m_neighbors: dict[str, set[str]] = {human: set() for human, _ in aligned}
    for row in human_edges.itertuples(index=False):
        left, right = str(row.source_gene), str(row.target_gene)
        if left in h_neighbors and right in h_to_m:
            h_neighbors[left].add(right)
        if right in h_neighbors and left in h_to_m:
            h_neighbors[right].add(left)
    for row in mouse_edges.itertuples(index=False):
        left, right = str(row.source_gene), str(row.target_gene)
        human_left, human_right = m_to_h.get(left), m_to_h.get(right)
        if human_left in m_neighbors and human_right is not None:
            m_neighbors[human_left].add(human_right)
        if human_right in m_neighbors and human_left is not None:
            m_neighbors[human_right].add(human_left)
    max_degree = max(
        [int(value) for value in human_nodes["degree"]]
        + [int(value) for value in mouse_nodes["degree"]]
        + [1]
    )
    module_score_by_pair: dict[tuple[str, str], float] = {}
    if module_alignment is not None and not module_alignment.empty:
        for row in module_alignment.to_dict(orient="records"):
            candidate = row.get("candidate_mouse_module_id")
            score = float(row["module_conservation_score"])
            module_score_by_pair[(str(row["human_module_id"]), str(candidate))] = score

    rows = []
    for human, mouse in aligned:
        human_neighbors = h_neighbors[human]
        mouse_neighbors = m_neighbors[human]
        conserved = human_neighbors & mouse_neighbors
        lost = human_neighbors - mouse_neighbors
        gained = mouse_neighbors - human_neighbors
        union = human_neighbors | mouse_neighbors
        similarity = len(conserved) / len(union) if union else 1.0
        edge_loss = len(lost) / len(human_neighbors) if human_neighbors else 0.0
        human_degree = int(hn.at[human, "degree"])
        mouse_degree = int(mn.at[mouse, "degree"])
        degree_difference = mouse_degree - human_degree
        normalized_degree_difference = min(1.0, abs(degree_difference) / max_degree)
        score = (
            float(weights["edge_loss"]) * edge_loss
            + float(weights["neighbor_discordance"]) * (1.0 - similarity)
            + float(weights["degree_difference"]) * normalized_degree_difference
        )
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"Computed invalid drift score for {human}/{mouse}: {score}.")
        category = (
            "HIGH_DRIFT" if score >= float(thresholds["high_drift"])
            else "MODERATE_DRIFT" if score >= float(thresholds["moderate_drift"])
            else "LOW_DRIFT"
        )
        human_module = str(hn.at[human, "module_id"]) if pd.notna(hn.at[human, "module_id"]) else None
        mouse_module = str(mn.at[mouse, "module_id"]) if pd.notna(mn.at[mouse, "module_id"]) else None
        module_score = module_score_by_pair.get((human_module, mouse_module)) if human_module and mouse_module else None
        rows.append({
            "human_ensembl_id": human,
            "mouse_ensembl_id": mouse,
            "human_symbol": hn.at[human, "gene_symbol"] if "gene_symbol" in hn else None,
            "mouse_symbol": mn.at[mouse, "gene_symbol"] if "gene_symbol" in mn else None,
            "human_degree": human_degree,
            "mouse_degree": mouse_degree,
            "degree_difference": degree_difference,
            "human_neighbor_count": len(human_neighbors),
            "mouse_neighbor_count": len(mouse_neighbors),
            "conserved_neighbor_count": len(conserved),
            "lost_neighbor_count": len(lost),
            "gained_neighbor_count": len(gained),
            "neighbor_similarity": similarity,
            "edge_loss_rate": edge_loss,
            "normalized_degree_difference": normalized_degree_difference,
            "module_conservation": module_score,
            "drift_score": score,
            "drift_category": category,
        })
    return pd.DataFrame(rows).sort_values("drift_score", ascending=False, ignore_index=True)
