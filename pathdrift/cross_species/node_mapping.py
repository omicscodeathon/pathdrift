from __future__ import annotations

import pandas as pd


def build_node_alignment(
    mappings: pd.DataFrame,
    human_nodes: pd.DataFrame,
    mouse_nodes: pd.DataFrame,
) -> pd.DataFrame:
    human_ids = set(human_nodes["gene_id"].astype(str))
    mouse_ids = set(mouse_nodes["gene_id"].astype(str))
    rows = mappings.copy()
    rows["human_network_present"] = rows["human_ensembl_id"].isin(human_ids)
    rows["mouse_network_present"] = rows["mouse_ensembl_id"].isin(mouse_ids)
    rows["is_primary"] = (
        rows["relationship_cardinality"].eq("one_to_one")
        & rows["orthology_type"].eq("ortholog_one2one")
        & rows["human_network_present"]
        & rows["mouse_network_present"]
    )
    return rows
