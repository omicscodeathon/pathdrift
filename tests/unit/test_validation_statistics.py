import networkx as nx

from app.bio.validation import (
    degree_preserving_network_test,
    edge_turnover,
    node_label_permutation_test,
)


def test_identical_networks_have_zero_edge_turnover():
    graph = nx.cycle_graph(8)

    assert edge_turnover(graph, graph.copy()) == 0.0


def test_node_label_permutation_returns_empirical_p_value():
    healthy = nx.cycle_graph(8)
    disease = nx.path_graph(8)

    result = node_label_permutation_test(healthy, disease, permutations=19, random_seed=7)

    assert result["available"] is True
    assert result["permutations"] == 19
    assert 0 < result["p_value"] <= 1
    assert result["observed"] == edge_turnover(healthy, disease)


def test_degree_preserving_null_reports_actual_replicates():
    healthy = nx.cycle_graph(10)
    disease = nx.path_graph(10)

    result = degree_preserving_network_test(healthy, disease, permutations=5, random_seed=11)

    assert result["available"] is True
    assert result["degree_sequence_preserved"] is True
    assert 1 <= result["permutations"] <= 5
    assert 0 < result["p_value"] <= 1


def test_degree_preserving_null_reports_insufficient_edges():
    result = degree_preserving_network_test(nx.path_graph(3), nx.path_graph(3))

    assert result["available"] is False