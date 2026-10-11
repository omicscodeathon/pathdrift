from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import re
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.services.filesystem_runs import (
    list_completed_result_manifests,
    read_result_run_manifest,
    user_can_access_result_run,
)
from app.models import AnalysisRun, AnalysisRunDataset, Dataset, Project, SampleQC, User

router = APIRouter()
logger = logging.getLogger(__name__)
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
FILESYSTEM_RUNS_ROOT = REPOSITORY_ROOT / "results" / "runs"
ACQUISITION_DATASET_MANIFEST = REPOSITORY_ROOT / "data" / "pathdrift" / "manifests" / "dataset_manifest.json"
QC_DATASET_ARTIFACTS = {
    "summary.json",
    "sample_qc.csv",
    "pca_coordinates.csv",
    "sample_correlation.csv",
    "sample_clustering.csv",
    "pca.png",
    "sample_correlation.png",
    "sample_clustering.png",
}
ACCESSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _read_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"QC run metadata could not be read: {path.name}") from exc


def _latest_dataset_qc() -> dict[str, tuple[Path, dict]]:
    latest: dict[str, tuple[str, Path, dict]] = {}
    if not FILESYSTEM_RUNS_ROOT.is_dir():
        return {}
    for run_dir in FILESYSTEM_RUNS_ROOT.iterdir():
        qc_root = run_dir / "qc"
        if not run_dir.is_dir() or not qc_root.is_dir():
            continue
        manifest = _read_json_file(run_dir / "manifest.json")
        run_date = str(manifest.get("created_at") or datetime.fromtimestamp(
            qc_root.stat().st_mtime, tz=timezone.utc
        ).isoformat())
        for dataset_dir in qc_root.iterdir():
            if not dataset_dir.is_dir():
                continue
            summary_path = dataset_dir / "summary.json"
            if not summary_path.is_file():
                continue
            summary = _read_json_file(summary_path)
            accession = str(summary.get("accession") or dataset_dir.name)
            if not ACCESSION_PATTERN.fullmatch(accession):
                continue
            existing = latest.get(accession)
            if existing is None or run_date > existing[0]:
                latest[accession] = (run_date, run_dir, summary)
    return {
        accession: (run_dir, {"summary": summary, "created_at": run_date, "run_id": run_dir.name})
        for accession, (run_date, run_dir, summary) in latest.items()
    }


