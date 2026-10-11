from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from pathdrift.differential_expression.service import analyze_comparison
from pathdrift.differential_expression.cross_study import prepare_mouse_cross_study_expression
from pathdrift.differential_expression.validation import ExpressionValidationError
from pathdrift.modules.detection import detect_modules
from pathdrift.networks.centrality import _landmark_closeness
from pathdrift.networks.construction import construct_network
from pathdrift.networks.correlation import correlation_edges
from pathdrift.networks.statistics import network_statistics


def _gene_ids(count: int) -> list[str]:
    return [f"ENSG{index:011d}" for index in range(1, count + 1)]


def test_mouse_gene_symbol_fallback_uses_unambiguous_one_to_one_ids(tmp_path):
    from pathdrift.phase3 import _mouse_gene_symbols

    mapping_path = tmp_path / "orthology.tsv"
    pd.DataFrame({
        "mouse_ensembl_id": [
            "ENSMUSG00000000001",
            "ENSMUSG00000000002",
            "ENSMUSG00000000002",
            "ENSMUSG00000000003",
        ],
        "mouse_symbol": ["GeneA", "Ambiguous", "Ambiguous", "ManyToOne"],
        "orthology_type": [
            "ortholog_one2one",
            "ortholog_one2one",
            "ortholog_one2one",
            "ortholog_many2one",
        ],
    }).to_csv(mapping_path, sep="\t", index=False)

    _mouse_gene_symbols.cache_clear()
    assert _mouse_gene_symbols(str(mapping_path)) == {
        "ENSMUSG00000000001": "GeneA",
    }
    _mouse_gene_symbols.cache_clear()


def test_continuous_deg_validates_design_and_returns_complete_fdr_results():
    samples = [f"C{index}" for index in range(1, 4)] + [f"N{index}" for index in range(1, 4)]
    expression = pd.DataFrame(
        [
            [8.0, 8.1, 7.9, 2.0, 2.1, 1.9],
            [3.0, 3.2, 2.9, 3.1, 3.0, 3.2],
            [5.0, 5.2, 5.1, 4.9, 5.0, 4.8],
        ],
        index=_gene_ids(3),
        columns=samples,
    )
    metadata = pd.DataFrame({
        "sample_id": samples,
        "disease_state": ["cancer"] * 3 + ["healthy"] * 3,
    })

    results, summary, validated = analyze_comparison(
        expression,
        metadata,
        raw_counts=None,
        species="human",
        sample_id_column="sample_id",
        condition_column="disease_state",
        case_condition="cancer",
        control_condition="healthy",
        minimum_samples_per_group=3,
        alpha=0.05,
        lfc_threshold=1.0,
        data_type="normalized",
        method="auto",
        min_count=10,
        min_samples_fraction=0.2,
        expression_scale="log2",
    )

    assert len(results) == 3
    assert results["gene_id"].is_unique
    assert results["adjusted_p_value"].dropna().between(0, 1).all()
    assert results.loc[results["gene_id"] == _gene_ids(3)[0], "log2fc"].iloc[0] > 0
    assert summary["method"] == "Welch's t-test + Benjamini-Hochberg"
    assert len(validated.case_samples) == len(validated.control_samples) == 3


def test_continuous_deg_does_not_assign_significance_to_zero_variance_genes():
    samples = ["C1", "C2", "C3", "N1", "N2", "N3"]
    expression = pd.DataFrame(
        [
            [3.0, 3.0 + 1e-15, 3.0, 0.0, 1e-15, 0.0],
            [4.0, 4.2, 3.8, 1.0, 1.2, 0.8],
        ],
        index=_gene_ids(2),
        columns=samples,
    )
    metadata = pd.DataFrame({
        "sample_id": samples,
        "disease_state": ["cancer"] * 3 + ["healthy"] * 3,
    })

    results, summary, _ = analyze_comparison(
        expression,
        metadata,
        raw_counts=None,
        species="human",
        sample_id_column="sample_id",
        condition_column="disease_state",
        case_condition="cancer",
        control_condition="healthy",
        minimum_samples_per_group=3,
        alpha=0.05,
        lfc_threshold=1.0,
        data_type="normalized",
        method="auto",
        min_count=10,
        min_samples_fraction=0.2,
        expression_scale="log2",
    )

    constant = results.loc[results["gene_id"] == _gene_ids(2)[0]].iloc[0]
    variable = results.loc[results["gene_id"] == _gene_ids(2)[1]].iloc[0]
    assert pd.isna(constant["pvalue"])
    assert pd.isna(constant["adjusted_p_value"])
    assert not constant["significant"]
    assert variable["pvalue"] < 0.05
    assert summary["total_genes_tested"] == 1
    assert summary["genes_within_group_variance_unavailable"] == 1


