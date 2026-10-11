from __future__ import annotations

import networkx as nx
import numpy as np
from collections import Counter


def network_statistics(graph: nx.Graph, *, method: str, filtering: dict) -> dict:
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    degree_counts = Counter(degree for _, degree in graph.degree())
    degrees = list(degree_counts.elements())
    components = list(nx.connected_components(graph))
    edge_weights = [float(data["weight"]) for _, _, data in graph.edges(data=True)]
    return {
        "n_nodes": node_count,
        "n_edges": edge_count,
        "density": float(nx.density(graph)) if node_count > 1 else 0.0,
        "average_degree": float(np.mean(degrees)) if degrees else 0.0,
        "degree_distribution": {str(degree): int(degree_counts[degree]) for degree in sorted(degree_counts)},
        "average_clustering": float(nx.average_clustering(graph, weight="weight")) if edge_count else 0.0,
        "connected_components": len(components),
        "largest_component_size": max((len(component) for component in components), default=0),
        "average_absolute_edge_weight": float(np.mean(edge_weights)) if edge_weights else None,
        "method": method,
        "filtering": filtering,
    }
