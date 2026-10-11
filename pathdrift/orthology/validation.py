from __future__ import annotations

import pandas as pd

from .mapping import primary_one_to_one


def validate_orthology(
    mappings: pd.DataFrame,
    human_network_genes: set[str],
    mouse_network_genes: set[str],
    min_confidence: float = 1.0,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    primary = primary_one_to_one(mappings, min_confidence)
    mapped_human = set(mappings["human_ensembl_id"])
    mapped_mouse = set(mappings["mouse_ensembl_id"])
    primary_human = set(primary["human_ensembl_id"])
    primary_mouse = set(primary["mouse_ensembl_id"])
    summary = {
        "total_orthology_mappings": int(len(mappings)),
        "unique_human_genes_mapped": int(mappings["human_ensembl_id"].nunique()),
        "unique_mouse_genes_mapped": int(mappings["mouse_ensembl_id"].nunique()),
        "one_to_one_mappings": int((mappings["relationship_cardinality"] == "one_to_one").sum()),
        "one_to_many_mappings": int((mappings["relationship_cardinality"] == "one_to_many").sum()),
        "many_to_one_mappings": int((mappings["relationship_cardinality"] == "many_to_one").sum()),
        "many_to_many_mappings": int((mappings["relationship_cardinality"] == "many_to_many").sum()),
        "primary_one_to_one_mappings": int(len(primary)),
        "human_network_genes": len(human_network_genes),
        "mouse_network_genes": len(mouse_network_genes),
        "human_network_genes_with_orthologs": len(human_network_genes & primary_human),
        "mouse_network_genes_with_orthologs": len(mouse_network_genes & primary_mouse),
    }
    summary["unmapped_human_network_genes"] = len(human_network_genes - mapped_human)
    summary["unmapped_mouse_network_genes"] = len(mouse_network_genes - mapped_mouse)
    unmapped_human = pd.DataFrame({"gene_id": sorted(human_network_genes - mapped_human)})
    unmapped_mouse = pd.DataFrame({"gene_id": sorted(mouse_network_genes - mapped_mouse)})
    return summary, unmapped_human, unmapped_mouse
