from __future__ import annotations

import networkx as nx
import pandas as pd


def detect_modules(
    graph: nx.Graph,
    *,
    method: str,
    resolution: float,
    min_module_size: int,
    seed: int,
    nodes: pd.DataFrame,
    deg_results: pd.DataFrame | None = None,
) -> dict:
    if method != "louvain":
        raise ValueError("Only the configured NetworkX Louvain community method is currently supported.")
    if resolution <= 0 or min_module_size < 2:
        raise ValueError("Module resolution must be positive and min_module_size must be at least 2.")
    if graph.number_of_edges():
        communities = nx.community.louvain_communities(
            graph,
            weight="weight",
            resolution=resolution,
            seed=seed,
        )
    else:
        communities = []
    communities = sorted(communities, key=lambda group: min(map(str, group)))
    accepted = [
        sorted(map(str, community))
        for community in communities
        if len(community) >= min_module_size
    ]
    membership: dict[str, str] = {
        gene: f"module_{index:04d}"
        for index, group in enumerate(accepted, start=1)
        for gene in group
    }
    node_table = nodes.copy()
    node_table["gene_id"] = node_table["gene_id"].astype(str)
    node_table["module_id"] = node_table["gene_id"].map(membership)

    deg = deg_results
    deg_by_gene = {}
    deg_available = deg is not None and not deg.empty
    if deg_available:
        deg_by_gene = deg.set_index(deg["gene_id"].astype(str)).to_dict(orient="index")
    module_rows = []
    gene_rows = []
    for index, members in enumerate(accepted, start=1):
        module_id = f"module_{index:04d}"
        subgraph = graph.subgraph(members)
        member_features = node_table[node_table["gene_id"].isin(members)].copy()
        central = member_features.sort_values(
            ["weighted_degree", "degree", "gene_id"],
            ascending=[False, False, True],
        )
        member_degs = [deg_by_gene[gene] for gene in members if gene in deg_by_gene]
        sig_degs = [row for row in member_degs if bool(row.get("significant"))]
        up = sum(row.get("direction") == "UPREGULATED" for row in sig_degs)
        down = sum(row.get("direction") == "DOWNREGULATED" for row in sig_degs)
        module_rows.append({
            "module_id": module_id,
            "size": len(members),
            "internal_edges": subgraph.number_of_edges(),
            "density": float(nx.density(subgraph)) if len(members) > 1 else 0.0,
            "average_degree": float(sum(dict(subgraph.degree()).values()) / len(members)),
            "average_internal_edge_weight": (
                float(sum(data["weight"] for _, _, data in subgraph.edges(data=True)) / subgraph.number_of_edges())
                if subgraph.number_of_edges() else None
            ),
            "deg_gene_count": len(sig_degs) if deg_available else None,
            "deg_gene_percent": 100.0 * len(sig_degs) / len(members) if deg_available else None,
            "upregulated_deg_count": int(up) if deg_available else None,
            "downregulated_deg_count": int(down) if deg_available else None,
            "non_deg_gene_count": len(members) - len(sig_degs) if deg_available else None,
            "top_central_genes": central["gene_id"].head(10).tolist(),
            "detection_method": "NetworkX Louvain",
            "resolution": float(resolution),
            "min_module_size": int(min_module_size),
        })
        for gene in members:
            row = {"module_id": module_id, "gene_id": gene}
            if gene in deg_by_gene:
                result = deg_by_gene[gene]
                row.update({
                    "log2fc": result.get("log2fc"),
                    "adjusted_p_value": result.get("adjusted_p_value"),
                    "significant": bool(result.get("significant")),
                    "direction": result.get("direction"),
                })
            else:
                row.update({
                    "log2fc": None,
                    "adjusted_p_value": None,
                    "significant": False if deg_available else None,
                    "direction": None,
                })
            gene_rows.append(row)
    modularity = (
        float(nx.community.modularity(graph, communities, weight="weight", resolution=resolution))
        if communities and graph.number_of_edges() else None
    )
    modules = pd.DataFrame(module_rows, columns=[
        "module_id", "size", "internal_edges", "density", "average_degree",
        "average_internal_edge_weight", "deg_gene_count", "deg_gene_percent", "upregulated_deg_count",
        "downregulated_deg_count", "non_deg_gene_count", "top_central_genes",
        "detection_method", "resolution", "min_module_size",
    ])
    genes = pd.DataFrame(gene_rows, columns=[
        "module_id", "gene_id", "log2fc", "adjusted_p_value", "significant", "direction",
    ])
    return {
        "modules": modules,
        "genes": genes,
        "nodes": node_table,
        "summary": {
            "detection_method": "NetworkX Louvain",
            "resolution": float(resolution),
            "min_module_size": int(min_module_size),
            "communities_detected": len(communities),
            "modules_retained": len(accepted),
            "genes_in_retained_modules": len(membership),
            "deg_comparison_available": deg_available,
            "modularity_including_small_communities": modularity,
        },
    }
