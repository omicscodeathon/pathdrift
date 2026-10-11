from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from .centrality import node_features
from .correlation import correlation_edges
from .filtering import select_network_genes
from .statistics import network_statistics
from ..differential_expression.validation import IDENTIFIER_PATTERNS


def construct_network(
    expression: pd.DataFrame,
    *,
    species: str,
    method: str,
    min_abs_correlation: float,
    max_adjusted_p_value: float,
    min_gene_variance: float,
    max_genes: int,
    seed: int,
    centrality_sample_count: int = 8,
) -> dict:
    if expression.empty or expression.columns.has_duplicates or expression.index.has_duplicates:
        raise ValueError("Network expression must have genes and samples with unique identifiers.")
    pattern = IDENTIFIER_PATTERNS.get(species.casefold())
    if pattern is None:
        raise ValueError(f"Unsupported species for network gene validation: {species!r}.")
    invalid = [str(gene) for gene in expression.index if not pattern.fullmatch(str(gene))]
    if invalid:
        raise ValueError(
            f"Network input contains {len(invalid)} non-{species} Ensembl gene identifiers; "
            f"examples: {invalid[:5]}"
        )
    expression = expression.apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(expression.to_numpy(dtype=float, copy=False)).all():
        raise ValueError("Network expression contains missing or non-finite values.")
    filtered, filtering = select_network_genes(
        expression,
        min_variance=min_gene_variance,
        max_genes=max_genes,
    )
    edges, correlation_info = correlation_edges(
        filtered,
        method=method,
        min_abs_correlation=min_abs_correlation,
        max_adjusted_p_value=max_adjusted_p_value,
    )
    graph = nx.Graph()
    graph.add_nodes_from(filtered.index.astype(str))
    for edge in edges.to_dict(orient="records"):
        graph.add_edge(
            edge["source_gene"],
            edge["target_gene"],
            weight=edge["weight"],
            distance=max(1e-12, 1.0 - edge["absolute_correlation"]),
            correlation=edge["correlation"],
            p_value=edge["p_value"],
            adjusted_p_value=edge["adjusted_p_value"],
        )
    filtering.update({
        "genes_after_zero_variance_removal": len(filtered),
        "correlation": correlation_info,
    })
    features = node_features(
        graph,
        seed=seed,
        centrality_sample_count=centrality_sample_count,
    )
    summary = network_statistics(graph, method=method, filtering=filtering)
    summary["top_central_genes"] = (
        features.sort_values(
            ["weighted_degree", "betweenness_centrality", "gene_id"],
            ascending=[False, False, True],
        )["gene_id"].head(10).tolist()
    )
    summary["centrality"] = {
        "betweenness": "NetworkX Brandes centrality; sampled deterministically when graph exceeds sample count",
        "betweenness_sample_count": int(min(len(graph), max(1, centrality_sample_count))),
        "closeness": (
            "Deterministic landmark approximation using 1 - absolute-correlation distance"
            if len(graph) > 1000
            else "NetworkX closeness centrality using 1 - absolute-correlation distance"
        ),
        "closeness_landmark_count": (
            int(min(len(graph), max(1, centrality_sample_count)))
            if len(graph) > 1000 else None
        ),
        "eigenvector": "NetworkX weighted eigenvector centrality; convergence failure is recorded as null",
    }
    return {
        "graph": graph,
        "edges": edges,
        "nodes": features,
        "summary": summary,
        "expression": filtered,
    }
