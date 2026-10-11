"""
Gene Network Construction Engine

Builds weighted gene co-expression networks from expression matrices.
Networks are constructed separately for each biological state (healthy/disease)
using only the samples from that state.

Supports:
  - Pearson correlation
  - Spearman correlation
  - FDR correction for correlations
  - Top-N gene selection (by variance)
  - Module detection via Louvain community detection

Network topology metrics calculated per node:
  - degree
  - weighted degree (strength)
  - betweenness centrality
  - closeness centrality
  - clustering coefficient
  - hub score (normalised degree)
"""
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import spearmanr, pearsonr
from statsmodels.stats.multitest import multipletests
import networkx as nx
import structlog
from typing import Optional, Tuple, Dict, List

logger = structlog.get_logger(__name__)


class NetworkConstructor:
    """
    Construct a weighted gene co-expression network for a given set of samples.

    Parameters
    ----------
    correlation_method : str
        'pearson' or 'spearman'
    correlation_threshold : float
        Minimum |correlation| for an edge to be included (0 < threshold <= 1)
    fdr_threshold : float
        Maximum adjusted p-value for an edge (applied to correlation p-values)
    top_n_genes : int or None
        If set, restrict to top N genes by expression variance before building network.
    min_gene_variance : float
        Minimum gene variance; genes below threshold are excluded.
    """

    def __init__(
        self,
        correlation_method: str = "pearson",
        correlation_threshold: float = 0.6,
        fdr_threshold: float = 0.05,
        top_n_genes: Optional[int] = None,
        min_gene_variance: float = 0.1,
        random_seed: int = 42,
    ):
        self.correlation_method = correlation_method
        self.correlation_threshold = correlation_threshold
        self.fdr_threshold = fdr_threshold
        self.top_n_genes = top_n_genes
        self.min_gene_variance = min_gene_variance
        self.random_seed = random_seed

    def build(
        self,
        expr_df: pd.DataFrame,
        sample_ids: List[str],
    ) -> Tuple[nx.Graph, pd.DataFrame]:
        """
        Build a network for the specified samples.

        Parameters
        ----------
        expr_df : pd.DataFrame
            Preprocessed expression matrix (genes × samples), log2-normalized.
        sample_ids : list[str]
            Column names identifying the samples to use for this network.

        Returns
        -------
        G : nx.Graph
            Weighted undirected graph. Edge weight = |correlation|.
        node_features : pd.DataFrame
            Per-node topology metrics.
        """
        # Select samples
        missing = set(sample_ids) - set(expr_df.columns)
        if missing:
            raise ValueError(f"Samples not in expression matrix: {missing}")
        sub = expr_df[sample_ids].copy()

        logger.info(
            "network_construction_starting",
            n_genes=sub.shape[0],
            n_samples=sub.shape[1],
            method=self.correlation_method,
        )

        # Filter low-variance genes
        gene_vars = sub.var(axis=1)
        sub = sub.loc[gene_vars >= self.min_gene_variance]
        if sub.shape[0] == 0:
            raise ValueError("No genes remain after variance filter. Reduce min_gene_variance.")

        # Optionally restrict to top-N genes by variance
        if self.top_n_genes and sub.shape[0] > self.top_n_genes:
            top_genes = sub.var(axis=1).nlargest(self.top_n_genes).index
            sub = sub.loc[top_genes]

        logger.info("network_genes_selected", n_genes=sub.shape[0])

        # Compute correlation matrix
        corr_matrix, pval_matrix = self._compute_correlations(sub)

        # Apply FDR correction to p-values
        adj_pval_matrix = self._fdr_correct_matrix(pval_matrix)

        # Build NetworkX graph
        G = self._build_graph(corr_matrix, adj_pval_matrix, sub.index.tolist())

        # Compute node features
        node_features = self._compute_node_features(G)

        # Detect modules (communities)
        modules = self._detect_modules(G)
        node_features["module"] = node_features.index.map(modules).fillna("M0")

        logger.info(
            "network_construction_done",
            n_nodes=G.number_of_nodes(),
            n_edges=G.number_of_edges(),
            density=nx.density(G) if G.number_of_nodes() > 1 else 0,
        )
        return G, node_features

    def _compute_correlations(
        self, expr_df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        genes = expr_df.index.tolist()
        n = len(genes)
        X = expr_df.values  # genes × samples

        corr = np.zeros((n, n))
        pvals = np.ones((n, n))

        if self.correlation_method == "pearson":
            for i in range(n):
                if i and i % 25 == 0:
                    logger.info("network_correlation_progress", genes_processed=i, total_genes=n, n_samples=X.shape[1])
                for j in range(i + 1, n):
                    if np.std(X[i]) == 0 or np.std(X[j]) == 0:
                        continue
                    r, p = pearsonr(X[i], X[j])
                    corr[i, j] = corr[j, i] = r
                    pvals[i, j] = pvals[j, i] = p
        elif self.correlation_method == "spearman":
            for i in range(n):
                if i and i % 25 == 0:
                    logger.info("network_correlation_progress", genes_processed=i, total_genes=n, n_samples=X.shape[1])
                for j in range(i + 1, n):
                    r, p = spearmanr(X[i], X[j])
                    corr[i, j] = corr[j, i] = r
                    pvals[i, j] = pvals[j, i] = p
        else:
            raise ValueError(f"Unknown correlation method: {self.correlation_method}")

        corr_df = pd.DataFrame(corr, index=genes, columns=genes)
        pval_df = pd.DataFrame(pvals, index=genes, columns=genes)
        return corr_df, pval_df

    @staticmethod
    def _fdr_correct_matrix(pval_df: pd.DataFrame) -> pd.DataFrame:
        """Apply BH FDR correction to the upper triangle of the p-value matrix."""
        n = pval_df.shape[0]
        idx_i, idx_j = np.triu_indices(n, k=1)
        pvals_flat = pval_df.values[idx_i, idx_j]

        _, padj_flat, _, _ = multipletests(pvals_flat, method="fdr_bh")

        adj_matrix = np.ones((n, n))
        adj_matrix[idx_i, idx_j] = padj_flat
        adj_matrix[idx_j, idx_i] = padj_flat
        return pd.DataFrame(adj_matrix, index=pval_df.index, columns=pval_df.columns)

    def _build_graph(
        self,
        corr_df: pd.DataFrame,
        adj_pval_df: pd.DataFrame,
        genes: List[str],
    ) -> nx.Graph:
        G = nx.Graph()
        G.add_nodes_from(genes)

        n = len(genes)
        for i in range(n):
            for j in range(i + 1, n):
                r = corr_df.iloc[i, j]
                p = adj_pval_df.iloc[i, j]
                if abs(r) >= self.correlation_threshold and p <= self.fdr_threshold:
                    G.add_edge(genes[i], genes[j], weight=abs(r), correlation=r)

        return G

    @staticmethod
    def _compute_node_features(G: nx.Graph) -> pd.DataFrame:
        if G.number_of_nodes() == 0:
            return pd.DataFrame()

        nodes = list(G.nodes())
        degree = dict(G.degree())
        weighted_degree = dict(G.degree(weight="weight"))

        if G.number_of_nodes() > 1 and G.number_of_edges() > 0:
            betweenness = nx.betweenness_centrality(G, weight="weight", normalized=True)
            closeness = nx.closeness_centrality(G)
            clustering = nx.clustering(G, weight="weight")
        else:
            betweenness = {n: 0.0 for n in nodes}
            closeness = {n: 0.0 for n in nodes}
            clustering = {n: 0.0 for n in nodes}

        features = pd.DataFrame(
            {
                "gene_id": nodes,
                "degree": [degree[n] for n in nodes],
                "weighted_degree": [weighted_degree[n] for n in nodes],
                "betweenness": [betweenness[n] for n in nodes],
                "closeness": [closeness[n] for n in nodes],
                "clustering": [clustering[n] for n in nodes],
            }
        ).set_index("gene_id")

        return features

    def _detect_modules(self, G: nx.Graph) -> Dict[str, str]:
        """Louvain community detection. Returns {gene_id: module_id}."""
        if G.number_of_edges() == 0:
            return {n: "M0" for n in G.nodes()}
        try:
            import community as community_louvain
            partition = community_louvain.best_partition(G, weight="weight", random_state=self.random_seed)
            return {gene: f"M{mod}" for gene, mod in partition.items()}
        except ImportError:
            # Fall back to greedy modularity
            try:
                communities = nx.community.greedy_modularity_communities(G, weight="weight")
                module_map = {}
                for i, comm in enumerate(communities):
                    for gene in comm:
                        module_map[gene] = f"M{i}"
                return module_map
            except Exception:
                return {n: "M0" for n in G.nodes()}


def compute_network_statistics(G: nx.Graph) -> Dict:
    """Compute global network statistics."""
    if G.number_of_nodes() == 0:
        return {}
    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()
    return {
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "density": nx.density(G),
        "avg_clustering": nx.average_clustering(G, weight="weight") if n_edges > 0 else 0.0,
        "avg_degree": (2 * n_edges / n_nodes) if n_nodes > 0 else 0.0,
        "is_connected": nx.is_connected(G),
        "n_connected_components": nx.number_connected_components(G),
    }
