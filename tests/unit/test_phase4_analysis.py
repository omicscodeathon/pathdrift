import json

import pandas as pd
import pytest

from pathdrift.acquisition.registry import json_safe
from pathdrift.cross_species.edge_mapping import align_edges
from pathdrift.cross_species.module_mapping import align_modules
from pathdrift.cross_species.node_mapping import build_node_alignment
from pathdrift.drift.scoring import compute_gene_drift, validate_scoring_configuration
from pathdrift.orthology.mapping import normalize_gene_id, normalize_mapping, primary_one_to_one
from pathdrift.orthology.validation import validate_orthology


def _mapping():
    return normalize_mapping(pd.DataFrame([
        {"human_ensembl_id": "ENSG00000000001.2", "mouse_ensembl_id": "ENSMUSG00000000001.3", "orthology_type": "ortholog_one2one", "confidence": 1.0, "human_symbol": "H1", "mouse_symbol": "M1"},
        {"human_ensembl_id": "ENSG00000000002", "mouse_ensembl_id": "ENSMUSG00000000002", "orthology_type": "ortholog_one2one", "confidence": 1.0, "human_symbol": "H2", "mouse_symbol": "M2"},
        {"human_ensembl_id": "ENSG00000000003", "mouse_ensembl_id": "ENSMUSG00000000003", "orthology_type": "ortholog_one2one", "confidence": 1.0, "human_symbol": "H3", "mouse_symbol": "M3"},
        {"human_ensembl_id": "ENSG00000000004", "mouse_ensembl_id": "ENSMUSG00000000004", "orthology_type": "ortholog_one2one", "confidence": 1.0, "human_symbol": "H4", "mouse_symbol": "M4"},
        {"human_ensembl_id": "ENSG00000000005", "mouse_ensembl_id": "ENSMUSG00000000005", "orthology_type": "ortholog_one2many", "confidence": 0.5, "human_symbol": "H5", "mouse_symbol": "M5"},
        {"human_ensembl_id": "ENSG00000000005", "mouse_ensembl_id": "ENSMUSG00000000006", "orthology_type": "ortholog_one2many", "confidence": 0.5, "human_symbol": "H5", "mouse_symbol": "M6"},
    ]))


def test_normalizes_version_suffix_and_preserves_original_id():
    stable_id, original_id = normalize_gene_id("ENSG00000123456.8", "human")
    assert stable_id == "ENSG00000123456"
    assert original_id == "ENSG00000123456.8"
    with pytest.raises(ValueError, match="Invalid human Ensembl"):
        normalize_gene_id("BRCA1", "human")


def test_classifies_non_one_to_one_relationships_without_collapsing_them():
    mapping = _mapping()
    one_to_many = mapping.loc[mapping["human_ensembl_id"] == "ENSG00000000005"]
    assert len(one_to_many) == 2
    assert set(one_to_many["relationship_cardinality"]) == {"one_to_many"}
    primary = primary_one_to_one(mapping)
    assert len(primary) == 4
    assert "ENSG00000000005" not in set(primary["human_ensembl_id"])


def test_primary_mapping_rejects_duplicate_one_to_one_correspondence():
    with pytest.raises(ValueError, match="Ambiguous Ensembl"):
        primary_one_to_one(pd.DataFrame([
            {"human_ensembl_id": "H1", "mouse_ensembl_id": "M1", "orthology_type": "ortholog_one2one", "relationship_cardinality": "one_to_one", "confidence": 1.0},
            {"human_ensembl_id": "H1", "mouse_ensembl_id": "M2", "orthology_type": "ortholog_one2one", "relationship_cardinality": "one_to_one", "confidence": 1.0},
        ]))


def test_validation_reports_unmapped_genes_and_network_coverage():
    mapping = _mapping()
    summary, unmapped_human, unmapped_mouse = validate_orthology(
        mapping,
        {"ENSG00000000001", "ENSG99999999999"},
        {"ENSMUSG00000000001", "ENSMUSG99999999999"},
    )
    assert summary["total_orthology_mappings"] == 6
    assert summary["primary_one_to_one_mappings"] == 4
    assert unmapped_human["gene_id"].tolist() == ["ENSG99999999999"]
    assert unmapped_mouse["gene_id"].tolist() == ["ENSMUSG99999999999"]


def test_node_alignment_marks_network_presence_and_primary_status():
    mapping = _mapping()
    aligned = build_node_alignment(
        mapping,
        pd.DataFrame({"gene_id": ["ENSG00000000001"]}),
        pd.DataFrame({"gene_id": ["ENSMUSG00000000001"]}),
    )
    primary_row = aligned.loc[aligned["human_ensembl_id"] == "ENSG00000000001"].iloc[0]
    ambiguous_row = aligned.loc[aligned["human_ensembl_id"] == "ENSG00000000005"].iloc[0]
    assert primary_row["is_primary"]
    assert not ambiguous_row["is_primary"]


