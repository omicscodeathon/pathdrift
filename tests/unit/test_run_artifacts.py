from __future__ import annotations

from pathlib import Path

from app.api.routes.phase3 import PUBLIC_RESULT_SUFFIXES, _list_public_run_artifacts


def test_list_public_run_artifacts_includes_results_and_excludes_non_downloadables(tmp_path: Path):
    (tmp_path / "deg").mkdir()
    (tmp_path / "ml" / "models").mkdir(parents=True)
    (tmp_path / "deg" / "significant_genes.csv").write_text("gene_id\nTP53\n", encoding="utf-8")
    (tmp_path / "ml" / "phase6_summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ml" / "models" / "model.joblib").write_bytes(b"model")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "secret.csv").write_text("private", encoding="utf-8")

    artifacts = _list_public_run_artifacts(tmp_path)

    assert [artifact["path"] for artifact in artifacts] == [
        "deg/significant_genes.csv",
        "ml/phase6_summary.json",
    ]
    assert all(Path(artifact["path"]).suffix in PUBLIC_RESULT_SUFFIXES for artifact in artifacts)
