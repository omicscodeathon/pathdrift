from __future__ import annotations

from typing import Any


CONFIDENCE_THRESHOLDS = {
    "high": 0.700,
    "medium": 0.400,
    "all": 0.0,
}


def normalize_string_network(
    seed: dict[str, Any],
    interactions: list[dict[str, Any]],
    confidence: str,
) -> dict[str, Any]:
    """Normalize STRING physical interactions and apply the selected score threshold."""
    if confidence not in CONFIDENCE_THRESHOLDS:
        raise ValueError(f"Unsupported STRING confidence level: {confidence}")

    threshold = CONFIDENCE_THRESHOLDS[confidence]
    nodes: dict[str, dict[str, Any]] = {}
    seed_id = str(seed["string_id"])
    nodes[seed_id] = {
        "string_id": seed_id,
        "preferred_name": str(seed.get("preferred_name") or seed.get("query") or seed_id),
        "is_query": True,
    }

    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    for interaction in interactions:
        try:
            score = float(interaction["score"])
            string_id_a = str(interaction["stringId_A"])
            string_id_b = str(interaction["stringId_B"])
        except (KeyError, TypeError, ValueError):
            continue
        if score < threshold or string_id_a == string_id_b:
            continue

        preferred_name_a = str(interaction.get("preferredName_A") or string_id_a)
        preferred_name_b = str(interaction.get("preferredName_B") or string_id_b)
        nodes.setdefault(string_id_a, {"string_id": string_id_a, "preferred_name": preferred_name_a, "is_query": string_id_a == seed_id})
        nodes.setdefault(string_id_b, {"string_id": string_id_b, "preferred_name": preferred_name_b, "is_query": string_id_b == seed_id})
        edge_key = tuple(sorted((string_id_a, string_id_b)))
        edge_map[edge_key] = {
            "protein_a": string_id_a,
            "protein_b": string_id_b,
            "preferred_name_a": preferred_name_a,
            "preferred_name_b": preferred_name_b,
            "score": score,
            "experimental_score": float(interaction.get("escore") or 0),
            "database_score": float(interaction.get("dscore") or 0),
        }

    edges = sorted(edge_map.values(), key=lambda edge: (-edge["score"], edge["protein_a"], edge["protein_b"]))
    return {
        "seed": nodes[seed_id],
        "confidence": confidence,
        "minimum_score": threshold,
        "nodes": sorted(nodes.values(), key=lambda node: (not node["is_query"], node["preferred_name"].casefold())),
        "interactions": edges,
        "node_count": len(nodes),
        "interaction_count": len(edges),
    }