def test_deg_rejects_normalized_data_as_raw_counts():
    samples = ["C1", "C2", "C3", "N1", "N2", "N3"]
    expression = pd.DataFrame([[1.0] * 6], index=_gene_ids(1), columns=samples)
    metadata = pd.DataFrame({
        "sample_id": samples,
        "disease_state": ["cancer"] * 3 + ["healthy"] * 3,
    })
    with pytest.raises(ExpressionValidationError, match="raw_counts"):
        analyze_comparison(
            expression,
            metadata,
            raw_counts=None,
            species="human",
            sample_id_column="sample_id",
            condition_column="disease_state",
            case_condition="cancer",
            control_condition="healthy",
            minimum_samples_per_group=3,
            alpha=0.05,
            lfc_threshold=1.0,
            data_type="raw_counts",
            method="auto",
            min_count=10,
            min_samples_fraction=0.2,
            expression_scale="log2",
        )


def test_raw_count_deg_uses_pydeseq2_without_substituting_continuous_test():
    samples = [f"C{index}" for index in range(1, 5)] + [f"N{index}" for index in range(1, 5)]
    genes = _gene_ids(24)
    counts = pd.DataFrame(
        [
            [
                (100 + gene_index * 3 + sample_index * 2)
                * (4 if gene_index == 0 and sample_index < 4 else 1)
                for sample_index in range(8)
            ]
            for gene_index in range(24)
        ],
        index=genes,
        columns=samples,
        dtype=int,
    )
    metadata = pd.DataFrame({
        "sample_id": samples,
        "disease_state": ["cancer"] * 4 + ["healthy"] * 4,
    })
    normalized = np.log2(counts.astype(float) + 1)

    results, summary, _ = analyze_comparison(
        normalized,
        metadata,
        raw_counts=counts,
        species="human",
        sample_id_column="sample_id",
        condition_column="disease_state",
        case_condition="cancer",
        control_condition="healthy",
        minimum_samples_per_group=3,
        alpha=0.05,
        lfc_threshold=1.0,
        data_type="raw_counts",
        method="auto",
        min_count=10,
        min_samples_fraction=0.2,
        expression_scale="log2",
    )
    assert len(results) == summary["tested_genes"]
    assert summary["method"] == "PyDESeq2 (DESeq2 Wald test)"
    assert set(results["method"]) == {"PyDESeq2 (DESeq2 Wald test)"}


def test_correlation_network_has_unique_undirected_edges_and_statistics():
    samples = [f"S{index}" for index in range(1, 9)]
    expression = pd.DataFrame(
        [
            [1, 2, 3, 4, 5, 6, 7, 8],
            [2, 4, 6, 8, 10, 12, 14, 16],
            [8, 7, 6, 5, 4, 3, 2, 1],
            [1, 3, 2, 5, 4, 7, 6, 8],
        ],
        index=_gene_ids(4),
        columns=samples,
        dtype=float,
    )
    edges, info = correlation_edges(
        expression,
        method="pearson",
        min_abs_correlation=0.7,
        max_adjusted_p_value=0.05,
    )
    assert info["tested_gene_pairs"] == 6
    assert not (edges["source_gene"] == edges["target_gene"]).any()
    assert edges.apply(lambda row: row.source_gene < row.target_gene, axis=1).all()
    assert not edges.duplicated(["source_gene", "target_gene"]).any()

    graph_result = construct_network(
        expression,
        species="human",
        method="pearson",
        min_abs_correlation=0.7,
        max_adjusted_p_value=0.05,
        min_gene_variance=0,
        max_genes=10,
        seed=42,
    )
    stats = network_statistics(
        graph_result["graph"],
        method="pearson",
        filtering=graph_result["summary"]["filtering"],
    )
    assert stats["n_nodes"] == 4
    assert stats["n_edges"] == len(graph_result["edges"])
    assert stats["connected_components"] >= 1


def test_landmark_closeness_matches_exact_scores_when_all_nodes_are_sampled():
    graph = nx.path_graph(6)
    nx.set_edge_attributes(graph, 1.0, "distance")

    approximate = _landmark_closeness(
        graph,
        list(graph.nodes()),
        sample_count=6,
        seed=42,
    )
    exact = nx.closeness_centrality(graph, distance="distance")

    assert approximate == pytest.approx(exact)


