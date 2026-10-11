from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _valid_edges(edges: pd.DataFrame, species: str) -> list[dict[str, Any]]:
    required = {"source_gene", "target_gene", "weight"}
    missing = required - set(edges.columns)
    if missing:
        raise ValueError(f"{species} network edges lack required columns: {sorted(missing)}")
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in edges.to_dict(orient="records"):
        source, target = str(row["source_gene"]), str(row["target_gene"])
        if source == target:
            raise ValueError(f"{species} network contains a self-loop at {source}.")
        key = tuple(sorted((source, target)))
        if key in seen:
            raise ValueError(f"{species} network contains a duplicate undirected edge: {key}.")
        seen.add(key)
        weight = float(row["weight"])
        if not math.isfinite(weight):
            raise ValueError(f"{species} network edge has a non-finite weight: {key}.")
        records.append({**row, "source_gene": source, "target_gene": target, "_key": key})
    return records


def align_edges(
    human_edges: pd.DataFrame,
    mouse_edges: pd.DataFrame,
    primary_mapping: pd.DataFrame,
    rewiring_threshold: float = 0.05,
) -> pd.DataFrame:
    if not math.isfinite(rewiring_threshold) or rewiring_threshold < 0:
        raise ValueError("Rewiring threshold must be a finite non-negative value.")
    h_to_m = dict(zip(
        primary_mapping["human_ensembl_id"].astype(str),
        primary_mapping["mouse_ensembl_id"].astype(str),
    ))
    m_to_h = {mouse: human for human, mouse in h_to_m.items()}
    if len(h_to_m) != len(primary_mapping) or len(m_to_h) != len(primary_mapping):
        raise ValueError("Primary orthology mapping is ambiguous.")

    human_records = _valid_edges(human_edges, "human")
    mouse_records = _valid_edges(mouse_edges, "mouse")
    mouse_by_canonical: dict[tuple[str, str], dict[str, Any]] = {}
    mouse_unmappable: list[dict[str, Any]] = []
    for edge in mouse_records:
        left = m_to_h.get(edge["source_gene"])
        right = m_to_h.get(edge["target_gene"])
        if left is None or right is None:
            mouse_unmappable.append(edge)
            continue
        canonical = tuple(sorted((left, right)))
        if canonical in mouse_by_canonical:
            raise ValueError(f"Multiple mouse edges map to the same ortholog pair: {canonical}.")
        mouse_by_canonical[canonical] = edge

    rows: list[dict[str, Any]] = []
    represented_mouse: set[tuple[str, str]] = set()
    for human in human_records:
        source, target = human["_key"]
        mouse_source, mouse_target = h_to_m.get(source), h_to_m.get(target)
        base = {
            "human_source_gene": source,
            "human_target_gene": target,
            "mouse_source_gene": mouse_source,
            "mouse_target_gene": mouse_target,
            "human_weight": human["weight"],
            "mouse_weight": None,
            "human_p_value": human.get("pvalue", human.get("p_value")),
            "mouse_p_value": None,
            "human_adjusted_p_value": human.get("adjusted_p_value"),
            "mouse_adjusted_p_value": None,
            "human_edge_id": human.get("edge_id"),
            "mouse_edge_id": None,
            "weight_difference": None,
            "absolute_weight_difference": None,
            "relative_weight_change": None,
            "edge_classification": "UNMAPPABLE",
            "status": "UNMAPPABLE",
        }
        if mouse_source is None or mouse_target is None:
            rows.append(base)
            continue
        canonical = tuple(sorted((source, target)))
        counterpart = mouse_by_canonical.get(canonical)
        if counterpart is None:
            base["edge_classification"] = "LOST"
            base["status"] = "LOST"
            rows.append(base)
            continue
        represented_mouse.add(canonical)
        difference = float(counterpart["weight"]) - float(human["weight"])
        absolute_difference = abs(difference)
        base.update({
            "mouse_source_gene": counterpart["source_gene"],
            "mouse_target_gene": counterpart["target_gene"],
            "mouse_weight": counterpart["weight"],
            "mouse_p_value": counterpart.get("pvalue", counterpart.get("p_value")),
            "mouse_adjusted_p_value": counterpart.get("adjusted_p_value"),
            "mouse_edge_id": counterpart.get("edge_id"),
            "weight_difference": difference,
            "absolute_weight_difference": absolute_difference,
            "relative_weight_change": difference / abs(float(human["weight"])) if float(human["weight"]) != 0 else None,
            "edge_classification": "REWIRED" if absolute_difference >= rewiring_threshold else "CONSERVED",
            "status": "REWIRED" if absolute_difference >= rewiring_threshold else "CONSERVED",
        })
        rows.append(base)

    for canonical, mouse in mouse_by_canonical.items():
        if canonical in represented_mouse:
            continue
        rows.append({
            "human_source_gene": canonical[0],
            "human_target_gene": canonical[1],
            "mouse_source_gene": mouse["source_gene"],
            "mouse_target_gene": mouse["target_gene"],
            "human_weight": None,
            "mouse_weight": mouse["weight"],
            "human_p_value": None,
            "mouse_p_value": mouse.get("pvalue", mouse.get("p_value")),
            "human_adjusted_p_value": None,
            "mouse_adjusted_p_value": mouse.get("adjusted_p_value"),
            "human_edge_id": None,
            "mouse_edge_id": mouse.get("edge_id"),
            "weight_difference": None,
            "absolute_weight_difference": None,
            "relative_weight_change": None,
            "edge_classification": "SPECIES_SPECIFIC_MOUSE",
            "status": "GAINED",
        })

    for mouse in mouse_unmappable:
        rows.append({
            "human_source_gene": None,
            "human_target_gene": None,
            "mouse_source_gene": mouse["source_gene"],
            "mouse_target_gene": mouse["target_gene"],
            "human_weight": None,
            "mouse_weight": mouse["weight"],
            "human_p_value": None,
            "mouse_p_value": mouse.get("pvalue", mouse.get("p_value")),
            "human_adjusted_p_value": None,
            "mouse_adjusted_p_value": mouse.get("adjusted_p_value"),
            "human_edge_id": None,
            "mouse_edge_id": mouse.get("edge_id"),
            "weight_difference": None,
            "absolute_weight_difference": None,
            "relative_weight_change": None,
            "edge_classification": "UNMAPPABLE",
            "status": "UNMAPPABLE",
        })
    return pd.DataFrame(rows)
