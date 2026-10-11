from __future__ import annotations

import math

import pandas as pd


def network_conservation_summary(
    human_nodes: pd.DataFrame,
    mouse_nodes: pd.DataFrame,
    primary_mapping: pd.DataFrame,
    edge_alignment: pd.DataFrame,
) -> dict:
    statuses = edge_alignment["status"].value_counts().to_dict()
    human_set = set(human_nodes["gene_id"].astype(str))
    mouse_set = set(mouse_nodes["gene_id"].astype(str))
    h_to_m = dict(zip(primary_mapping["human_ensembl_id"], primary_mapping["mouse_ensembl_id"]))
    mapped_human = human_set.intersection(h_to_m)
    mapped_mouse = mouse_set.intersection(set(h_to_m.values()))
    shared = {gene for gene in mapped_human if h_to_m[gene] in mouse_set}
    mouse_to_h = {mouse: human for human, mouse in h_to_m.items()}
    shared_mouse = {mouse for mouse in mapped_mouse if mouse_to_h[mouse] in human_set}
    total_human_edges = int(edge_alignment["human_edge_id"].notna().sum())
    mappable_human_edges = int(edge_alignment.loc[edge_alignment["human_edge_id"].notna(), "status"].ne("UNMAPPABLE").sum())
    conserved = int(statuses.get("CONSERVED", 0))
    lost = int(statuses.get("LOST", 0))
    gained = int(statuses.get("GAINED", 0))
    unmappable = int(statuses.get("UNMAPPABLE", 0))
    return {
        "human_nodes": len(human_set),
        "mouse_nodes": len(mouse_set),
        "ortholog_mapped_human_network_nodes": len(mapped_human),
        "ortholog_mapped_mouse_network_nodes": len(mapped_mouse),
        "shared_network_nodes": len(shared),
        "human_only_nodes": len(human_set - shared),
        "mouse_only_nodes": len(mouse_set - shared_mouse),
        "total_human_edges": total_human_edges,
        "total_mouse_edges": int(edge_alignment["mouse_edge_id"].notna().sum()),
        "mapped_human_edges": mappable_human_edges,
        "conserved_edges": conserved,
        "lost_edges": lost,
        "unmappable_edges": unmappable,
        "gained_edges": gained,
        "species_specific_mouse_edges": int((edge_alignment["edge_classification"] == "SPECIES_SPECIFIC_MOUSE").sum()),
        "rewired_edges": int(statuses.get("REWIRED", 0)),
        "edge_conservation_rate": conserved / mappable_human_edges if mappable_human_edges else None,
        "edge_loss_rate": lost / mappable_human_edges if mappable_human_edges else None,
        "edge_gain_rate": gained / (gained + conserved + lost + int(statuses.get("REWIRED", 0)))
        if gained + conserved + lost + int(statuses.get("REWIRED", 0)) else None,
    }
