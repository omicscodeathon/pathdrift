from __future__ import annotations

import json

import pandas as pd
import pytest

from app.api.routes import phase5
from app.services import filesystem_runs
from pathdrift.phase5.scoring import (
    build_biomarker_candidates,
    build_gene_loss_tables,
    compute_hub_metrics,
)
from pathdrift.phase5 import service


def test_gene_loss_score_renormalizes_missing_evidence_and_excludes_mouse_score():
    human = pd.DataFrame([
        {"gene_id": "ENSG1", "log2fc": -2.0, "adjusted_p_value": 0.01, "gene_symbol": "A"},
        {"gene_id": "ENSG2", "log2fc": 2.0, "adjusted_p_value": 0.01, "gene_symbol": "B"},
        {"gene_id": "ENSG4", "log2fc": None, "adjusted_p_value": 0.01, "gene_symbol": "D"},
    ])
    mouse = pd.DataFrame([
        {"gene_id": "ENSMUSG1", "log2fc": -3.0, "adjusted_p_value": 0.001},
    ])
    drift = pd.DataFrame([
        {"human_ensembl_id": "ENSG1", "mouse_ensembl_id": "ENSMUSG1", "drift_score": 0.9, "drift_category": "HIGH_DRIFT", "edge_loss_rate": 0.8},
        {"human_ensembl_id": "ENSG2", "mouse_ensembl_id": "ENSMUSG2", "drift_score": 0.2, "drift_category": "LOW_DRIFT", "edge_loss_rate": 0.1},
        {"human_ensembl_id": "ENSG3", "mouse_ensembl_id": "ENSMUSG3", "drift_score": 0.4, "drift_category": "MODERATE_DRIFT", "edge_loss_rate": 0.3},
        {"human_ensembl_id": "ENSG4", "mouse_ensembl_id": "ENSMUSG4", "drift_score": 0.4, "drift_category": "MODERATE_DRIFT", "edge_loss_rate": 0.3},
    ])
    orthology = pd.DataFrame([
        {"human_ensembl_id": "ENSG1", "mouse_ensembl_id": "ENSMUSG1", "orthology_type": "ortholog_one2one"},
    ])

    evidence, scores, high_risk = build_gene_loss_tables(human, mouse, drift, orthology)

    first = evidence.set_index("human_gene_id").loc["ENSG1"]
    assert first["risk_score"] == 0.95
    assert first["mouse_exploratory_downregulated"]
    assert first["one_to_one_orthology_recorded"]
    assert scores.iloc[0]["human_gene_id"] == "ENSG1"
    assert high_risk["human_gene_id"].tolist() == ["ENSG1"]
    assert evidence.loc[evidence["human_gene_id"] == "ENSG2", "score_evidence_count"].iloc[0] == 2
    missing_expression = evidence.set_index("human_gene_id").loc["ENSG3"]
    assert pd.isna(missing_expression["human_expression_loss_component"])
    assert missing_expression["risk_score"] == 0.4
    assert missing_expression["score_evidence_count"] == 1
    untestable_expression = evidence.set_index("human_gene_id").loc["ENSG4"]
    assert pd.isna(untestable_expression["human_expression_loss_component"])
    assert untestable_expression["score_evidence_count"] == 1


def test_biomarker_candidates_are_transparent_and_not_clinical():
    significant = pd.DataFrame([
        {"gene_id": "ENSG1", "log2fc": 2.5, "adjusted_p_value": 0.001, "direction": "UPREGULATED"},
        {"gene_id": "ENSG2", "log2fc": 3.0, "adjusted_p_value": 0.002, "direction": "UPREGULATED"},
    ])
    nodes = pd.DataFrame([{
        "gene_id": "ENSG1",
        "degree": 9,
        "weighted_degree": 7.5,
        "betweenness_centrality": 0.9,
        "module_id": "module_1",
        "gene_symbol": None,
    }])
    drift = pd.DataFrame([{
        "human_ensembl_id": "ENSG1",
        "mouse_ensembl_id": "ENSMUSG1",
        "drift_score": 0.7,
        "drift_category": "HIGH_DRIFT",
    }])
    orthology = pd.DataFrame([{
        "human_ensembl_id": "ENSG1",
        "human_symbol": "GENE1",
        "mouse_ensembl_id": "ENSMUSG1",
        "mouse_symbol": "Gene1",
        "orthology_type": "ortholog_one2one",
    }])

    result = build_biomarker_candidates(significant, nodes, drift, orthology)

    candidate = result.iloc[0]
    assert candidate["gene_symbol"] == "GENE1"
    assert candidate["mouse_ortholog_symbol"] == "Gene1"
    assert candidate["network_degree"] == 9
    assert candidate["clinical_validation"] == False
    assert candidate["candidate_status"] == "MULTI_EVIDENCE_CANDIDATE"
    assert "hub-supported" in candidate["evidence_categories"]
    assert "DEG-supported" in candidate["evidence_categories"]
    assert result["gene_id"].tolist() == ["ENSG1"]


