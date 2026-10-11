from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd


def write_network_figures(nodes: pd.DataFrame, summary: dict, output_dir: Path, label: str) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    degrees = nodes["degree"].astype(int)
    fig, ax = plt.subplots(figsize=(8, 5))
    if degrees.empty:
        ax.text(0.5, 0.5, "No genes passed network filtering", ha="center", va="center", transform=ax.transAxes)
    else:
        distribution = degrees.value_counts().sort_index()
        ax.bar(distribution.index, distribution.values, color="#355C7D", width=0.85)
        ax.set_yscale("log" if int(distribution.max()) > 1 else "linear")
    ax.set(title=f"{label}: degree distribution", xlabel="Degree", ylabel="Number of genes")
    fig.tight_layout()
    figures = []
    for suffix in ("png", "svg"):
        path = output_dir / f"degree_distribution.{suffix}"
        fig.savefig(path, dpi=180 if suffix == "png" else None)
        figures.append({"path": str(path), "figure_type": "degree_distribution", "format": suffix})
    plt.close(fig)

    keys = ["n_nodes", "n_edges", "connected_components", "largest_component_size"]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(keys, [summary[key] for key in keys], color="#6C5B7B")
    ax.set(title=f"{label}: network statistics", ylabel="Count")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    for suffix in ("png", "svg"):
        path = output_dir / f"network_statistics.{suffix}"
        fig.savefig(path, dpi=180 if suffix == "png" else None)
        figures.append({"path": str(path), "figure_type": "network_statistics", "format": suffix})
    plt.close(fig)
    return figures


def write_top_centrality_subnetwork(
    graph: nx.Graph,
    nodes: pd.DataFrame,
    output_dir: Path,
    *,
    label: str,
    seed: int,
    max_nodes: int = 40,
) -> list[dict]:
    if graph.number_of_edges() == 0 or graph.number_of_nodes() <= 1000:
        return []
    selected = nodes.sort_values(
        ["weighted_degree", "betweenness_centrality", "gene_id"],
        ascending=[False, False, True],
    )["gene_id"].head(max_nodes).astype(str).tolist()
    subgraph = graph.subgraph(selected).copy()
    if not subgraph.number_of_edges():
        return []
    positions = nx.spring_layout(subgraph, seed=seed, weight="weight", iterations=80)
    fig, ax = plt.subplots(figsize=(12, 10))
    node_values = [subgraph.degree(node) for node in subgraph.nodes()]
    nx.draw_networkx_edges(subgraph, positions, ax=ax, alpha=0.28, width=0.7)
    nx.draw_networkx_nodes(
        subgraph,
        positions,
        ax=ax,
        node_size=[40 + 25 * degree for degree in node_values],
        node_color=node_values,
        cmap="viridis",
    )
    labels = dict(zip(
        nodes["gene_id"].astype(str),
        nodes["gene_symbol"].where(nodes["gene_symbol"].notna(), nodes["gene_id"]).astype(str),
    )) if "gene_symbol" in nodes else None
    if labels is not None:
        labels = {node: labels.get(node, node) for node in subgraph.nodes()}
    nx.draw_networkx_labels(subgraph, positions, labels=labels, ax=ax, font_size=6)
    ax.set_title(f"{label}: top-centrality induced subnetwork")
    ax.set_axis_off()
    fig.tight_layout()
    output_dir.mkdir(parents=True, exist_ok=True)
    figures = []
    for suffix in ("png", "svg"):
        path = output_dir / f"top_centrality_subnetwork.{suffix}"
        fig.savefig(path, dpi=180 if suffix == "png" else None)
        figures.append({"path": str(path), "figure_type": "top_centrality_subnetwork", "format": suffix})
    plt.close(fig)
    return figures
