import json

import pandas as pd
from app.tasks.report_tasks import _generate_html_report

from app.api.routes import data_acquisition
from app.services.data_acquisition import dataset_manager as dm
from app.services.data_acquisition.dataset_scoring import score_dataset_list
from app.services.data_acquisition.preprocessing import normalize_gene_ids, preprocess_expression_matrix
from app.services.data_acquisition.validator import validate_expression_matrix


def test_geo_dataset_scoring():
    dataset = {
        "species": "Mouse",
        "tissue": "mammary gland",
        "condition": "Cancer",
        "data_type": "RNA-seq",
        "normal_controls": True,
        "biological_replicates": True,
        "metadata_available": True,
        "expression_available": True,
        "study_quality": "high",
    }
    score, reasons = score_dataset_list([dataset])[0]["suitability_score"], score_dataset_list([dataset])[0]["suitability_reasons"]
    assert score >= 80
    assert any("Mouse" in r for r in reasons)


def test_gene_id_normalization():
    series = pd.Series([
        "ENSG00000141510.17",
        "TP53",
        "ENSG00000234567.9",
        "ENSG00000002586.20_PAR_Y",
        "ENSMUSG00000017146.4",
        "Epb4.1",
    ])
    normalized = normalize_gene_ids(series)
    assert normalized.iloc[0] == "ENSG00000141510"
    assert normalized.iloc[1] == "TP53"
    assert normalized.iloc[3] == "ENSG00000002586_PAR_Y"
    assert normalized.iloc[4] == "ENSMUSG00000017146"
    assert normalized.iloc[5] == "Epb4.1"


def test_preprocessing_preserves_versioned_source_gene_symbols():
    frame = pd.DataFrame({
        "gene_id": ["Epb4.1", "Epb4.2", "Tex19.1", "Tex19.2"],
        "sample_a": [1.0, 2.0, 3.0, 4.0],
    })

    processed, summary = preprocess_expression_matrix(frame)

    assert processed["gene_id"].tolist() == frame["gene_id"].tolist()
    assert summary["n_genes_after"] == 4


def test_preprocessing_and_validation():
    frame = pd.DataFrame({
        "gene_id": ["ENSG00000141510.17", "ENSG00000141510.17", "ENSG00000123456"],
        "gene_symbol": ["TP53", "TP53", "BRCA1"],
        "sample_a": [1.0, 2.0, 3.0],
        "sample_b": [4.0, 5.0, 6.0],
    })
    processed, summary = preprocess_expression_matrix(frame)
    assert processed.shape[0] >= 2
    assert summary["n_genes_after"] >= 2

    csv_path = "./tmp_data_acquisition_validation.csv"
    processed.to_csv(csv_path, index=False)
    result = validate_expression_matrix(csv_path)
    assert result["valid"] is True
    assert result["n_rows"] > 0


def test_dataset_id_alias_is_normalized_in_acquired_manifest(monkeypatch, tmp_path):
    manifest_path = tmp_path / "dataset_manifest.json"
    manifest_path.write_text(json.dumps({
        "datasets": [{
            "dataset_id": "ds-123",
            "name": "Example dataset",
            "repository": "GEO",
            "accession": "GSE12345",
            "species": "Human",
            "tissue": "Breast",
            "status": "ready",
        }]
    }), encoding="utf-8")

    monkeypatch.setattr(dm, "MANIFEST_ROOT", tmp_path)

    datasets = dm.list_acquired_datasets()

    assert datasets[0]["id"] == "ds-123"
    assert datasets[0]["dataset_id"] == "ds-123"


def test_public_candidates_use_real_accessions_and_data_scales():
    candidates = {candidate["id"]: candidate for candidate in data_acquisition.build_candidate_datasets()}

    assert set(candidates) == {
        "gdc-tcga-brca-paired",
        "geo-mouse-gse116385-normal",
        "geo-human-gse205725-normal",
        "geo-mouse-gse155577",
    }
    assert candidates["gdc-tcga-brca-paired"]["accessions"] == ["TCGA-BRCA"]
    assert candidates["geo-mouse-gse116385-normal"]["accessions"] == ["GSE116385"]
    assert candidates["geo-mouse-gse155577"]["accessions"] == ["GSE155577"]
    assert candidates["gdc-tcga-brca-paired"]["normal_controls"] is True
    assert candidates["geo-mouse-gse116385-normal"]["sample_count"] == 8
    assert candidates["geo-mouse-gse116385-normal"]["normal_controls"] is True
    assert candidates["geo-mouse-gse155577"]["normal_controls"] is False

    tcga = data_acquisition._dataset_metadata_from_candidate("gdc-tcga-brca-paired", "Breast Cancer")
    geo = data_acquisition._dataset_metadata_from_candidate("geo-mouse-gse155577", "Breast Cancer")
    normal_mouse = data_acquisition._dataset_metadata_from_candidate(
        "geo-mouse-gse116385-normal", "Breast Cancer"
    )
    assert tcga["data_type"] == "raw_counts"
    assert geo["data_type"] == "normalized"
    assert normal_mouse["data_type"] == "normalized"
    assert tcga["accession"] == "TCGA-BRCA"
    assert geo["accession"] == "GSE155577"
    assert normal_mouse["accession"] == "GSE116385"


def test_tcga_download_supports_parallel_workers():
    import inspect

    from scripts.acquire_real_breast_data import download_tcga_brca_subset

    params = inspect.signature(download_tcga_brca_subset).parameters
    assert "max_workers" in params
    assert params["max_workers"].default >= 2


def test_report_renderer_honors_selected_sections(tmp_path):
    _generate_html_report({
        "title": "Test",
        "analysis_name": "Example",
        "analysis_id": "analysis-1",
        "generated_at": "2026-01-01T00:00:00Z",
        "random_seed": 42,
        "config": {},
        "include_sections": ["deg"],
        "sections": {
            "deg": {"title": "Differential Expression", "table": pd.DataFrame([{"gene": "TP53"}])},
            "networks": {"title": "Network Construction", "table": pd.DataFrame([{"gene": "BRCA1"}])},
        },
    }, str(tmp_path))
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Differential Expression" in report
    assert "Network Construction" not in report
