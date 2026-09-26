"""
Network Drift Detection Engine

Central component of PathDrift.

Given a healthy network and a disease network (same species, same gene space),
computes:

Edge-level drift:
  - Edges gained in disease (not present in healthy)
  - Edges lost in disease (present in healthy, absent in disease)
  - Edges with increased weight (strengthened interaction)
  - Edges with decreased weight (weakened interaction)

Node-level drift:
  - Degree change (Δdegree)
  - Weighted degree change (Δstrength)
  - Betweenness centrality change
  - Closeness centrality change
  - Clustering coefficient change
  - Node Drift Score (NDS): composite quantitative score

Module-level drift:
  - Module preservation (Jaccard similarity of membership)
  - Module disruption score
  - Connectivity change within module

Global Network Drift Score (GNDS):
  - Normalised sum of edge changes weighted by correlation magnitude
  - Documented formula; configurable weighting

All results are returned as DataFrames that can be stored as Parquet files.
"""
import numpy as np
import pandas as pd
import networkx as nx
import structlog
from typing import Optional, Dict, List, Tuple, Set

logger = structlog.get_logger(__name__)

# Weights for the composite Node Drift Score
NODE_DRIFT_WEIGHTS = {
    "degree_change_norm": 0.25,
    "betweenness_change_norm": 0.25,
    "closeness_change_norm": 0.25,
    "clustering_change_norm": 0.25,
}


