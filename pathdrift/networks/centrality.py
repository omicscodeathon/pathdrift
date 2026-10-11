from __future__ import annotations

import numpy as np
import networkx as nx
import pandas as pd


def _landmark_closeness(
    graph: nx.Graph,
    nodes: list[str],
    *,
    sample_count: int,
    seed: int,
) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    selected = rng.choice(nodes, size=min(len(nodes), sample_count), replace=False).tolist()
    sampled = set(selected)
    distance_sums = dict.fromkeys(nodes, 0.0)
    landmark_counts = dict.fromkeys(nodes, 0)
    for source in selected:
        for target, distance in nx.single_source_dijkstra_path_length(
            graph,
            source,
            weight="distance",
        ).items():
            distance_sums[target] += distance
            landmark_counts[target] += 1

    total_nodes = len(nodes)
    values: dict[str, float] = {}
    for component in nx.connected_components(graph):
        component_size = len(component)
        for node in component:
            if component_size <= 1:
                values[node] = 0.0
                continue
            count = landmark_counts[node] - int(node in sampled)
            if count <= 0:
                values[node] = 0.0
                continue
            mean_distance = distance_sums[node] / count
            values[node] = (
                (component_size - 1) / ((total_nodes - 1) * mean_distance)
                if mean_distance > 0 else 0.0
            )
    return values


def node_features(graph: nx.Graph, *, seed: int, centrality_sample_count: int) -> pd.DataFrame:
    nodes = list(graph.nodes())
    degree = dict(graph.degree())
    strength = dict(graph.degree(weight="weight"))
    if graph.number_of_edges():
        sample_count = min(len(nodes), max(1, centrality_sample_count))
        betweenness = nx.betweenness_centrality(
            graph,
            k=sample_count if sample_count < len(nodes) else None,
            weight="distance",
            seed=seed,
        )
        if len(nodes) > 1000:
            closeness = _landmark_closeness(
                graph,
                nodes,
                sample_count=sample_count,
                seed=seed,
            )
        else:
            closeness = nx.closeness_centrality(graph, distance="distance")
        try:
            eigenvector = nx.eigenvector_centrality(graph, max_iter=1000, weight="weight")
        except nx.PowerIterationFailedConvergence:
            eigenvector = {node: None for node in nodes}
    else:
        betweenness = {node: 0.0 for node in nodes}
        closeness = {node: 0.0 for node in nodes}
        eigenvector = {node: 0.0 for node in nodes}
    return pd.DataFrame([
        {
            "gene_id": node,
            "degree": int(degree[node]),
            "weighted_degree": float(strength[node]),
            "betweenness_centrality": betweenness[node],
            "closeness_centrality": closeness[node],
            "eigenvector_centrality": eigenvector[node],
            "module_id": None,
        }
        for node in nodes
    ])