def test_degree_alone_cannot_qualify_as_a_hub():
    nodes = pd.DataFrame([
        {"gene_id": "g1", "degree": 1, "module_id": "m1"},
        {"gene_id": "g2", "degree": 2, "module_id": "m1"},
    ])

    result = compute_hub_metrics(nodes)

    assert result["hub_supported"].isna().all()
    assert result["hub_metric_count"].tolist() == [1, 1]


def test_phase5_service_writes_scoped_tables_and_unavailable_statuses(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    run_directory = tmp_path / "results" / "runs" / run_id
    run_directory.mkdir(parents=True)
    (run_directory / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "COMPLETED",
        "phase3": {"status": "COMPLETED"},
    }), encoding="utf-8")
    inputs = {
        "deg/human/all_genes.csv": "gene_id,log2fc,adjusted_p_value\nENSG1,-2,0.01\n",
        "deg/human/significant_genes.csv": "gene_id,log2fc,adjusted_p_value,direction\nENSG1,-2,0.01,DOWNREGULATED\n",
        "deg/mouse/cross_study_exploratory/all_genes.csv": "gene_id,log2fc,adjusted_p_value\nENSMUSG1,-1,0.02\n",
        "networks/human_cancer_nodes.csv": "gene_id,degree,gene_symbol\nENSG1,3,G1\n",
        "drift/gene_drift.csv": "human_ensembl_id,mouse_ensembl_id,drift_score,drift_category\nENSG1,ENSMUSG1,0.8,HIGH_DRIFT\n",
        "orthology/orthologs.csv": "human_ensembl_id,mouse_ensembl_id,human_symbol,mouse_symbol,orthology_type\nENSG1,ENSMUSG1,G1,G1,ortholog_one2one\n",
    }
    for relative_path, contents in inputs.items():
        target = run_directory / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(service, "ROOT", tmp_path)

    result = service.run_phase5(run_id)

    assert result["status"] == "PARTIAL"
    assert result["stages"]["biomarkers"]["candidate_count"] == 1
    assert result["stages"]["ppi"]["status"] == "UNAVAILABLE"
    assert result["stages"]["pathways"]["status"] == "UNAVAILABLE"
    assert result["stages"]["morphology"]["status"] == "UNAVAILABLE"
    assert (run_directory / "gene_loss" / "gene_loss_scores.csv").is_file()
    assert (run_directory / "biomarkers" / "candidate_biomarkers.csv").is_file()


@pytest.mark.asyncio
async def test_phase5_biomarker_api_authorizes_and_paginates_saved_artifact(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    run_directory = tmp_path / run_id
    run_directory.mkdir()
    (run_directory / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "COMPLETED",
        "phase3": {"status": "COMPLETED"},
    }), encoding="utf-8")
    (run_directory / "phase5_summary.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "PARTIAL",
    }), encoding="utf-8")
    biomarker_directory = run_directory / "biomarkers"
    biomarker_directory.mkdir()
    (biomarker_directory / "candidate_biomarkers.csv").write_text(
        "gene_id,gene_symbol\nENSG1,A\nENSG2,B\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(phase5, "FILESYSTEM_RUNS_ROOT", tmp_path)
    monkeypatch.setattr(filesystem_runs, "FILESYSTEM_RUNS_ROOT", tmp_path)

    async def authorize(*_args):
        return None

    monkeypatch.setattr(phase5, "_authorize_phase5", authorize)
    result = await phase5.get_phase5_table(
        run_id,
        "biomarkers",
        limit=1,
        offset=1,
        current_user=object(),
        db=object(),
    )

    assert result["total"] == 2
    assert result["items"] == [{"gene_id": "ENSG2", "gene_symbol": "B"}]


@pytest.mark.asyncio
async def test_gene_loss_api_serves_summary_and_scoped_figure(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    run_directory = tmp_path / run_id
    gene_loss_directory = run_directory / "gene_loss"
    gene_loss_directory.mkdir(parents=True)
    (run_directory / "phase5_summary.json").write_text(
        json.dumps({"run_id": run_id, "status": "PARTIAL"}),
        encoding="utf-8",
    )
    (gene_loss_directory / "summary.json").write_text(
        json.dumps({"status": "COMPLETED", "evidence_rows": 3}),
        encoding="utf-8",
    )
    figure_path = gene_loss_directory / "gene_loss_risk_distribution.png"
    figure_path.write_bytes(b"image bytes")
    monkeypatch.setattr(phase5, "FILESYSTEM_RUNS_ROOT", tmp_path)

    async def authorize(*_args):
        return None

    monkeypatch.setattr(phase5, "_authorize_phase5", authorize)
    summary = await phase5.get_gene_loss_summary(run_id, current_user=object(), db=object())
    figure = await phase5.get_gene_loss_figure(run_id, current_user=object(), db=object())

    assert summary["evidence_rows"] == 3
    assert figure.path == figure_path
