import pandas as pd
import pytest

from pathdrift.acquisition.qc import QCConfig, run_quality_control


def _metadata():
    return pd.DataFrame({
        "sample_id": ["S1", "S2", "S3", "S4"],
        "disease_state": ["cancer", "cancer", "healthy", "healthy"],
        "center": ["A", "A", "B", "B"],
    })


def test_qc_aggregates_versioned_duplicate_ids_and_computes_sample_statistics():
    expression = pd.DataFrame({
        "gene_id": [
            "ENSG00000000001.4", "ENSG00000000001", "ENSG00000000002.2",
            "ENSG00000000003", "ENSG00000000004", "ENSG00000000005",
        ],
        "S1": [5, 5, 8, 3, 7, 2],
        "S2": [6, 4, 7, 4, 8, 3],
        "S3": [4, 5, 9, 3, 6, 2],
        "S4": [7, 4, 6, 5, 9, 4],
    })

    result = run_quality_control(
        expression,
        _metadata(),
        species="human",
        data_type="raw_counts",
        config=QCConfig(min_expression=1, min_samples=2, pca_gene_limit=10),
    )

    assert result["summary"]["initial_samples"] == 4
    assert result["summary"]["duplicate_gene_ids_aggregated"] == 1
    assert result["summary"]["normalization_method"] == "log2cpm"
    assert result["sample_correlation"].shape == (4, 4)
    assert result["pca_coordinates"].shape[0] == 4
    assert result["sample_qc"]["library_size"].gt(0).all()
    assert result["summary"]["batch_variables"] == [{
        "variable": "center", "levels": ["A", "B"], "level_count": 2, "varies": True,
    }]


def test_normalized_data_is_not_cpm_normalized_again():
    expression = pd.DataFrame({
        "gene_id": [f"ENSG0000000000{index}" for index in range(1, 7)],
        "S1": [5.0, 8.0, 3.0, 7.0, 2.0, 4.0],
        "S2": [6.0, 7.0, 4.0, 8.0, 3.0, 5.0],
        "S3": [4.0, 9.0, 3.0, 6.0, 2.0, 4.0],
        "S4": [7.0, 6.0, 5.0, 9.0, 4.0, 3.0],
    })

    result = run_quality_control(
        expression,
        _metadata(),
        species="human",
        data_type="normalized",
        config=QCConfig(min_expression=1, min_samples=2),
    )

    assert result["summary"]["normalization_method"] == "none"
    assert result["normalized_expression"].max().max() == expression.iloc[:, 1:].max().max()


def test_source_gene_identifiers_are_qc_checked_without_ensembl_validation():
    expression = pd.DataFrame({
        "gene_id": ["Actb", "Actb", "Gapdh", "Krt8", "Krt18", "Epcam"],
        "S1": [5.0, 2.0, 8.0, 3.0, 7.0, 2.0],
        "S2": [6.0, 3.0, 7.0, 4.0, 8.0, 3.0],
        "S3": [4.0, 1.0, 9.0, 3.0, 6.0, 2.0],
        "S4": [7.0, 2.0, 6.0, 5.0, 9.0, 4.0],
    })

    result = run_quality_control(
        expression,
        _metadata(),
        species="mouse",
        data_type="fpkm",
        gene_identifier_type="source",
        config=QCConfig(min_expression=1, min_samples=2, pca_gene_limit=10),
    )

    assert result["summary"]["gene_identifier_type"] == "source"
    assert result["summary"]["invalid_gene_ids"] == 0
    assert result["summary"]["duplicate_gene_ids_aggregated"] == 1
    assert result["summary"]["normalization_method"] == "log2"
    assert result["pca_coordinates"].shape[0] == 4


def test_qc_rejects_duplicate_sample_metadata():
    expression = pd.DataFrame({
        "gene_id": [f"ENSG0000000000{index}" for index in range(1, 7)],
        "S1": [5, 8, 3, 7, 2, 4],
        "S2": [6, 7, 4, 8, 3, 5],
        "S3": [4, 9, 3, 6, 2, 4],
    })
    metadata = pd.concat([_metadata().iloc[:3], _metadata().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate sample IDs"):
        run_quality_control(expression, metadata, species="human", data_type="normalized")