def test_mouse_cross_study_inputs_map_genes_exclude_cell_lines_and_pair_tumor_fractions():
    genes = [f"ENSMUSG{index:011d}" for index in range(1, 4)]
    tumor_samples = [
        f"tumor{replicate}{fraction}"
        for replicate in range(1, 4)
        for fraction in ("p", "m")
    ] + ["cellline"]
    tumor_expression = pd.DataFrame(
        [
            [3, 7, 4, 8, 5, 9, 1],
            [2, 6, 3, 7, 4, 8, 1],
            [1, 5, 2, 6, 3, 7, 1],
        ],
        index=genes,
        columns=tumor_samples,
        dtype=float,
    )
    tumor_rows = []
    for replicate in range(1, 4):
        for fraction, sign in (("p", "+"), ("m", "-")):
            tumor_rows.append({
                "sample_id": f"tumor{replicate}{fraction}",
                "disease_state": "cancer",
                "geo_title": f"Her2(+)EpCAM({sign}) tumor - Day20_rep{replicate}",
                "geo_characteristics": (
                    "treatment: CD4 and CD8 double depletion | "
                    "cell type: tumor cells isolated from E-A14 tumors"
                ),
                "geo_sample_id": f"GSM{replicate}{sign}",
            })
    tumor_rows.append({
        "sample_id": "cellline",
        "disease_state": "cancer",
        "geo_title": "E-A14 cell line_rep1",
        "geo_characteristics": "treatment: In vitro cell culture",
        "geo_sample_id": "GSMcell",
    })
    tumor_metadata = pd.DataFrame(tumor_rows)
    healthy_symbols = ["Sym1", "Sym2", "Sym3"]
    healthy_expression = pd.DataFrame(
        [[3, 7, 15], [1, 3, 7], [0, 1, 3]],
        index=healthy_symbols,
        columns=["N1", "N2", "N3"],
        dtype=float,
    )
    healthy_metadata = pd.DataFrame({
        "sample_id": ["N1", "N2", "N3"],
        "disease_state": ["healthy"] * 3,
        "geo_title": ["adult basal", "luminal progenitor", "mature luminal"],
    })
    mapping = pd.DataFrame({
        "mouse_ensembl_id": genes,
        "mouse_symbol": healthy_symbols,
        "orthology_type": ["ortholog_one2one"] * 3,
    })

    expression, metadata, gene_table, info = prepare_mouse_cross_study_expression(
        tumor_expression,
        tumor_metadata,
        healthy_expression,
        healthy_metadata,
        mapping,
    )

    assert expression.shape == (3, 6)
    assert metadata["disease_state"].value_counts().to_dict() == {"cancer": 3, "healthy": 3}
    assert "cellline" not in ";".join(metadata["source_sample_ids"])
    assert info["tumor_source_sample_count"] == 6
    assert info["tumor_cell_line_samples_excluded"] == ["cellline"]
    assert info["tumor_biological_replicates"] == 3
    assert gene_table["gene_id"].tolist() == genes
    assert expression.loc[genes[0], "GSE155577:day20:rep1"] == pytest.approx(2.5)
    assert expression.loc[genes[0], "GSE116385:N1"] == pytest.approx(2.0)


def test_louvain_modules_are_derived_from_graph_and_report_deg_availability():
    graph = nx.Graph()
    first = _gene_ids(5)
    second = [f"ENSG{index:011d}" for index in range(6, 11)]
    graph.add_nodes_from(first + second)
    graph.add_edges_from((first[i], first[j], {"weight": 0.9}) for i in range(5) for j in range(i + 1, 5))
    graph.add_edges_from((second[i], second[j], {"weight": 0.9}) for i in range(5) for j in range(i + 1, 5))
    nodes = pd.DataFrame({
        "gene_id": first + second,
        "degree": [4] * 10,
        "weighted_degree": [3.6] * 10,
        "betweenness_centrality": [0.0] * 10,
        "closeness_centrality": [1.0] * 10,
        "eigenvector_centrality": [0.5] * 10,
        "module_id": [None] * 10,
    })
    modules = detect_modules(
        graph,
        method="louvain",
        resolution=1.0,
        min_module_size=3,
        seed=42,
        nodes=nodes,
    )
    assert len(modules["modules"]) == 2
    assert modules["genes"]["gene_id"].nunique() == 10
    assert modules["summary"]["deg_comparison_available"] is False
    assert modules["modules"]["deg_gene_count"].isna().all()