class DriftDetector:
    """
    Computes network drift between a healthy and a disease gene network.

    Parameters
    ----------
    weight_threshold : float
        Minimum edge-weight change magnitude to count as a significant change.
    """

    def __init__(self, weight_threshold: float = 0.1):
        self.weight_threshold = weight_threshold

    def compute(
        self,
        healthy_G: nx.Graph,
        disease_G: nx.Graph,
    ) -> Dict:
        """
        Compare healthy and disease networks.

        Returns
        -------
        dict with keys:
            'edge_drift'    : pd.DataFrame
            'node_drift'    : pd.DataFrame
            'module_drift'  : pd.DataFrame
            'global_stats'  : dict
        """
        logger.info(
            "drift_computation_starting",
            healthy_nodes=healthy_G.number_of_nodes(),
            disease_nodes=disease_G.number_of_nodes(),
        )

        shared_genes = set(healthy_G.nodes()) & set(disease_G.nodes())
        if not shared_genes:
            raise ValueError(
                "No genes shared between healthy and disease networks. "
                "Ensure both networks were built from the same dataset."
            )

        # Restrict both graphs to shared genes for fair comparison
        H = healthy_G.subgraph(shared_genes).copy()
        D = disease_G.subgraph(shared_genes).copy()

        edge_drift = self._compute_edge_drift(H, D)
        node_drift = self._compute_node_drift(H, D, shared_genes)
        module_drift = self._compute_module_drift(H, D)
        global_stats = self._compute_global_drift_score(H, D, edge_drift)

        logger.info(
            "drift_computation_done",
            n_gained=int((edge_drift["type"] == "gained").sum()),
            n_lost=int((edge_drift["type"] == "lost").sum()),
            global_drift_score=global_stats["global_drift_score"],
        )

        return {
            "edge_drift": edge_drift,
            "node_drift": node_drift,
            "module_drift": module_drift,
            "global_stats": global_stats,
        }

    @staticmethod
    def _compute_edge_drift(H: nx.Graph, D: nx.Graph) -> pd.DataFrame:
        """
        Edge-level drift analysis.

        Edge types:
          'gained'    — present in D, absent in H
          'lost'      — present in H, absent in D
          'conserved' — present in both, similar weight
          'increased' — present in both, weight higher in D
          'decreased' — present in both, weight lower in D
        """
        rows = []
        h_edges = {frozenset((u, v)): d.get("weight", 0.0) for u, v, d in H.edges(data=True)}
        d_edges = {frozenset((u, v)): d.get("weight", 0.0) for u, v, d in D.edges(data=True)}

        all_edge_sets = set(h_edges.keys()) | set(d_edges.keys())

        for edge_set in all_edge_sets:
            g1, g2 = tuple(edge_set)
            w_h = h_edges.get(edge_set, 0.0)
            w_d = d_edges.get(edge_set, 0.0)
            delta_w = w_d - w_h

            if edge_set not in h_edges:
                etype = "gained"
            elif edge_set not in d_edges:
                etype = "lost"
            elif abs(delta_w) < 0.05:
                etype = "conserved"
            elif delta_w > 0:
                etype = "increased"
            else:
                etype = "decreased"

            rows.append(
                {
                    "gene1": g1,
                    "gene2": g2,
                    "weight_healthy": w_h,
                    "weight_disease": w_d,
                    "delta_weight": delta_w,
                    "type": etype,
                }
            )

        return pd.DataFrame(rows)

    @staticmethod
    def _compute_node_drift(
        H: nx.Graph, D: nx.Graph, shared_genes: Set[str]
    ) -> pd.DataFrame:
        """
        Node-level drift: change in topology metrics between states.
        Computes a composite Node Drift Score (NDS).
        """
        from app.bio.network import NetworkConstructor
        h_features = NetworkConstructor._compute_node_features(H)
        d_features = NetworkConstructor._compute_node_features(D)

        # Ensure all shared genes are present
        for gene in shared_genes:
            if gene not in h_features.index:
                h_features.loc[gene] = 0
            if gene not in d_features.index:
                d_features.loc[gene] = 0

        drift = pd.DataFrame(index=list(shared_genes))
        drift.index.name = "gene_id"

        for col in ["degree", "weighted_degree", "betweenness", "closeness", "clustering"]:
            drift[f"{col}_healthy"] = h_features.reindex(drift.index)[col].fillna(0)
            drift[f"{col}_disease"] = d_features.reindex(drift.index)[col].fillna(0)
            drift[f"{col}_change"] = drift[f"{col}_disease"] - drift[f"{col}_healthy"]

        # Normalise changes to [0, 1] for composite score
        for col in ["degree", "betweenness", "closeness", "clustering"]:
            change_col = f"{col}_change"
            abs_changes = drift[change_col].abs()
            max_change = abs_changes.max()
            if max_change > 0:
                drift[f"{col}_change_norm"] = abs_changes / max_change
            else:
                drift[f"{col}_change_norm"] = 0.0

        # Node Drift Score: weighted combination
        drift["node_drift_score"] = (
            NODE_DRIFT_WEIGHTS["degree_change_norm"] * drift["degree_change_norm"]
            + NODE_DRIFT_WEIGHTS["betweenness_change_norm"] * drift["betweenness_change_norm"]
            + NODE_DRIFT_WEIGHTS["closeness_change_norm"] * drift["closeness_change_norm"]
            + NODE_DRIFT_WEIGHTS["clustering_change_norm"] * drift["clustering_change_norm"]
        )

        return drift.reset_index()

    @staticmethod
    def _compute_module_drift(H: nx.Graph, D: nx.Graph) -> pd.DataFrame:
        """
        Module-level drift: assess preservation and disruption of gene modules.

        Uses Jaccard similarity of module membership between healthy and disease.
        """
        def get_modules(G):
            """Return {gene: module_id} using greedy modularity."""
            if G.number_of_edges() == 0:
                return {n: "M0" for n in G.nodes()}
            try:
                import community as community_louvain
                return community_louvain.best_partition(G, weight="weight")
            except ImportError:
                comms = list(nx.community.greedy_modularity_communities(G, weight="weight"))
                mapping = {}
                for i, comm in enumerate(comms):
                    for gene in comm:
                        mapping[gene] = i
                return mapping

        h_modules = get_modules(H)
        d_modules = get_modules(D)

        # Group genes by module
        from collections import defaultdict
        h_mod_genes: dict = defaultdict(set)
        for g, m in h_modules.items():
            h_mod_genes[m].add(g)

        d_mod_genes: dict = defaultdict(set)
        for g, m in d_modules.items():
            d_mod_genes[m].add(g)

        rows = []
        for h_mod, h_genes in h_mod_genes.items():
            # Find best matching disease module by Jaccard
            best_jaccard = 0.0
            best_d_mod = None
            for d_mod, d_genes in d_mod_genes.items():
                intersection = len(h_genes & d_genes)
                union = len(h_genes | d_genes)
                j = intersection / union if union > 0 else 0.0
                if j > best_jaccard:
                    best_jaccard = j
                    best_d_mod = d_mod

            rows.append(
                {
                    "healthy_module": h_mod,
                    "matched_disease_module": best_d_mod,
                    "n_genes_healthy": len(h_genes),
                    "n_genes_disease": len(d_mod_genes.get(best_d_mod, set())),
                    "n_shared_genes": len(h_genes & d_mod_genes.get(best_d_mod, set())),
                    "jaccard_similarity": best_jaccard,
                    "disruption_score": 1.0 - best_jaccard,
                }
            )

        return pd.DataFrame(rows)

    @staticmethod
    def _compute_global_drift_score(
        H: nx.Graph, D: nx.Graph, edge_drift: pd.DataFrame
    ) -> Dict:
        """
        Global Network Drift Score (GNDS).

        Formula:
          GNDS = (n_gained + n_lost) / (n_healthy_edges + n_disease_edges + 1)
               + mean(|Δw|) over all conserved edges

        Range: [0, ∞) — higher means more drift.
        """
        n_h_edges = H.number_of_edges()
        n_d_edges = D.number_of_edges()
        n_gained = int((edge_drift["type"] == "gained").sum())
        n_lost = int((edge_drift["type"] == "lost").sum())
        n_increased = int((edge_drift["type"] == "increased").sum())
        n_decreased = int((edge_drift["type"] == "decreased").sum())
        n_conserved = int((edge_drift["type"] == "conserved").sum())

        topology_drift = (n_gained + n_lost) / max(n_h_edges + n_d_edges, 1)
        weight_drift = edge_drift[
            edge_drift["type"].isin(["increased", "decreased"])
        ]["delta_weight"].abs().mean()
        weight_drift = float(weight_drift) if not pd.isna(weight_drift) else 0.0

        gnds = (topology_drift + weight_drift) / 2.0

        return {
            "n_healthy_edges": n_h_edges,
            "n_disease_edges": n_d_edges,
            "n_gained": n_gained,
            "n_lost": n_lost,
            "n_increased": n_increased,
            "n_decreased": n_decreased,
            "n_conserved": n_conserved,
            "topology_drift": topology_drift,
            "weight_drift": weight_drift,
            "global_drift_score": gnds,
            "score_formula": (
                "GNDS = mean(topology_drift, weight_drift); "
                "topology_drift = (n_gained+n_lost)/(n_H_edges+n_D_edges); "
                "weight_drift = mean(|Δweight|) over rewired edges"
            ),
        }
