from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from .downloader import DownloadReceipt, copy_cached_file


GDC_API = "https://api.gdc.cancer.gov"


def verify_gdc_project(project_id: str, workflow: str, metadata_path: str | Path) -> dict[str, Any]:
    with httpx.Client(timeout=60) as client:
        project_response = client.get(f"{GDC_API}/projects/{project_id}")
        project_response.raise_for_status()
        project = project_response.json().get("data", {})
        if project.get("project_id") != project_id:
            raise ValueError(f"GDC project lookup did not confirm {project_id}")

        metadata = pd.read_csv(metadata_path, sep="\t", dtype=str).fillna("")
        if "file_uuid" not in metadata or metadata["file_uuid"].eq("").any():
            raise ValueError("GDC sample metadata must retain each source file UUID")
        file_ids = sorted(metadata["file_uuid"].unique().tolist())
        file_response = client.post(
            f"{GDC_API}/files",
            json={
                "filters": {"op": "in", "content": {"field": "file_id", "value": file_ids}},
                "fields": "file_id,file_name,md5sum,file_size,data_type,analysis.workflow_type,cases.project.project_id",
                "format": "JSON",
                "size": len(file_ids),
            },
        )
        file_response.raise_for_status()
    hits = file_response.json().get("data", {}).get("hits", [])
    records = {str(hit.get("file_id")): hit for hit in hits}
    missing = sorted(set(file_ids) - set(records))
    if missing:
        raise ValueError(f"GDC no longer resolves source file IDs: {missing[:5]}")

    verified_files = []
    for file_id, hit in records.items():
        analyses = hit.get("analysis") or []
        if isinstance(analyses, dict):
            analyses = [analyses]
        workflows = {str(item.get("workflow_type", "")) for item in analyses}
        projects = {
            str(project_record.get("project_id", ""))
            for case in hit.get("cases", [])
            for project_record in [case.get("project") or {}]
        }
        if workflow not in workflows:
            raise ValueError(f"GDC file {file_id} does not use configured workflow {workflow}")
        if projects and project_id not in projects:
            raise ValueError(f"GDC file {file_id} does not belong to {project_id}")
        verified_files.append({
            "file_id": file_id,
            "file_name": hit.get("file_name"),
            "md5sum": hit.get("md5sum"),
            "file_size": hit.get("file_size"),
            "data_type": hit.get("data_type"),
            "workflow": workflow,
            "project": project_id,
        })
    return {
        "project": project,
        "project_id": project_id,
        "workflow": workflow,
        "source_files": verified_files,
        "retrieval_url": f"{GDC_API}/projects/{project_id}",
    }


def acquire_gdc(config: dict[str, Any], raw_dir: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    target_dir = Path(raw_dir)
    accession = str(config.get("project", "")).strip()
    if not accession:
        raise ValueError("Human dataset config must specify a GDC project")
    workflow = str(config.get("workflow", "STAR - Counts"))
    source_expression = config.get("expression_file")
    source_metadata = config.get("metadata_file")
    if not source_expression or not source_metadata:
        source_expression, source_metadata = download_gdc_brca(config, target_dir / "source_download")
    expression_path = target_dir / f"{accession}_expression.tsv.gz"
    metadata_path = target_dir / f"{accession}_metadata.tsv"
    expression_receipt = copy_cached_file(
        source_expression,
        expression_path,
        expected_sha256=config.get("expression_sha256"),
    )
    metadata_receipt = copy_cached_file(
        source_metadata,
        metadata_path,
        expected_sha256=config.get("metadata_sha256"),
    )
    source_info = verify_gdc_project(accession, workflow, metadata_path)
    source_info.update({
        "source": "GDC",
        "accession": accession,
        "data_type": "raw_counts",
        "expression": expression_receipt.__dict__,
        "metadata": metadata_receipt.__dict__,
        "file_ids": source_info["source_files"],
    })
    return expression_path, metadata_path, source_info


def download_gdc_brca(config: dict[str, Any], raw_dir: str | Path) -> tuple[Path, Path]:
    """Download a configured GDC subset using the existing official API client."""
    if config.get("project") != "TCGA-BRCA":
        raise ValueError("The built-in GDC downloader currently supports TCGA-BRCA only")
    backend_root = Path(__file__).resolve().parents[2] / "backend"
    sys.path.insert(0, str(backend_root))
    from scripts.acquire_real_breast_data import download_tcga_brca_subset

    limit = int(config.get("max_samples_per_group", 10))
    expression, metadata = download_tcga_brca_subset(Path(raw_dir), limit_per_group=limit)
    return Path(expression), Path(metadata)