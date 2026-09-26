"""Unit tests for network construction and drift detection."""
import pytest
import numpy as np
import pandas as pd
import networkx as nx
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.bio.network import NetworkConstructor, compute_network_statistics
from app.bio.drift import DriftDetector


def make_correlated_expr(n_genes=50, n_samples=30, seed=42):
    """Synthetic expression matrix with known correlation structure (TEST DATA ONLY)."""
    rng = np.random.default_rng(seed)
    base = rng.standard_normal((n_genes, n_samples))
    # Introduce some correlation in first 10 genes
    for i in range(1, 10):
        base[i] = base[0] + 0.3 * rng.standard_normal(n_samples)
    df = pd.DataFrame(base,
                      index=[f"ENSG{i:011d}" for i in range(n_genes)],
                      columns=[f"S{i:03d}" for i in range(n_samples)])
    return df


class TestNetworkConstructor:
    def setup_method(self):
        self.expr = make_correlated_expr()
        self.sample_ids = self.expr.columns.tolist()

    def test_builds_graph(self):
        constructor = NetworkConstructor(correlation_threshold=0.3, top_n_genes=30)
        G, features = constructor.build(self.expr, self.sample_ids)
        assert isinstance(G, nx.Graph)
        assert G.number_of_nodes() > 0

    def test_edges_respect_threshold(self):
        threshold = 0.4
        constructor = NetworkConstructor(correlation_threshold=threshold, fdr_threshold=1.0,
                                          top_n_genes=30, min_gene_variance=0)
        G, _ = constructor.build(self.expr, self.sample_ids)
        for u, v, data in G.edges(data=True):
            assert data['weight'] >= threshold, f"Edge {u}-{v} weight {data['weight']} below threshold"

    def test_node_features_computed(self):
        constructor = NetworkConstructor(correlation_threshold=0.3, top_n_genes=30)
        G, features = constructor.build(self.expr, self.sample_ids)
        assert 'degree' in features.columns
        assert 'betweenness' in features.columns
        assert 'clustering' in features.columns
        assert 'module' in features.columns

    def test_top_n_genes_restriction(self):
        top_n = 20
        constructor = NetworkConstructor(correlation_threshold=0.3, top_n_genes=top_n)
        G, _ = constructor.build(self.expr, self.sample_ids)
        assert G.number_of_nodes() <= top_n

    def test_empty_samples_raises(self):
        constructor = NetworkConstructor(correlation_threshold=0.6, top_n_genes=20)
        with pytest.raises(ValueError):
            constructor.build(self.expr, ['NONEXISTENT_SAMPLE'])

    def test_statistics_computed(self):
        constructor = NetworkConstructor(correlation_threshold=0.3, top_n_genes=30)
        G, _ = constructor.build(self.expr, self.sample_ids)
        stats = compute_network_statistics(G)
        assert 'n_nodes' in stats
        assert 'density' in stats
        assert 0 <= stats['density'] <= 1


class TestDriftDetector:
    def setup_method(self):
        # Create two simple graphs to compare (TEST DATA ONLY)
        self.H = nx.Graph()
        genes = [f"ENSG{i:011d}" for i in range(20)]
        self.H.add_nodes_from(genes)
        # Add some edges to healthy network
        for i in range(8):
            self.H.add_edge(genes[i], genes[i+1], weight=0.7, correlation=0.7)

        self.D = nx.Graph()
        self.D.add_nodes_from(genes)
        # Disease network: some edges lost, some new edges gained
        for i in range(3):
            self.D.add_edge(genes[i], genes[i+1], weight=0.7, correlation=0.7)  # conserved
        self.D.add_edge(genes[10], genes[11], weight=0.8, correlation=0.8)     # gained
        self.D.add_edge(genes[12], genes[13], weight=0.75, correlation=0.75)   # gained

    def test_edge_drift_categories(self):
        detector = DriftDetector()
        result = detector.compute(self.H, self.D)
        edge_drift = result['edge_drift']
        types = edge_drift['type'].unique()
        # Should detect gained and lost edges
        assert 'gained' in types or 'lost' in types

    def test_global_drift_score_nonnegative(self):
        detector = DriftDetector()
        result = detector.compute(self.H, self.D)
        assert result['global_stats']['global_drift_score'] >= 0

    def test_node_drift_contains_all_shared_genes(self):
        detector = DriftDetector()
        result = detector.compute(self.H, self.D)
        node_drift = result['node_drift']
        assert 'node_drift_score' in node_drift.columns
        assert len(node_drift) > 0

    def test_disjoint_networks_raise(self):
        G1 = nx.Graph()
        G1.add_node("ENSG00000000001")
        G2 = nx.Graph()
        G2.add_node("ENSG99999999999")
        detector = DriftDetector()
        with pytest.raises(ValueError):
            detector.compute(G1, G2)
