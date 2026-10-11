import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from app.api.routes import runs


def _write_dataset_qc_run(root, run_id, created_at, accession, sample_id):
    run_dir = root / run_id
    qc_dir = run_dir / "qc" / accession
    qc_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"status": "COMPLETED", "created_at": created_at}),
        encoding="utf-8",
    )
    (qc_dir / "summary.json").write_text(json.dumps({
        "initial_samples": 1,
        "retained_samples": 1,
        "initial_genes": 10,
        "retained_genes": 8,
        "normalization_method": "none",
        "outliers": [],
    }), encoding="utf-8")
    pd.DataFrame([{
        "sample_id": sample_id, "disease_state": "healthy", "cluster": 1,
        "detected_genes": 8, "missing_fraction": 0, "zero_fraction": 0.2,
        "outlier_score": 0, "is_outlier": False, "excluded": False,
    }]).to_csv(qc_dir / "sample_qc.csv", index=False)
    pd.DataFrame([{"sample_id": sample_id, "PC1": 0.5, "PC2": -0.2}]).to_csv(
        qc_dir / "pca_coordinates.csv", index=False
    )
    pd.DataFrame({"": [sample_id], sample_id: [1.0]}).to_csv(
        qc_dir / "sample_correlation.csv", index=False
    )
    pd.DataFrame([{"sample_id": sample_id, "cluster": 1}]).to_csv(
        qc_dir / "sample_clustering.csv", index=False
    )
    for image in ("pca.png", "sample_correlation.png", "sample_clustering.png"):
        (qc_dir / image).write_bytes(b"dataset-specific plot")
    return run_dir


def test_acquisition_qc_deduplicates_runs_and_returns_mouse_and_pca(monkeypatch, tmp_path):
    _write_dataset_qc_run(tmp_path, "old-run", "2026-10-04T10:00:00Z", "TCGA-BRCA", "H1")
    _write_dataset_qc_run(tmp_path, "new-run", "2026-10-05T10:00:00Z", "TCGA-BRCA", "H2")
    _write_dataset_qc_run(tmp_path, "mouse-run", "2026-10-05T11:00:00Z", "GSE155577", "M1")
    monkeypatch.setattr(runs, "FILESYSTEM_RUNS_ROOT", tmp_path)
    monkeypatch.setattr(runs, "ACQUISITION_DATASET_MANIFEST", tmp_path / "dataset_manifest.json")
    runs.ACQUISITION_DATASET_MANIFEST.write_text(json.dumps({"datasets": [
        {"accession": "TCGA-BRCA", "species": "Human", "name": "Human cohort"},
        {"accession": "GSE155577", "species": "Mouse", "name": "Mouse cohort"},
    ]}), encoding="utf-8")

    datasets = asyncio.run(runs.list_acquisition_qc_datasets(current_user=None))
    assert [item["accession"] for item in datasets] == ["TCGA-BRCA", "GSE155577"]
    assert datasets[0]["run_id"] == "new-run"
    assert datasets[0]["status"] == "QC complete"
    assert datasets[1]["species"] == "Mouse"

    report = asyncio.run(runs.get_acquisition_qc_dataset("GSE155577", current_user=None))
    assert report["sample_qc"][0]["sample_id"] == "M1"
    assert report["pca_coordinates"][0]["PC1"] == 0.5
    plot = asyncio.run(runs.get_acquisition_qc_dataset_artifact("GSE155577", "pca.png", current_user=None))
    assert Path(plot.path).resolve() == (tmp_path / "mouse-run" / "qc" / "GSE155577" / "pca.png").resolve()

    with pytest.raises(HTTPException) as error:
        asyncio.run(runs.get_acquisition_qc_dataset_artifact("../outside", "pca.png", current_user=None))
    assert error.value.status_code == 404
