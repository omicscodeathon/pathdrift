import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.routes import phase3, phase4
from app.services import filesystem_runs


def _write_phase3_manifest(root, run_id, owner, phase3_status="COMPLETED"):
    run_dir = root / run_id
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({
            "run_id": run_id,
            "created_at": "2026-10-06T12:00:00Z",
            "status": "COMPLETED",
            "project": {"name": "BRCA analysis", "owner_username": owner},
            "phase3": {"status": phase3_status},
        }),
        encoding="utf-8",
    )


def test_completed_run_manifests_are_scoped_or_unrestricted_for_admin(monkeypatch, tmp_path):
    _write_phase3_manifest(tmp_path, "11111111-1111-1111-1111-111111111111", "researcher")
    _write_phase3_manifest(tmp_path, "22222222-2222-2222-2222-222222222222", "another-user")
    _write_phase3_manifest(
        tmp_path,
        "33333333-3333-3333-3333-333333333333",
        "researcher",
        phase3_status="FAILED",
    )
    monkeypatch.setattr(filesystem_runs, "FILESYSTEM_RUNS_ROOT", tmp_path)

    owned = filesystem_runs.list_completed_result_manifests(None, "researcher")
    all_completed = filesystem_runs.list_completed_result_manifests(None, None)

    assert [manifest["run_id"] for manifest in owned] == [
        "11111111-1111-1111-1111-111111111111"
    ]
    assert {manifest["run_id"] for manifest in all_completed} == {
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    }


