from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from pathdrift.phase6 import dataset
from pathdrift.phase6 import service
from pathdrift.phase6 import biological
from pathdrift.phase6.evaluation import build_pipeline, evaluate_models, make_splits


def test_patient_groups_never_cross_validation_folds():
    labels = pd.Series([0, 1] * 6)
    groups = pd.Series([f"patient-{index}" for index in range(12)])
    groups.iloc[1] = groups.iloc[0]
    splits, folds, splitter = make_splits(labels, groups, seed=11, max_folds=3)

    assert folds == 3
    assert splitter == "StratifiedGroupKFold"
    for train, test in splits:
        assert set(groups.iloc[train]).isdisjoint(set(groups.iloc[test]))
        assert set(labels.iloc[test]) == {0, 1}


def test_grouped_split_refuses_folds_without_both_classes():
    labels = pd.Series([0, 0, 0, 0, 1, 1, 1, 1])
    groups = pd.Series(["a", "a", "b", "b", "c", "c", "d", "d"])
    with pytest.raises(ValueError, match="cannot preserve both classes"):
        make_splits(labels, groups, seed=7, max_folds=3)


def test_feature_selection_and_scaling_are_inside_model_pipeline():
    pipeline = build_pipeline("logistic_regression", seed=3)
    assert [name for name, _ in pipeline.steps] == [
        "impute", "variance", "select", "scale", "model"
    ]


def test_load_labeled_expression_uses_manifest_paths_and_preserves_case_groups(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset, "ROOT", tmp_path)
    run_id = "12345678-1234-1234-1234-123456789012"
    run_dir = tmp_path / "results" / "runs" / run_id
    run_dir.mkdir(parents=True)
    expression_path = tmp_path / "processed.tsv"
    metadata_path = tmp_path / "metadata.tsv"
    pd.DataFrame(
        {
            "sample-a": [1.0, 2.0],
            "sample-b": [2.0, 1.0],
            "sample-c": [1.5, 3.0],
            "sample-d": [3.0, 1.5],
        },
        index=pd.Index(["ENSG000001", "ENSG000002"], name="gene_id"),
    ).to_csv(expression_path, sep="\t")
    pd.DataFrame(
        {
            "sample_id": ["sample-a", "sample-b", "sample-c", "sample-d"],
            "disease_state": ["healthy", "cancer", "healthy", "cancer"],
            "case_id": ["case-1", "case-1", "case-2", "case-3"],
        }
    ).to_csv(metadata_path, sep="\t", index=False)
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "COMPLETED",
        "phase3": {"status": "COMPLETED"},
        "datasets": [{
            "accession": "TCGA-BRCA",
            "species": "human",
            "processed_path": str(expression_path),
            "metadata_path": str(metadata_path),
        }],
    }), encoding="utf-8")

    result = dataset.load_labeled_expression(run_id)

    assert result.features.shape == (4, 2)
    assert result.labels.to_dict() == {
        "sample-a": 0, "sample-b": 1, "sample-c": 0, "sample-d": 1,
    }
    assert result.groups is not None
    assert result.groups.loc["sample-a"] == result.groups.loc["sample-b"]
    assert result.preprocessing["matched_labeled_samples"] == 4
    assert result.preprocessing["missing_expression_cells"] == 0


def test_cross_study_pooling_is_not_silently_performed(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset, "ROOT", tmp_path)
    run_id = "12345678-1234-1234-1234-123456789012"
    run_dir = tmp_path / "results" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "COMPLETED",
        "phase3": {"status": "COMPLETED"},
        "datasets": [
            {"accession": "GSE1", "species": "mouse", "metadata_path": "a", "processed_path": "b"},
            {"accession": "GSE2", "species": "mouse", "metadata_path": "c", "processed_path": "d"},
        ],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="found 2"):
        dataset.load_labeled_expression(run_id, species="mouse")


