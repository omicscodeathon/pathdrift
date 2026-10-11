import app.main
from types import SimpleNamespace

from app.tasks import analysis_tasks


def test_analysis_routes_exist():
    routes = [r.path for r in app.main.app.routes]
    assert "/api/v1/analyses/" in routes
    assert "/api/v1/analyses/{analysis_id}" in routes or any(path.startswith("/api/v1/analyses/") for path in routes)
    assert "/api/v1/datasets/{dataset_id}/quality" in routes
    assert "/api/v1/deg/project/{project_id}" in routes
    assert "/api/v1/networks/project/{project_id}" in routes
    assert "/api/v1/networks/{network_id}/genes/{gene_id}" in routes
    assert "/api/v1/networks/{network_id}/modules" in routes
    assert "/api/v1/networks/{network_id}/modules/{module_id}/enrichment" in routes
    assert "/api/v1/cross-species/project/{project_id}" in routes
    assert "/api/v1/cross-species/{cs_id}/network-alignment" in routes
    assert "/api/v1/drift/project/{project_id}" in routes
    assert "/api/v1/drift/{drift_id}/summary" in routes
    assert "/api/v1/cross-species/{cs_id}/genes/{gene_id}/network-drift" in routes
    assert "/api/v1/gene-loss/evidence/{comparison_id}" in routes
    assert "/api/v1/ppi/network" in routes
    assert "/api/v1/projects/{project_id}/dashboard-summary" in routes


def test_network_analysis_uses_its_configured_preprocessing_job(monkeypatch):
    db = SimpleNamespace()
    network = SimpleNamespace(dataset_id="dataset-id", preprocessing_job_id="preprocessing-id")
    captured = {}

    monkeypatch.setattr(
        analysis_tasks,
        "_load_analysis_data",
        lambda _db, dataset_id, preprocessing_job_id: captured.update(
            dataset_id=dataset_id,
            preprocessing_job_id=preprocessing_job_id,
        ),
    )

    analysis_tasks._load_network_analysis_data(db, network)

    assert captured == {"dataset_id": "dataset-id", "preprocessing_job_id": "preprocessing-id"}
