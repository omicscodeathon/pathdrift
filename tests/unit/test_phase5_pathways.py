import json

import pandas as pd
import pytest

from app.services import filesystem_runs
from pathdrift.phase5.pathways import Pathway, compare_pathways, run_over_representation
from pathdrift.phase5.phenotype import build_phenotype_metadata
from pathdrift.phase5.service import _attach_candidate_pathway_evidence


def test_ora_uses_species_specific_expressed_background_and_bh() -> None:
    pathways = {
        "human": [
            Pathway("human", "GO-BP", "GO:1", "Human term", frozenset({"h1", "h2"}), "test"),
            Pathway("human", "GO-BP", "GO:2", "Other human term", frozenset({"h3"}), "test"),
        ],
        "mouse": [
            Pathway("mouse", "GO-BP", "GO:1", "Mouse term", frozenset({"m1", "m2"}), "test"),
            Pathway("mouse", "GO-BP", "GO:2", "Other mouse term", frozenset({"m3"}), "test"),
        ],
    }
    gene_maps = {
        "human": {gene_id: {"symbol": gene_id.upper(), "entrez_id": ""} for gene_id in ("h1", "h2", "h3")},
        "mouse": {gene_id: {"symbol": gene_id.upper(), "entrez_id": ""} for gene_id in ("m1", "m2", "m3")},
    }
    result = run_over_representation(
        {("human", "significant_deg"): {"h1", "h2"}, ("mouse", "significant_deg"): {"m1"}},
        pathways,
        gene_maps,
        {"human": {"h1", "h2", "h3"}, "mouse": {"m1", "m3"}},
    )

    human = result.loc[result["species"].eq("human")].iloc[0]
    mouse = result.loc[result["species"].eq("mouse")].iloc[0]
    assert human["background_gene_count"] == 3
    assert human["overlap_gene_count"] == 2
    assert human["p_value"] == pytest.approx(1 / 3)
    assert mouse["background_gene_count"] == 2
    assert mouse["overlap_gene_count"] == 1
    assert mouse["p_value"] == pytest.approx(0.5)
    assert mouse["overlapping_gene_ids"] == "m1"
    assert set(result["species"]) == {"human", "mouse"}


def test_pathway_comparison_requires_enrichment_and_measured_edge_divergence() -> None:
    human_path = Pathway("human", "WikiPathways", "WP1", "Shared pathway", frozenset({"h1", "h2"}), "test")
    mouse_path = Pathway("mouse", "WikiPathways", "WP1", "Shared pathway", frozenset({"m1", "m2"}), "test")
    enrichment = pd.DataFrame([
        {"species": "human", "gene_set_key": "significant_deg", "database": "WikiPathways", "pathway_id": "WP1", "pathway_name": "Shared pathway", "adjusted_p_value": 0.01},
        {"species": "mouse", "gene_set_key": "significant_deg", "database": "WikiPathways", "pathway_id": "WP1", "pathway_name": "Shared pathway", "adjusted_p_value": 0.2},
    ])
    orthology = pd.DataFrame([
        {"human_ensembl_id": "h1", "mouse_ensembl_id": "m1", "orthology_type": "ortholog_one2one"},
        {"human_ensembl_id": "h2", "mouse_ensembl_id": "m2", "orthology_type": "ortholog_one2one"},
    ])
    edge = pd.DataFrame([{"source_gene": "h1", "target_gene": "h2"}])
    empty_edges = pd.DataFrame(columns=["source_gene", "target_gene"])
    nodes = pd.DataFrame([
        {"gene_id": "h1", "degree": 2},
        {"gene_id": "h2", "degree": 4},
    ])
    modules = pd.DataFrame([
        {"gene_id": "h1", "module_id": "H1"},
        {"gene_id": "h2", "module_id": "H1"},
    ])

    result = compare_pathways(
        enrichment,
        {"human": [human_path], "mouse": [mouse_path]},
        orthology,
        {"human_cancer": edge, "mouse_cancer": empty_edges},
        {"human_cancer": nodes, "mouse_cancer": None},
        {"human": modules, "mouse": modules.rename(columns={"gene_id": "gene_id"}).assign(gene_id=["m1", "m2"])},
    )

    row = result.iloc[0]
    assert row["conserved_ortholog_count"] == 2
    assert row["lost_edge_count"] == 1
    assert row["gained_edge_count"] == 0
    assert row["pathway_drift_score"] == 1
    assert row["key_drifted_pathway"]
    assert row["human_mean_degree"] == 3
    assert row["module_preservation_jaccard"] == 1
    assert row["human_unpaired_pathway_member_count"] == 0
    assert row["mouse_unpaired_pathway_member_count"] == 0
    assert "conserved_orthologs" not in result.columns