def test_importance_is_aggregated_from_training_folds():
    features = pd.DataFrame(
        {
            "gene-a": [0.0, 0.1, 0.2, 0.3, 2.0, 2.1, 2.2, 2.3],
            "gene-b": [1.0, 0.8, 1.2, 0.9, 1.1, 0.9, 1.3, 1.0],
        },
        index=[f"sample-{index}" for index in range(8)],
    )
    labels = pd.Series([0, 0, 0, 0, 1, 1, 1, 1], index=features.index)

    metrics, predictions, importance, _, split = evaluate_models(
        features, labels, None, seed=5
    )

    assert split["name"] == "StratifiedKFold"
    assert len(predictions) == 8 * 4
    assert set(metrics) == {
        "logistic_regression", "random_forest", "svm", "gradient_boosting"
    }
    assert importance["selection_frequency"].between(0, 1).all()
    assert importance["importance_method"].str.startswith("fold-local").all()
    assert set(importance["model"]) == set(metrics)


def test_saved_phase_artifacts_are_reported_as_annotations_not_missing(tmp_path):
    artifact_paths = (
        "deg/human/all_genes.csv",
        "networks/human_cancer_nodes.csv",
        "modules/human/module_genes.csv",
        "orthology/orthologs.csv",
        "drift/gene_drift.csv",
        "pathways/enrichment_results.csv",
        "morphology/phenotype_variables.csv",
        "morphology/morphology_summary.json",
    )
    for artifact in artifact_paths:
        path = tmp_path / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    groups = service._saved_feature_groups(tmp_path, "human")

    assert groups["differential_expression"]["status"] == "ANNOTATION_AVAILABLE"
    assert groups["network_features"]["status"] == "ANNOTATION_AVAILABLE"
    assert groups["module_features"]["status"] == "ANNOTATION_AVAILABLE"
    assert groups["orthology_features"]["status"] == "ANNOTATION_AVAILABLE"
    assert groups["network_drift_features"]["status"] == "ANNOTATION_AVAILABLE"
    assert groups["pathway_features"]["status"] == "ANNOTATION_AVAILABLE"
    assert groups["morphology_features"]["status"] == "DESCRIPTIVE_METADATA_AVAILABLE"
    assert groups["morphology_features"]["sample_level"] is False


def test_pathway_results_are_joined_to_predictive_genes(tmp_path):
    pathways = tmp_path / "pathways"
    pathways.mkdir()
    pd.DataFrame([
        {
            "species": "human",
            "gene_set_key": "upregulated_deg",
            "database": "GO-BP",
            "pathway_id": "GO:0001",
            "pathway_name": "cell signaling",
            "adjusted_p_value": 0.01,
            "overlapping_gene_ids": "ENSG000001|ENSG000002",
        },
        {
            "species": "human",
            "gene_set_key": "downregulated_deg",
            "database": "GO-BP",
            "pathway_id": "GO:0002",
            "pathway_name": "unadjusted pathway",
            "adjusted_p_value": 0.2,
            "overlapping_gene_ids": "ENSG000001",
        },
    ]).to_csv(pathways / "enrichment_results.csv", index=False)
    pd.DataFrame([{
        "human_gene_set_key": "upregulated_deg",
        "database": "GO-BP",
        "pathway_id": "GO:0001",
        "key_drifted_pathway": True,
    }]).to_csv(pathways / "key_drifted_pathways.csv", index=False)

    annotations = service._pathway_annotations(
        tmp_path, "human", {"ENSG000001", "ENSG000003"}
    ).set_index("gene_id")

    assert annotations.loc["ENSG000001", "pathway_annotation_names"] == "cell signaling"
    assert annotations.loc["ENSG000001", "key_drifted_annotation_names"] == "cell signaling"
    assert "ENSG000003" not in annotations.index


def test_training_fold_deg_ranking_ignores_held_out_expression_and_labels():
    features = pd.DataFrame(
        {
            "ENSG000001": [0.0, 0.2, 5.0, 5.2, 1000.0, -1000.0],
            "ENSG000002": [2.0, 2.1, 2.0, 2.1, -1000.0, 1000.0],
        },
        index=[f"sample-{index}" for index in range(6)],
    )
    labels = pd.Series([0, 0, 1, 1, 0, 1], index=features.index)
    train_indices = np.array([0, 1, 2, 3])

    original, _ = biological._rank_training_degs(features, labels, train_indices)
    changed_features = features.copy()
    changed_features.iloc[4:] = [[-5000.0, 8000.0], [9000.0, -7000.0]]
    changed_labels = labels.copy()
    changed_labels.iloc[4:] = [1, 0]
    changed, _ = biological._rank_training_degs(
        changed_features, changed_labels, train_indices
    )

    pd.testing.assert_frame_equal(original, changed)


