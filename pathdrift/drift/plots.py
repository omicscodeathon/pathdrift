from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def write_drift_figures(genes: pd.DataFrame, edges: pd.DataFrame, modules: pd.DataFrame, root: Path) -> list[str]:
    root.mkdir(parents=True, exist_ok=True)
    paths = []

    figure, axis = plt.subplots(figsize=(8, 5))
    if not genes.empty:
        axis.hist(genes["drift_score"], bins=20, color="#3478a8", edgecolor="white")
    axis.set(xlabel="Gene drift score", ylabel="Aligned genes", title="Cross-species gene drift distribution")
    figure.tight_layout()
    path = root / "gene_drift_distribution.png"
    figure.savefig(path, dpi=140)
    plt.close(figure)
    paths.append(str(path))

    counts = edges["status"].value_counts().reindex(
        ["CONSERVED", "LOST", "GAINED", "REWIRED", "UNMAPPABLE"], fill_value=0
    ) if not edges.empty else pd.Series(0, index=["CONSERVED", "LOST", "GAINED", "REWIRED", "UNMAPPABLE"])
    figure, axis = plt.subplots(figsize=(8, 5))
    axis.bar(counts.index, counts.values, color=["#39845b", "#bd554c", "#477bb7", "#d39632", "#969da4"])
    axis.set(ylabel="Edges", title="Cross-species edge classifications")
    axis.tick_params(axis="x", rotation=15)
    figure.tight_layout()
    path = root / "edge_conservation_summary.png"
    figure.savefig(path, dpi=140)
    plt.close(figure)
    paths.append(str(path))

    counts = modules["classification"].value_counts() if not modules.empty else pd.Series(dtype=int)
    figure, axis = plt.subplots(figsize=(8, 5))
    if not counts.empty:
        axis.bar(counts.index, counts.values, color="#8b6bb5")
    axis.set(ylabel="Human module candidates", title="Module conservation classifications")
    axis.tick_params(axis="x", rotation=15)
    figure.tight_layout()
    path = root / "module_conservation.png"
    figure.savefig(path, dpi=140)
    plt.close(figure)
    paths.append(str(path))
    return paths