def test_phenotype_artifacts_are_descriptive_and_distinguish_image_evidence(tmp_path) -> None:
    run_directory = tmp_path / "results" / "runs" / "test-run"
    run_directory.joinpath("deg", "human").mkdir(parents=True)
    run_directory.joinpath("deg", "human", "summary.json").write_text(json.dumps({
        "case_sample_ids": ["T1"],
        "control_sample_ids": ["N1"],
    }), encoding="utf-8")
    metadata_path = tmp_path / "metadata.tsv"
    pd.DataFrame([
        {"sample_id": "T1", "disease_state": "cancer", "sample_type": "Primary Tumor", "case_id": "C1", "ajcc_pathologic_stage": "Stage II", "primary_diagnosis": "Carcinoma", "tumor_grade": "", "morphology": "8500/3"},
        {"sample_id": "N1", "disease_state": "healthy", "sample_type": "Solid Tissue Normal", "case_id": "C2", "ajcc_pathologic_stage": "", "primary_diagnosis": "", "tumor_grade": "", "morphology": ""},
    ]).to_csv(metadata_path, sep="\t", index=False)
    manifest = {"datasets": [{"species": "human", "accession": "TEST", "metadata_path": str(metadata_path)}]}

    samples, variables, summary = build_phenotype_metadata(run_directory, tmp_path, manifest)

    assert len(samples) == 2
    assert summary["selected_human_tumor_sample_count"] == 1
    assert summary["image_records"] == 0
    assert summary["gene_or_pathway_associations"] == "NOT_CALCULATED"
    assert "morphology" in set(variables["field"])
    assert "tumor_grade" not in summary["observed_pathology_fields"]
    morphology = variables.loc[variables["field"].eq("morphology")].iloc[0]
    assert morphology["evidence_type"] == "CLINICAL_PATHOLOGY_METADATA"


def test_candidate_profiles_replace_stale_evidence_with_computed_status() -> None:
    pathway = Pathway("human", "WikiPathways", "WP1", "Shared pathway", frozenset({"h1"}), "test")
    candidates = pd.DataFrame([{
        "gene_id": "h1",
        "pathway_evidence": "Unavailable: no pathway data",
        "morphology_evidence": "Unavailable: no morphology data",
    }])
    enrichment = pd.DataFrame([{
        "species": "human",
        "gene_set_key": "significant_deg",
        "adjusted_p_value": 0.01,
        "overlapping_gene_ids": "h1",
        "pathway_id": "WP1",
        "pathway_name": "Shared pathway",
    }])

    result = _attach_candidate_pathway_evidence(
        candidates,
        enrichment,
        pd.DataFrame(),
        {"human": [pathway]},
        {"gene_or_pathway_associations": "NOT_CALCULATED"},
    )

    assert result.loc[0, "pathway_evidence_status"] == "SIGNIFICANT_DEG_PATHWAY_OVERLAP"
    assert result.loc[0, "pathway_evidence"] == "Shared pathway (WP1)"
    assert "no gene/pathway association tested" in result.loc[0, "morphology_evidence"]

    unavailable = _attach_candidate_pathway_evidence(
        candidates,
        pd.DataFrame(),
        pd.DataFrame(),
        {"human": []},
        {"gene_or_pathway_associations": "NOT_CALCULATED"},
        pathway_status="UNAVAILABLE",
    )
    assert unavailable.loc[0, "pathway_evidence_status"] == "UNAVAILABLE"
    assert "references are unavailable" in unavailable.loc[0, "pathway_evidence"]


def test_streamed_pathway_page_filters_and_counts_without_loading_full_table(monkeypatch, tmp_path) -> None:
    run_id = "11111111-1111-1111-1111-111111111111"
    run_directory = tmp_path / run_id
    run_directory.mkdir()
    run_directory.joinpath("manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "COMPLETED",
        "phase3": {"status": "COMPLETED"},
    }), encoding="utf-8")
    pathway_directory = run_directory / "pathways"
    pathway_directory.mkdir()
    pd.DataFrame([
        {"species": "human", "gene_set_key": "significant_deg", "database": "GO-BP", "adjusted_p_value": 0.01, "pathway_id": "GO:1"},
        {"species": "human", "gene_set_key": "significant_deg", "database": "GO-BP", "adjusted_p_value": 0.08, "pathway_id": "GO:2"},
        {"species": "mouse", "gene_set_key": "significant_deg", "database": "GO-BP", "adjusted_p_value": 0.01, "pathway_id": "GO:3"},
    ]).to_csv(pathway_directory / "enrichment_results.csv", index=False)
    monkeypatch.setattr(filesystem_runs, "FILESYSTEM_RUNS_ROOT", tmp_path)

    items, total = filesystem_runs.read_result_csv_page(
        run_id,
        "pathways/enrichment_results.csv",
        limit=10,
        offset=0,
        species="human",
        gene_set_key="significant_deg",
        database="GO-BP",
        significant_only=True,
    )

    assert total == 1
    assert items[0]["pathway_id"] == "GO:1"


def test_streamed_pathway_page_reads_large_enrichment_fields(monkeypatch, tmp_path) -> None:
    run_id = "11111111-1111-1111-1111-111111111111"
    run_directory = tmp_path / run_id
    run_directory.mkdir()
    run_directory.joinpath("manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "COMPLETED",
        "phase3": {"status": "COMPLETED"},
    }), encoding="utf-8")
    pathway_directory = run_directory / "pathways"
    pathway_directory.mkdir()
    large_gene_list = "|".join(f"ENSG{i:011d}" for i in range(20_000))
    pd.DataFrame([{
        "species": "human",
        "gene_set_key": "significant_deg",
        "database": "GO-BP",
        "adjusted_p_value": 0.01,
        "pathway_id": "GO:1",
        "overlapping_gene_ids": large_gene_list,
    }]).to_csv(pathway_directory / "enrichment_results.csv", index=False)
    monkeypatch.setattr(filesystem_runs, "FILESYSTEM_RUNS_ROOT", tmp_path)

    items, total = filesystem_runs.read_result_csv_page(
        run_id,
        "pathways/enrichment_results.csv",
        limit=10,
        offset=0,
        species="human",
        gene_set_key="significant_deg",
        significant_only=True,
    )

    assert total == 1
    assert items[0]["pathway_id"] == "GO:1"
    assert len(items[0]["overlapping_gene_ids"]) > 131_072