def test_edge_alignment_distinguishes_conserved_lost_gained_rewired_and_unmappable():
    mapping = primary_one_to_one(_mapping())
    human = pd.DataFrame([
        {"edge_id": "h1", "source_gene": "ENSG00000000001", "target_gene": "ENSG00000000002", "weight": 0.80, "pvalue": 0.01, "adjusted_p_value": 0.02},
        {"edge_id": "h2", "source_gene": "ENSG00000000001", "target_gene": "ENSG00000000003", "weight": 0.70},
        {"edge_id": "h3", "source_gene": "ENSG00000000002", "target_gene": "ENSG00000000004", "weight": 0.75},
        {"edge_id": "h4", "source_gene": "ENSG00000000001", "target_gene": "ENSG00000000005", "weight": 0.90},
    ])
    mouse = pd.DataFrame([
        {"edge_id": "m1", "source_gene": "ENSMUSG00000000001", "target_gene": "ENSMUSG00000000002", "weight": 0.82},
        {"edge_id": "m2", "source_gene": "ENSMUSG00000000001", "target_gene": "ENSMUSG00000000003", "weight": 0.649},
        {"edge_id": "m3", "source_gene": "ENSMUSG00000000002", "target_gene": "ENSMUSG00000000003", "weight": 0.60},
        {"edge_id": "m4", "source_gene": "ENSMUSG00000000002", "target_gene": "ENSMUSG00000000005", "weight": 0.75},
    ])

    result = align_edges(human, mouse, mapping, rewiring_threshold=0.05)
    counts = result["status"].value_counts().to_dict()
    assert counts == {"UNMAPPABLE": 2, "REWIRED": 1, "CONSERVED": 1, "LOST": 1, "GAINED": 1}
    gained = result.loc[result["status"] == "GAINED"].iloc[0]
    assert gained["edge_classification"] == "SPECIES_SPECIFIC_MOUSE"
    unmappable = result.loc[result["status"] == "UNMAPPABLE"]
    assert len(unmappable) == 2
    assert result.loc[result["status"] == "CONSERVED", "weight_difference"].iloc[0] == pytest.approx(0.02)


def test_edge_alignment_rejects_self_loops_and_duplicate_undirected_edges():
    mapping = primary_one_to_one(_mapping())
    with pytest.raises(ValueError, match="self-loop"):
        align_edges(pd.DataFrame([{"source_gene": "H1", "target_gene": "H1", "weight": 0.5}]), pd.DataFrame(columns=["source_gene", "target_gene", "weight"]), mapping)
    with pytest.raises(ValueError, match="duplicate undirected"):
        align_edges(pd.DataFrame([
            {"source_gene": "H1", "target_gene": "H2", "weight": 0.5},
            {"source_gene": "H2", "target_gene": "H1", "weight": 0.5},
        ]), pd.DataFrame(columns=["source_gene", "target_gene", "weight"]), mapping)


def test_module_alignment_allows_fragmented_candidate_matches():
    mapping = primary_one_to_one(_mapping())
    result = align_modules(
        pd.DataFrame([{"module_id": "human-module", "size": 3}]),
        pd.DataFrame([
            {"module_id": "human-module", "gene_id": "ENSG00000000001"},
            {"module_id": "human-module", "gene_id": "ENSG00000000002"},
            {"module_id": "human-module", "gene_id": "ENSG00000000003"},
        ]),
        pd.DataFrame([
            {"module_id": "mouse-a", "size": 2},
            {"module_id": "mouse-b", "size": 1},
        ]),
        pd.DataFrame([
            {"module_id": "mouse-a", "gene_id": "ENSMUSG00000000001"},
            {"module_id": "mouse-a", "gene_id": "ENSMUSG00000000002"},
            {"module_id": "mouse-b", "gene_id": "ENSMUSG00000000003"},
        ]),
        mapping,
    )
    assert result["candidate_mouse_module_id"].nunique() == 2
    assert set(result["classification"]) == {"FRAGMENTED"}


def test_gene_drift_score_uses_configured_weights_and_is_bounded():
    mapping = primary_one_to_one(_mapping().iloc[:4])
    human_nodes = pd.DataFrame([
        {"gene_id": "ENSG00000000001", "gene_symbol": "H1", "degree": 1, "module_id": "h"},
        {"gene_id": "ENSG00000000002", "gene_symbol": "H2", "degree": 1, "module_id": "h"},
        {"gene_id": "ENSG00000000003", "gene_symbol": "H3", "degree": 0, "module_id": None},
        {"gene_id": "ENSG00000000004", "gene_symbol": "H4", "degree": 0, "module_id": None},
    ])
    mouse_nodes = pd.DataFrame([
        {"gene_id": f"ENSMUSG0000000000{i}", "gene_symbol": f"M{i}", "degree": 1 if i <= 2 else 0, "module_id": "m" if i <= 2 else None}
        for i in range(1, 5)
    ])
    human_edges = pd.DataFrame([{"source_gene": "ENSG00000000001", "target_gene": "ENSG00000000002", "weight": 0.8}])
    mouse_edges = pd.DataFrame([{"source_gene": "ENSMUSG00000000001", "target_gene": "ENSMUSG00000000003", "weight": 0.8}])

    results = compute_gene_drift(human_nodes, mouse_nodes, human_edges, mouse_edges, mapping)
    assert results["drift_score"].between(0, 1).all()
    assert results.loc[results["human_ensembl_id"] == "ENSG00000000001", "edge_loss_rate"].iloc[0] == 1.0
    assert set(results["drift_category"]).issubset({"LOW_DRIFT", "MODERATE_DRIFT", "HIGH_DRIFT"})


def test_scoring_configuration_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        validate_scoring_configuration(
            {"edge_loss": 0.4, "neighbor_discordance": 0.4, "degree_difference": 0.4},
            {"moderate_drift": 0.3, "high_drift": 0.7},
        )


def test_json_safe_normalizes_non_finite_summary_values():
    summary = json_safe({"module_conservation": float("nan"), "nested": [float("inf")]})

    assert summary == {"module_conservation": None, "nested": [None]}
    json.dumps(summary, allow_nan=False)
