"""Statistical null models for validating observed network drift."""
import networkx as nx
import numpy as np


def edge_turnover(healthy: nx.Graph, disease: nx.Graph) -> float:
    """Return one minus edge-set Jaccard similarity on shared nodes."""
    shared_nodes = set(healthy.nodes()) & set(disease.nodes())
    healthy_edges = {
        frozenset(edge)
        for edge in healthy.subgraph(shared_nodes).edges()
    }
    disease_edges = {
        frozenset(edge)
        for edge in disease.subgraph(shared_nodes).edges()
    }
    union_size = len(healthy_edges | disease_edges)
    if not union_size:
        return 0.0
    return 1.0 - len(healthy_edges & disease_edges) / union_size


def node_label_permutation_test(
    healthy: nx.Graph,
    disease: nx.Graph,
    permutations: int = 199,
    random_seed: int = 42,
) -> dict:
    """Test whether observed edge turnover exceeds random gene correspondence."""
    shared_nodes = sorted(set(healthy.nodes()) & set(disease.nodes()))
    if len(shared_nodes) < 2:
        return {"available": False, "reason": "Fewer than two shared network nodes."}

    healthy_shared = healthy.subgraph(shared_nodes)
    disease_shared = disease.subgraph(shared_nodes)
    observed = edge_turnover(healthy_shared, disease_shared)
    rng = np.random.default_rng(random_seed)
    null_scores = []

    for _ in range(permutations):
        shuffled_nodes = rng.permutation(shared_nodes)
        relabel = dict(zip(shared_nodes, shuffled_nodes))
        permuted_disease = nx.relabel_nodes(disease_shared, relabel, copy=True)
        null_scores.append(edge_turnover(healthy_shared, permuted_disease))

    return {
        "available": True,
        "method": "gene-label permutation; network topology and edge weights preserved",
        "statistic": "edge turnover (1 - edge Jaccard similarity)",
        "observed": observed,
        "null_mean": float(np.mean(null_scores)),
        "null_std": float(np.std(null_scores, ddof=1)) if len(null_scores) > 1 else 0.0,
        "p_value": (1 + sum(score >= observed for score in null_scores)) / (len(null_scores) + 1),
        "permutations": len(null_scores),
        "shared_nodes": len(shared_nodes),
    }


def degree_preserving_network_test(
    healthy: nx.Graph,
    disease: nx.Graph,
    permutations: int = 99,
    random_seed: int = 42,
) -> dict:
    """Compare observed edge turnover to degree-preserving rewired networks."""
    shared_nodes = sorted(set(healthy.nodes()) & set(disease.nodes()))
    healthy_shared = healthy.subgraph(shared_nodes)
    disease_shared = disease.subgraph(shared_nodes)
    if healthy_shared.number_of_edges() < 3 or disease_shared.number_of_edges() < 3:
        return {"available": False, "reason": "Each network needs at least three shared-node edges."}

    observed = edge_turnover(healthy_shared, disease_shared)
    null_scores = []
    rng = np.random.default_rng(random_seed)
    swap_count = min(1000, max(1, healthy_shared.number_of_edges()), max(1, disease_shared.number_of_edges()))

    for _ in range(permutations):
        rewired_healthy = healthy_shared.copy()
        rewired_disease = disease_shared.copy()
        try:
            nx.double_edge_swap(
                rewired_healthy,
                nswap=swap_count,
                max_tries=max(20, swap_count * 20),
                seed=int(rng.integers(0, 2**32 - 1)),
            )
            nx.double_edge_swap(
                rewired_disease,
                nswap=swap_count,
                max_tries=max(20, swap_count * 20),
                seed=int(rng.integers(0, 2**32 - 1)),
            )
        except nx.NetworkXAlgorithmError:
            continue
        null_scores.append(edge_turnover(rewired_healthy, rewired_disease))

    if not null_scores:
        return {"available": False, "reason": "Degree-preserving swaps were not possible for these networks."}

    return {
        "available": True,
        "method": "independent degree-preserving double-edge swaps",
        "statistic": "edge turnover (1 - edge Jaccard similarity)",
        "observed": observed,
        "null_mean": float(np.mean(null_scores)),
        "null_std": float(np.std(null_scores, ddof=1)) if len(null_scores) > 1 else 0.0,
        "p_value": (1 + sum(score >= observed for score in null_scores)) / (len(null_scores) + 1),
        "permutations": len(null_scores),
        "degree_sequence_preserved": True,
    }