def test_shared_run_is_listed_only_for_named_user(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    _write_phase3_manifest(tmp_path, run_id, "researcher")
    manifest_path = tmp_path / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["shared_with_usernames"] = ["colly"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(filesystem_runs, "FILESYSTEM_RUNS_ROOT", tmp_path)

    assert [item["run_id"] for item in filesystem_runs.list_completed_result_manifests(None, "colly")] == [run_id]
    assert filesystem_runs.list_completed_result_manifests(None, "unrelated-user") == []


def test_public_run_is_listed_for_every_user(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    _write_phase3_manifest(tmp_path, run_id, "researcher")
    manifest_path = tmp_path / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["visibility"] = "public"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(filesystem_runs, "FILESYSTEM_RUNS_ROOT", tmp_path)

    for username in ("colly", "another-user"):
        assert [
            item["run_id"]
            for item in filesystem_runs.list_completed_result_manifests(None, username)
        ] == [run_id]
        assert filesystem_runs.user_can_access_result_run(manifest, username)


def test_mouse_module_summary_uses_exploratory_deg_counts(monkeypatch):
    run_id = "11111111-1111-1111-1111-111111111111"
    network_id = "22222222-2222-2222-2222-222222222222"
    monkeypatch.setattr(
        phase3,
        "_filesystem_networks",
        lambda _run_id: [{"network_id": network_id, "name": "mouse_cancer"}],
    )
    module_rows = [
        {
            "network_name": "mouse_cancer",
            "module_id": "module_0001",
            "size": "4",
            "density": "0.5",
            "deg_gene_count": "",
            "upregulated_deg_count": "",
            "downregulated_deg_count": "",
        }
    ]
    member_rows = [
        {"network_name": "mouse_cancer", "module_id": "module_0001", "gene_id": "up"},
        {"network_name": "mouse_cancer", "module_id": "module_0001", "gene_id": "down"},
        {"network_name": "mouse_cancer", "module_id": "module_0001", "gene_id": "not-significant"},
        {"network_name": "mouse_cancer", "module_id": "module_0001", "gene_id": "unmatched"},
    ]
    deg_rows = [
        {"gene_id": "up", "significant": "True", "direction": "UPREGULATED"},
        {"gene_id": "down", "significant": "True", "direction": "down"},
        {"gene_id": "not-significant", "significant": "False", "direction": ""},
    ]

    def read_csv(_run_id, path):
        return {
            "deg/mouse/cross_study_exploratory/all_genes.csv": deg_rows,
            "modules/mouse/module_genes.csv": member_rows,
            "modules/mouse/modules.csv": module_rows,
        }.get(path, [])

    monkeypatch.setattr(phase3, "read_result_csv", read_csv)

    modules = phase3._filesystem_modules(run_id, species="mouse")

    assert len(modules) == 1
    assert modules[0]["statistics"]["deg_gene_count"] == 2
    assert modules[0]["statistics"]["upregulated_deg_count"] == 1
    assert modules[0]["statistics"]["downregulated_deg_count"] == 1
    assert modules[0]["statistics"]["non_deg_gene_count"] == 1
    assert modules[0]["statistics"]["deg_genes_tested"] == 3
    assert modules[0]["statistics"]["deg_comparison"] == "cancer_vs_healthy_cross_study_exploratory"


def test_mouse_deg_rows_distinguish_untestable_from_not_significant(monkeypatch):
    rows = [
        {
            "gene_id": "ENSMUSG_UNTESTABLE",
            "gene_symbol": "Myf5",
            "log2fc": "2.6867",
            "pvalue": "",
            "adjusted_p_value": "",
            "statistic": "",
            "average_expression": "1.3434",
            "direction": "NOT_SIGNIFICANT",
            "significant": "False",
            "method": "Welch's t-test + Benjamini-Hochberg",
        },
        {
            "gene_id": "ENSMUSG_TESTED",
            "gene_symbol": "Cdh1",
            "log2fc": "0.1",
            "pvalue": "0.5",
            "adjusted_p_value": "0.8",
            "statistic": "0.7",
            "average_expression": "2.0",
            "direction": "NOT_SIGNIFICANT",
            "significant": "False",
            "method": "Welch's t-test + Benjamini-Hochberg",
        },
    ]
    monkeypatch.setattr(
        phase3,
        "read_result_csv",
        lambda _run_id, path: rows if path.endswith("cross_study_exploratory/all_genes.csv") else [],
    )

    result = phase3._filesystem_deg_page(
        "11111111-1111-1111-1111-111111111111",
        "mouse",
        "cancer_vs_healthy_cross_study_exploratory",
        False,
        10,
        0,
    )

    untestable, tested = (
        next(item for item in result["items"] if item["gene_id"] == "ENSMUSG_UNTESTABLE"),
        next(item for item in result["items"] if item["gene_id"] == "ENSMUSG_TESTED"),
    )
    assert untestable["testable"] is False
    assert untestable["direction"] == "not_testable"
    assert untestable["gene_symbol"] == "Myf5"
    assert tested["testable"] is True
    assert tested["direction"] == "not_significant"


def test_human_significant_deg_uses_saved_significant_genes_artifact(monkeypatch):
    significant_rows = [{
        "gene_id": "ENSG00000123500",
        "gene_symbol": "",
        "log2fc": "7.97",
        "pvalue": "2.2e-42",
        "adjusted_p_value": "5.0e-38",
        "statistic": "13.6",
        "base_mean": "3057.3",
        "average_expression": "3057.3",
        "direction": "UPREGULATED",
        "significant": "True",
        "method": "PyDESeq2 (DESeq2 Wald test)",
    }]
    paths_read = []

    def read_csv(_run_id, path):
        paths_read.append(path)
        if path == "deg/human/significant_genes.csv":
            return significant_rows
        return []

    monkeypatch.setattr(phase3, "read_result_csv", read_csv)
    result = phase3._filesystem_deg_page(
        "11111111-1111-1111-1111-111111111111",
        "human",
        None,
        True,
        10,
        0,
    )

    assert "deg/human/significant_genes.csv" in paths_read
    assert [item["gene_id"] for item in result["items"]] == ["ENSG00000123500"]


@pytest.mark.asyncio
async def test_phase4_endpoints_serve_saved_run_artifacts(monkeypatch):
    run_id = "11111111-1111-1111-1111-111111111111"
    run_manifest = {"run_id": run_id, "phase3": {"status": "COMPLETED"}}
    csv_rows = {
        "orthology/orthologs.csv": [{
            "human_ensembl_id": "ENSG1",
            "mouse_ensembl_id": "ENSMUSG1",
            "confidence": "1",
        }],
        "cross_species/node_alignment.csv": [{
            "human_ensembl_id": "ENSG1",
            "mouse_ensembl_id": "ENSMUSG1",
            "human_network_present": "True",
            "mouse_network_present": "False",
            "is_primary": "True",
        }],
        "cross_species/edge_alignment.csv": [{
            "human_source_gene": "ENSG1",
            "human_target_gene": "ENSG2",
            "mouse_source_gene": "ENSMUSG1",
            "mouse_target_gene": "",
            "status": "UNMAPPABLE",
        }],
        "drift/gene_drift.csv": [{
            "human_ensembl_id": "ENSG1",
            "mouse_ensembl_id": "ENSMUSG1",
            "drift_score": "0.9",
        }],
        "drift/edge_drift.csv": [{
            "human_source_gene": "ENSG1",
            "human_target_gene": "ENSG2",
            "status": "LOST",
        }],
        "drift/module_drift.csv": [{
            "human_module_id": "module_1",
            "candidate_mouse_module_id": "module_2",
            "module_conservation_score": "0.75",
        }],
    }
    json_rows = {
        "orthology/orthology_summary.json": {"total_orthology_mappings": 1},
        "cross_species/network_conservation_summary.json": {"conserved_edges": 1},
        "drift/drift_summary.json": {
            "aligned_gene_count": 1,
            "mean_gene_drift_score": 0.9,
            "edge_status_counts": {"LOST": 1},
        },
    }

    async def authorize(*_args):
        return run_manifest

    monkeypatch.setattr(phase4, "_authorize", authorize)
    monkeypatch.setattr(phase4, "read_result_csv", lambda _run_id, path: csv_rows.get(path, []))
    monkeypatch.setattr(phase4, "_filesystem_json", lambda _run_id, path: json_rows[path])
    user = type("UserStub", (), {"username": "researcher", "is_superuser": False})()

    orthology = await phase4.get_run_orthology(run_id, 50, 0, user, object())
    orthology_summary = await phase4.get_run_orthology_summary(run_id, user, object())
    nodes = await phase4.get_run_cross_species_nodes(run_id, 50, 0, user, object())
    edges = await phase4.get_run_cross_species_edges(run_id, 50, 0, None, user, object())
    cross_summary = await phase4.get_run_cross_species_summary(run_id, user, object())
    genes = await phase4.get_run_drift_genes(run_id, 50, 0, user, object())
    drift_edges = await phase4.get_run_drift_edges(run_id, 50, 0, None, user, object())
    modules = await phase4.get_run_drift_modules(run_id, 50, 0, user, object())
    drift_summary = await phase4.get_run_drift_summary(run_id, user, object())

    assert orthology["items"][0]["confidence"] == 1
    assert orthology["items"][0]["is_primary"] is None
    assert orthology_summary["total_orthology_mappings"] == 1
    assert nodes["items"][0]["human_network_present"] is True
    assert nodes["items"][0]["mouse_network_present"] is False
    assert edges["items"][0]["status"] == "UNMAPPABLE"
    assert edges["items"][0]["human_source_gene_id"] == "ENSG1"
    assert cross_summary["aligned_gene_count"] == 1
    assert cross_summary["edge_status_counts"]["LOST"] == 1
    assert genes["items"][0]["id"] == "ENSG1:ENSMUSG1"
    assert drift_edges["items"][0]["status"] == "LOST"
    assert modules["items"][0]["id"] == "module_1:module_2"
    assert drift_summary["mean_gene_drift_score"] == 0.9


@pytest.mark.asyncio
async def test_mouse_cross_study_table_endpoint_pages_only_allowed_artifacts(monkeypatch):
    run_id = "11111111-1111-1111-1111-111111111111"
    rows = [{"sample_id": f"sample-{index}", "disease_state": "healthy"} for index in range(3)]
    paths_read = []

    async def authorize_run(*_args):
        return {"run_id": run_id}

    def read_csv(_run_id, path):
        paths_read.append(path)
        return rows

    monkeypatch.setattr(phase3, "_owned_run", authorize_run)
    monkeypatch.setattr(phase3, "read_result_csv", read_csv)
    user = type("UserStub", (), {"username": "researcher", "is_superuser": False})()

    result = await phase3.get_run_deg_table(
        run_id,
        "mouse",
        "sample_metadata.csv",
        "cancer_vs_healthy_cross_study_exploratory",
        2,
        1,
        object(),
        user,
    )

    assert paths_read == [str(Path("deg") / "mouse" / "cross_study_exploratory" / "sample_metadata.csv")]
    assert result["total"] == 3
    assert [row["sample_id"] for row in result["items"]] == ["sample-1", "sample-2"]


@pytest.mark.asyncio
async def test_shared_run_is_authorized_for_phase3_results(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    _write_phase3_manifest(tmp_path, run_id, "researcher")
    manifest_path = tmp_path / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["shared_with_usernames"] = ["colly"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(phase3, "FILESYSTEM_RUNS_ROOT", tmp_path)
    monkeypatch.setattr(filesystem_runs, "FILESYSTEM_RUNS_ROOT", tmp_path)

    user = type("UserStub", (), {"username": "colly", "is_superuser": False})()
    result = await phase3._owned_run(run_id, db=object(), user=user)

    assert result["run_id"] == run_id


@pytest.mark.asyncio
async def test_public_run_is_authorized_for_any_authenticated_phase3_user(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    _write_phase3_manifest(tmp_path, run_id, "researcher")
    manifest_path = tmp_path / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["visibility"] = "public"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(phase3, "FILESYSTEM_RUNS_ROOT", tmp_path)
    monkeypatch.setattr(filesystem_runs, "FILESYSTEM_RUNS_ROOT", tmp_path)

    user = type("UserStub", (), {"username": "any-user", "is_superuser": False})()
    result = await phase3._owned_run(run_id, db=object(), user=user)

    assert result["run_id"] == run_id


@pytest.mark.asyncio
async def test_saved_deg_artifacts_are_listed_and_served_from_run_directory(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    mouse_dir = tmp_path / run_id / "deg" / "mouse" / "cross_study_exploratory"
    mouse_dir.mkdir(parents=True)
    volcano_path = mouse_dir / "volcano.png"
    volcano_path.write_bytes(b"figure")
    (mouse_dir / "all_genes.csv").write_text("gene_id\nENSMUSG1\n", encoding="utf-8")
    monkeypatch.setattr(phase3, "FILESYSTEM_RUNS_ROOT", tmp_path)

    async def allow_run(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(phase3, "_owned_run", allow_run)
    artifacts = await phase3.list_run_deg_artifacts(
        run_id, "mouse", "cancer_vs_healthy_cross_study_exploratory",
        db=object(), current_user=object(),
    )
    response = await phase3.get_run_deg_artifact(
        run_id, "mouse", "volcano.png",
        comparison="cancer_vs_healthy_cross_study_exploratory",
        db=object(), current_user=object(),
    )

    assert artifacts["items"] == ["all_genes.csv", "volcano.png"]
    assert Path(response.path) == volcano_path


@pytest.mark.asyncio
async def test_saved_deg_artifacts_reject_path_traversal(monkeypatch, tmp_path):
    run_id = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(phase3, "FILESYSTEM_RUNS_ROOT", tmp_path)

    async def allow_run(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(phase3, "_owned_run", allow_run)
    with pytest.raises(HTTPException) as error:
        await phase3.get_run_deg_artifact(
            run_id, "human", "../manifest.json",
            db=object(), current_user=object(),
        )
    assert error.value.status_code == 404
