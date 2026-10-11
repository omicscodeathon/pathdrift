from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def write_deg_figures(
    results: pd.DataFrame,
    output_dir: Path,
    *,
    accession: str,
    alpha: float,
    lfc_threshold: float,
    expression_scale: str,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    significant = results["significant"].astype(bool)
    padj = results["adjusted_p_value"].astype(float).clip(lower=np.finfo(float).tiny)
    colors = np.where(
        results["direction"].eq("UPREGULATED"), "#c0392b",
        np.where(results["direction"].eq("DOWNREGULATED"), "#2471a3", "#aab2bd"),
    )
    figures = []

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(results["log2fc"], -np.log10(padj), c=colors, s=9, alpha=0.65, linewidths=0, rasterized=True)
    ax.axvline(lfc_threshold, color="#566573", linestyle="--", linewidth=0.8)
    ax.axvline(-lfc_threshold, color="#566573", linestyle="--", linewidth=0.8)
    ax.axhline(-np.log10(alpha), color="#566573", linestyle="--", linewidth=0.8)
    top_genes = results.loc[significant].nsmallest(10, "adjusted_p_value")
    for row in top_genes.itertuples():
        ax.annotate(str(row.gene_id), (row.log2fc, -np.log10(max(row.adjusted_p_value, np.finfo(float).tiny))),
                    fontsize=7, xytext=(3, 3), textcoords="offset points")
    ax.set(title=f"{accession}: differential expression", xlabel="log2 fold change", ylabel="-log10 adjusted p-value")
    ax.text(0.01, 0.99, f"{int(significant.sum()):,} significant / {len(results):,} tested", transform=ax.transAxes, va="top")
    fig.tight_layout()
    for suffix in ("png", "svg"):
        path = output_dir / f"volcano.{suffix}"
        fig.savefig(path, dpi=180 if suffix == "png" else None)
        figures.append({"path": str(path), "figure_type": "volcano", "format": suffix})
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 7))
    if expression_scale == "log2":
        average_expression = results["average_expression"].astype(float)
        average_label = "mean log2 expression"
    else:
        average_expression = np.log10(results["average_expression"].astype(float).clip(lower=0) + 1)
        average_label = "log10 average expression + 1"
    ax.scatter(
        average_expression,
        results["log2fc"],
        c=colors,
        s=9,
        alpha=0.65,
        linewidths=0,
        rasterized=True,
    )
    ax.axhline(0, color="#566573", linewidth=0.8)
    ax.axhline(lfc_threshold, color="#566573", linestyle="--", linewidth=0.8)
    ax.axhline(-lfc_threshold, color="#566573", linestyle="--", linewidth=0.8)
    ax.set(title=f"{accession}: MA plot", xlabel=average_label, ylabel="log2 fold change")
    fig.tight_layout()
    for suffix in ("png", "svg"):
        path = output_dir / f"ma_plot.{suffix}"
        fig.savefig(path, dpi=180 if suffix == "png" else None)
        figures.append({"path": str(path), "figure_type": "ma_plot", "format": suffix})
    plt.close(fig)
    return figures