def _acquisition_dataset_manifest() -> list[dict]:
    try:
        manifest = json.loads(ACQUISITION_DATASET_MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Acquired dataset manifest could not be read.") from exc
    return manifest.get("datasets", [])


def _acquisition_qc_directory(accession: str) -> tuple[Path, dict]:
    if not ACCESSION_PATTERN.fullmatch(accession):
        raise HTTPException(status_code=404, detail="Acquisition QC dataset not found")
    latest = _latest_dataset_qc().get(accession)
    if latest is None:
        raise HTTPException(status_code=404, detail=f"QC results have not been generated for {accession}.")
    run_dir, details = latest
    dataset_dir = (run_dir / "qc" / accession).resolve()
    try:
        dataset_dir.relative_to((FILESYSTEM_RUNS_ROOT / run_dir.name / "qc").resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Acquisition QC dataset not found") from exc
    return dataset_dir, details


@router.get("/acquisition-qc")
async def list_acquisition_qc_datasets(
    current_user: User = Depends(get_current_user),
):
    del current_user
    latest = _latest_dataset_qc()
    datasets = []
    for item in _acquisition_dataset_manifest():
        accession = str(item.get("accession") or "")
        qc_record = latest.get(accession)
        if qc_record is None:
            datasets.append({
                "accession": accession,
                "name": item.get("name", accession),
                "species": item.get("species", "Unknown"),
                "tissue": item.get("tissue", "Not recorded"),
                "condition": item.get("condition", "Not recorded"),
                "status": "QC not available",
                "run_id": None,
                "created_at": None,
                "summary": None,
                "artifacts": [],
            })
            continue
        run_dir, details = qc_record
        dataset_dir = run_dir / "qc" / accession
        summary = details["summary"]
        artifacts = sorted(
            path.name for path in dataset_dir.iterdir()
            if path.is_file() and path.name in QC_DATASET_ARTIFACTS
        )
        datasets.append({
            "accession": accession,
            "name": item.get("name", accession),
            "species": item.get("species", "Unknown"),
            "tissue": item.get("tissue", "Not recorded"),
            "condition": item.get("condition", "Not recorded"),
            "source_data_type": item.get("source_data_type", item.get("data_type", "Not recorded")),
            "gene_identifier_type": item.get("gene_identifier_type", "Ensembl"),
            "status": "QC complete" if QC_DATASET_ARTIFACTS.difference({"summary.json"}).issubset(artifacts) else "QC incomplete",
            "run_id": run_dir.name,
            "created_at": details["created_at"],
            "summary": summary,
            "artifacts": artifacts,
        })
    return datasets


@router.get("/acquisition-qc/{accession}")
async def get_acquisition_qc_dataset(
    accession: str,
    current_user: User = Depends(get_current_user),
):
    del current_user
    dataset_dir, details = _acquisition_qc_directory(accession)
    sample_qc_path = dataset_dir / "sample_qc.csv"
    pca_path = dataset_dir / "pca_coordinates.csv"
    correlation_path = dataset_dir / "sample_correlation.csv"
    clustering_path = dataset_dir / "sample_clustering.csv"
    for required_path in (sample_qc_path, pca_path, correlation_path, clustering_path):
        if not required_path.is_file():
            raise HTTPException(status_code=409, detail=f"QC output is incomplete: {required_path.name}")

    sample_qc = await asyncio.to_thread(pd.read_csv, sample_qc_path)
    pca_coordinates = await asyncio.to_thread(pd.read_csv, pca_path)
    correlation = await asyncio.to_thread(pd.read_csv, correlation_path, index_col=0)
    clustering = await asyncio.to_thread(pd.read_csv, clustering_path)
    sample_by_id = {
        str(row["sample_id"]): row
        for row in json.loads(sample_qc.to_json(orient="records"))
    }
    cluster_by_id = {
        str(row["sample_id"]): row.get("cluster")
        for row in json.loads(clustering.to_json(orient="records"))
    }
    pca_records = json.loads(pca_coordinates.to_json(orient="records"))
    for point in pca_records:
        sample = sample_by_id.get(str(point.get("sample_id")), {})
        point["cluster"] = cluster_by_id.get(str(point.get("sample_id")))
        point["is_outlier"] = sample.get("is_outlier", False)
    return {
        "accession": accession,
        "run_id": details["run_id"],
        "created_at": details["created_at"],
        "summary": details["summary"],
        "sample_qc": list(sample_by_id.values()),
        "pca_coordinates": pca_records,
        "correlation": {
            "samples": correlation.index.astype(str).tolist(),
            "values": json.loads(correlation.to_json(orient="values")),
        },
        "clustering": json.loads(clustering.to_json(orient="records")),
        "artifacts": sorted(
            path.name for path in dataset_dir.iterdir()
            if path.is_file() and path.name in QC_DATASET_ARTIFACTS
        ),
    }


@router.get("/acquisition-qc/{accession}/artifacts/{artifact_name}")
async def get_acquisition_qc_dataset_artifact(
    accession: str,
    artifact_name: str,
    current_user: User = Depends(get_current_user),
):
    del current_user
    if artifact_name not in QC_DATASET_ARTIFACTS:
        raise HTTPException(status_code=404, detail="QC artifact not found")
    dataset_dir, _ = _acquisition_qc_directory(accession)
    artifact_path = (dataset_dir / artifact_name).resolve()
    try:
        artifact_path.relative_to(dataset_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="QC artifact not found") from exc
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="QC artifact not found")
    return FileResponse(artifact_path, filename=artifact_name)


async def _owned_run(
    run_id: str,
    current_user: User,
    db: AsyncSession,
) -> AnalysisRun | dict:
    manifest = read_result_run_manifest(run_id)
    project = manifest.get("project") if manifest else None
    phase3 = manifest.get("phase3") if manifest else None
    if (
        isinstance(project, dict)
        and user_can_access_result_run(manifest, current_user.username, current_user.is_superuser)
        and isinstance(phase3, dict)
        and str(phase3.get("status", "")).upper() == "COMPLETED"
    ):
        return manifest

    run_statement = (
        select(AnalysisRun)
        .join(Project, Project.id == AnalysisRun.project_id)
        .where(AnalysisRun.id == run_id)
    )
    if not current_user.is_superuser:
        run_statement = run_statement.where(Project.owner_id == current_user.id)
    result = await db.execute(run_statement)
    run = result.scalar_one_or_none()
    if run is not None:
        return run

    raise HTTPException(status_code=404, detail="Run not found")


@router.get("/project/{project_id}")
async def list_project_runs(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project_statement = select(Project).where(Project.id == project_id)
    if not current_user.is_superuser:
        project_statement = project_statement.where(Project.owner_id == current_user.id)
    project_result = await db.execute(project_statement)
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    runs_statement = select(AnalysisRun).where(AnalysisRun.project_id == project_id)
    result = await db.execute(runs_statement.order_by(AnalysisRun.created_at.desc()))
    runs = [{
        "id": run.id,
        "status": run.status,
        "stage": run.stage,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "error_message": run.error_message,
        "datasets": run.qc_summary.get("dataset_count", 0) if run.qc_summary else 0,
    } for run in result.scalars().all()]
    known_runs = {run["id"]: run for run in runs}
    for manifest in list_completed_result_manifests(
        project.name,
        None if current_user.is_superuser else current_user.username,
    ):
        run_id = manifest["run_id"]
        filesystem_run = {
            "id": run_id,
            "status": "COMPLETED",
            "stage": "ANALYSIS",
            "created_at": manifest.get("created_at"),
            "completed_at": manifest.get("updated_at") or manifest.get("created_at"),
            "error_message": None,
            "datasets": len(manifest.get("datasets", [])),
        }
        if run_id in known_runs:
            known_runs[run_id].update(filesystem_run)
        else:
            runs.append(filesystem_run)
    return sorted(runs, key=lambda run: str(run.get("created_at") or ""), reverse=True)


@router.get("/saved")
async def list_saved_runs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List saved runs owned by the current user, including filesystem-only results."""
    runs_by_id = {}
    try:
        runs_statement = select(AnalysisRun, Project.name).join(Project, Project.id == AnalysisRun.project_id)
        if not current_user.is_superuser:
            runs_statement = runs_statement.where(Project.owner_id == current_user.id)
        result = await db.execute(runs_statement.order_by(AnalysisRun.created_at.desc()))
        runs_by_id = {
            run.id: {
                "id": run.id,
                "project_name": project_name,
                "status": run.status,
                "stage": run.stage,
                "created_at": run.created_at,
                "completed_at": run.completed_at,
                "error_message": run.error_message,
                "datasets": run.qc_summary.get("dataset_count", 0) if run.qc_summary else 0,
            }
            for run, project_name in result.all()
        }
    except SQLAlchemyError:
        logger.exception("Could not load database-backed runs; falling back to saved run manifests.")

    for manifest in list_completed_result_manifests(
        None,
        None if current_user.is_superuser else current_user.username,
    ):
        run_id = manifest["run_id"]
        project = manifest.get("project") or {}
        runs_by_id[run_id] = {
            "id": run_id,
            "project_name": project.get("name", "Saved analysis"),
            "status": "COMPLETED",
            "stage": "ANALYSIS",
            "created_at": manifest.get("created_at"),
            "completed_at": manifest.get("updated_at") or manifest.get("created_at"),
            "error_message": None,
            "datasets": len(manifest.get("datasets", [])),
        }
    return sorted(
        runs_by_id.values(),
        key=lambda run: str(run.get("completed_at") or run.get("created_at") or ""),
        reverse=True,
    )


@router.get("/{run_id}/datasets")
async def get_run_datasets(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(run_id, current_user, db)
    if isinstance(run, dict):
        phase3_summary = run.get("phase3", {}).get("summary", {})
        stored_datasets = {
            str(dataset.get("accession")): dataset
            for dataset in run.get("datasets", [])
            if isinstance(dataset, dict) and dataset.get("accession")
        }
        result_datasets = phase3_summary.get("datasets", [])
        if not isinstance(result_datasets, list):
            return []
        response = []
        for result_dataset in result_datasets:
            if not isinstance(result_dataset, dict):
                continue
            accession = str(result_dataset.get("accession") or "")
            dataset = stored_datasets.get(accession, {})
            response.append({
                "id": result_dataset.get("dataset_id") or dataset.get("id") or accession,
                "name": dataset.get("name") or accession,
                "source": dataset.get("source"),
                "accession": accession,
                "species": result_dataset.get("species") or dataset.get("species"),
                "tissue": dataset.get("tissue"),
                "platform": dataset.get("platform"),
                "data_type": dataset.get("data_type"),
                "version": dataset.get("version"),
                "sample_count": dataset.get("retained_samples") or dataset.get("initial_samples"),
                "gene_count": dataset.get("retained_genes") or dataset.get("validated_ensembl_genes"),
                "expression_path": None,
                "metadata_path": None,
                "download_date": None,
                "checksum": None,
                "status": dataset.get("status"),
                "provenance": result_dataset,
            })
        return response

    result = await db.execute(
        select(Dataset, AnalysisRunDataset.provenance)
        .join(AnalysisRunDataset, AnalysisRunDataset.dataset_id == Dataset.id)
        .where(AnalysisRunDataset.run_id == run.id)
        .order_by(Dataset.accession)
    )
    return [{
        "id": dataset.id,
        "name": dataset.name,
        "source": dataset.source,
        "accession": dataset.accession,
        "species": dataset.species.value,
        "tissue": dataset.tissue,
        "platform": dataset.platform,
        "data_type": dataset.data_type.value,
        "version": dataset.source_version,
        "sample_count": dataset.n_samples,
        "gene_count": dataset.n_genes,
        "expression_path": dataset.expression_file_path,
        "metadata_path": dataset.metadata_file_path,
        "download_date": dataset.download_date,
        "checksum": dataset.checksum,
        "status": dataset.status,
        "provenance": provenance,
    } for dataset, provenance in result.all()]


@router.get("/{run_id}/qc")
async def get_run_qc(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(run_id, current_user, db)
    if not run.qc_summary:
        raise HTTPException(status_code=409, detail=f"Run QC is not available (status: {run.status})")
    counts = await db.execute(
        select(
            SampleQC.dataset_id,
            func.count(SampleQC.id),
            func.count(SampleQC.id).filter(SampleQC.is_outlier.is_(True)),
            func.count(SampleQC.id).filter(SampleQC.excluded.is_(True)),
        )
        .where(SampleQC.run_id == run.id)
        .group_by(SampleQC.dataset_id)
    )
    return {
        "run_id": run.id,
        "status": run.status,
        "stage": run.stage,
        "summary": run.qc_summary,
        "sample_qc_records": [
            {"dataset_id": dataset_id, "samples": int(total), "outliers": int(outliers), "excluded": int(excluded)}
            for dataset_id, total, outliers, excluded in counts.all()
        ],
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


@router.get("/{run_id}/qc/pca")
async def get_run_pca(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(run_id, current_user, db)
    result = await db.execute(
        select(SampleQC, Dataset.accession, Dataset.species)
        .join(Dataset, Dataset.id == SampleQC.dataset_id)
        .where(SampleQC.run_id == run.id)
        .order_by(Dataset.accession, SampleQC.sample_id)
    )
    points = []
    for qc, accession, species in result.all():
        point = {
            "accession": accession,
            "species": species.value,
            "sample_id": qc.sample_id,
            "cluster": qc.cluster,
            "is_outlier": qc.is_outlier,
            "excluded": qc.excluded,
            "disease_state": (qc.sample_metadata or {}).get("disease_state"),
            "outlier_score": qc.outlier_score,
            "missing_fraction": qc.missing_fraction,
            "zero_fraction": qc.zero_fraction,
            "detected_genes": qc.detected_genes,
            **(qc.pca_coordinates or {}),
        }
        points.append(point)
    if not points:
        raise HTTPException(status_code=409, detail="Persisted PCA coordinates are not available")
    return {"run_id": run.id, "points": points}


@router.get("/{run_id}/qc/correlation")
async def get_run_correlation(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(run_id, current_user, db)
    correlation_path = Path(run.run_dir or "") / "qc" / "sample_correlation.csv"
    if not run.run_dir or not correlation_path.is_file():
        raise HTTPException(status_code=404, detail="Persisted sample-correlation output not found")
    records = await asyncio.to_thread(pd.read_csv, correlation_path)
    return {"run_id": run.id, "pairs": records.to_dict(orient="records")}


@router.get("/{run_id}/qc/clustering")
async def get_run_clustering(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(run_id, current_user, db)
    result = await db.execute(
        select(SampleQC, Dataset.accession, Dataset.species)
        .join(Dataset, Dataset.id == SampleQC.dataset_id)
        .where(SampleQC.run_id == run.id)
        .order_by(Dataset.accession, SampleQC.sample_id)
    )
    rows = result.all()
    if not rows:
        raise HTTPException(status_code=409, detail="Persisted sample clusters are not available")
    return {
        "run_id": run.id,
        "clusters": [{
            "accession": accession,
            "species": species.value,
            "sample_id": qc.sample_id,
            "cluster": qc.cluster,
            "is_outlier": qc.is_outlier,
            "excluded": qc.excluded,
            "outlier_score": qc.outlier_score,
            "missing_fraction": qc.missing_fraction,
            "zero_fraction": qc.zero_fraction,
            "detected_genes": qc.detected_genes,
        } for qc, accession, species in rows],
    }