def test_hub_and_drift_experiments_are_unavailable_without_training_fold_edges(
    tmp_path, monkeypatch
):
    features = pd.DataFrame(
        {
            f"ENSG{index:011d}": [float(sample + index % 3) for sample in range(12)]
            for index in range(1, 7)
        },
        index=[f"sample-{index}" for index in range(12)],
    )
    labels = pd.Series([0] * 6 + [1] * 6, index=features.index)
    baseline = pd.DataFrame({
        "model": ["logistic_regression"] * len(labels),
        "sample_id": features.index,
        "predicted_probability": [0.1, 0.2, 0.2, 0.3, 0.4, 0.3, 0.6, 0.7, 0.8, 0.9, 0.8, 0.7],
    })

    def no_edges(expression, **kwargs):
        assert expression.shape[1] < len(features)
        return {
            "nodes": pd.DataFrame(columns=["gene_id", "degree", "weighted_degree"]),
            "edges": pd.DataFrame(columns=["source_gene", "target_gene"]),
        }

    monkeypatch.setattr(biological, "construct_network", no_edges)
    summary, predictions, _ = biological.evaluate_biological_experiments(
        tmp_path, features, labels, None, baseline, seed=3
    )

    assert summary["experiments"]["deg_ranked_expression"]["status"] == "EVALUATED"
    assert summary["experiments"]["deg_plus_hubs"]["status"] == "NOT_AVAILABLE"
    assert summary["experiments"]["deg_plus_drift"]["status"] == "NOT_AVAILABLE"
    assert len(predictions) == len(labels)


def test_mouse_phase6_reports_study_confounding_without_overwriting_human_results(
    tmp_path, monkeypatch
):
    run_id = "12345678-1234-1234-1234-123456789012"
    run_directory = tmp_path / "results" / "runs" / run_id
    run_directory.mkdir(parents=True)
    cohorts = [
        ("GSE-cancer", ["cancer"] * 4),
        ("GSE-healthy", ["healthy"] * 3),
    ]
    entries = []
    for accession, labels in cohorts:
        metadata_path = tmp_path / f"{accession}.tsv"
        pd.DataFrame({
            "sample_id": [f"{accession}-{index}" for index in range(len(labels))],
            "disease_state": labels,
        }).to_csv(metadata_path, sep="\t", index=False)
        entries.append({
            "accession": accession,
            "species": "mouse",
            "metadata_path": str(metadata_path),
            "processed_path": str(tmp_path / f"{accession}.parquet"),
            "tissue": "mammary",
        })
    (run_directory / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "COMPLETED",
        "phase3": {"status": "COMPLETED"},
        "datasets": entries,
    }), encoding="utf-8")
    human_summary_path = run_directory / "ml" / "phase6_summary.json"
    human_summary_path.parent.mkdir(parents=True)
    human_summary_path.write_text('{"species":"human"}', encoding="utf-8")
    monkeypatch.setattr(dataset, "ROOT", tmp_path)
    monkeypatch.setattr(service, "ROOT", tmp_path)

    summary = service.run_phase6(run_id, species="mouse", force=True)

    assert summary["status"] == "NOT_ESTIMABLE"
    assert summary["estimable_cohorts"] == []
    assert [cohort["healthy_samples"] for cohort in summary["cohorts"]] == [0, 3]
    assert [cohort["cancer_samples"] for cohort in summary["cohorts"]] == [4, 0]
    assert json.loads(human_summary_path.read_text(encoding="utf-8")) == {"species": "human"}
    assert (run_directory / "ml" / "mouse" / "phase6_summary.json").is_file()
