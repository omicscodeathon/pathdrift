from __future__ import annotations

import json
import hashlib
import uuid
import gzip
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select

from app.db.base import get_db
from app.api.deps import get_current_user
from app.bio.identifiers import enforce_ensembl_gene_ids
from app.models import DataTypeEnum, Dataset, Project, SpeciesEnum, User
from app.schemas.data_acquisition import (
    AcquiredDataset,
    DatasetCandidate,
    DatasetSelectionRequest,
    DownloadRequest,
    JobStatusResponse,
    ProcessingRequest,
    SamplePreview,
    SearchResponse,
    ValidationRequest,
)
from app.services.data_acquisition.dataset_manager import (
    DATA_ROOT,
    PROCESSED_ROOT,
    RAW_ROOT,
    UPLOAD_ROOT,
    ensure_data_directories,
    list_acquired_datasets,
    write_manifest,
)
from app.services.data_acquisition.dataset_scoring import score_dataset_list
from app.services.data_acquisition.preprocessing import preprocess_expression_matrix
from app.services.data_acquisition.validator import validate_expression_matrix

router = APIRouter()
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
REPOSITORY_DATASET_MANIFEST = REPOSITORY_ROOT / "data" / "pathdrift" / "manifests" / "dataset_manifest.json"
DEFAULT_EXPRESSION_PAGE_SIZE = 100
MAX_EXPRESSION_PAGE_SIZE = 250


def _manifest_datasets() -> List[Dict[str, Any]]:
    if not REPOSITORY_DATASET_MANIFEST.is_file():
        return []
    try:
        manifest = json.loads(REPOSITORY_DATASET_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="The repository dataset manifest is invalid JSON.") from exc

    datasets = []
    for item in manifest.get("datasets", []):
        normalized = dict(item)
        for field in ("raw_expression_path", "metadata_path", "processed_expression_path"):
            value = normalized.get(field)
            if not value:
                continue
            path_value = str(value).replace("\\", "/")
            if len(path_value) > 2 and path_value[1:3] == ":/":
                marker = "/data/pathdrift/"
                marker_index = path_value.lower().rfind(marker)
                if marker_index < 0:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Dataset manifest path for {field} is outside the repository.",
                    )
                path = REPOSITORY_ROOT / path_value[marker_index + 1:]
            else:
                path = Path(path_value)
            if not path.is_absolute():
                path = REPOSITORY_ROOT / path
            try:
                normalized[field] = path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
            except ValueError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Dataset manifest path for {field} is outside the repository.",
                ) from exc
        datasets.append(normalized)
    return datasets


def _find_manifest_dataset(dataset_id: str) -> Dict[str, Any]:
    for dataset in _manifest_datasets():
        if dataset_id in {str(dataset.get("id", "")), str(dataset.get("dataset_id", "")), str(dataset.get("accession", ""))}:
            return dataset
    raise HTTPException(status_code=404, detail="Acquired dataset not found in the repository manifest.")


def _repository_data_path(relative_path: str) -> Path:
    path = (REPOSITORY_ROOT / relative_path).resolve()
    try:
        path.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Dataset manifest contains a path outside the repository.") from exc
    return path


@lru_cache(maxsize=16)
def _count_expression_rows(path_string: str, modified_ns: int) -> int:
    del modified_ns
    path = Path(path_string)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _build_manifest_preview(
    dataset: Dict[str, Any],
    offset: int = 0,
    limit: int = DEFAULT_EXPRESSION_PAGE_SIZE,
) -> Dict[str, Any]:
    import pandas as pd

    expression_path = dataset.get("raw_expression_path")
    if not expression_path:
        raise HTTPException(status_code=404, detail="Expression matrix path is not recorded for this dataset.")
    expression_file = _repository_data_path(expression_path)
    if not expression_file.is_file():
        raise HTTPException(status_code=404, detail="Expression matrix file is not available.")

    total_rows = _count_expression_rows(str(expression_file), expression_file.stat().st_mtime_ns)
    expression = pd.read_csv(
        expression_file,
        sep="\t",
        compression="infer",
        skiprows=range(1, offset + 1) if offset else None,
        nrows=limit,
        low_memory=False,
    )
    expression_columns = [str(column) for column in expression.columns]
    expression_rows = [
        [
            None if pd.isna(value) else value.item() if hasattr(value, "item") else value
            for value in row
        ]
        for row in expression.itertuples(index=False, name=None)
    ]

    metadata_columns: List[str] = []
    metadata_rows: List[List[Any]] = []
    metadata_path = dataset.get("metadata_path")
    if metadata_path:
        metadata_file = _repository_data_path(metadata_path)
        if not metadata_file.is_file():
            raise HTTPException(status_code=404, detail="Sample metadata file is not available.")
        metadata = pd.read_csv(metadata_file, sep="\t", low_memory=False)
        metadata_columns = [str(column) for column in metadata.columns]
        metadata_rows = [
            [None if pd.isna(value) else value.item() if hasattr(value, "item") else value for value in row]
            for row in metadata.itertuples(index=False, name=None)
        ]

    return {
        "dataset_id": dataset.get("id") or dataset.get("dataset_id") or dataset.get("accession"),
        "expression": {
            "columns": expression_columns,
            "rows": expression_rows,
            "offset": offset,
            "limit": limit,
            "total_rows": total_rows,
        },
        "sample_metadata": {"columns": metadata_columns, "rows": metadata_rows},
    }


def build_candidate_datasets() -> List[Dict[str, Any]]:
    candidates = [
        {
            "id": "gdc-tcga-brca-paired",
            "name": "TCGA-BRCA Tumor and Adjacent Normal",
            "repository": "GDC / TCGA",
            "species": "Human",
            "condition": "Primary Tumor + Solid Tissue Normal",
            "tissue": "Breast",
            "sample_count": 19,
            "data_type": "Raw STAR counts",
            "expression_available": True,
            "metadata_available": True,
            "study_quality": "high",
            "normal_controls": True,
            "biological_replicates": True,
            "source_url": "https://portal.gdc.cancer.gov/projects/TCGA-BRCA",
            "accessions": ["TCGA-BRCA"],
            "platform": "Illumina sequencing; GDC STAR - Counts workflow",
            "genome_build": "GRCh38 (GDC STAR - Counts; GENCODE v36 gene model)",
            "source_data_type": "RNA-Seq unstranded gene counts",
        },
        {
            "id": "geo-mouse-gse116385-normal",
            "name": "Normal Mouse Mammary Gland RNA-seq",
            "repository": "GEO",
            "species": "Mouse",
            "condition": "Normal",
            "tissue": "Mammary gland",
            "sample_count": 8,
            "data_type": "RNA-seq RPKM expression",
            "expression_available": True,
            "metadata_available": True,
            "study_quality": "good",
            "normal_controls": True,
            "biological_replicates": True,
            "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE116385",
            "accessions": ["GSE116385"],
            "platform": "RNA sequencing",
            "genome_build": "Not reported in GEO series metadata",
            "source_data_type": "RPKM expression; mouse gene symbols",
        },
        {
            "id": "geo-human-gse205725-normal",
            "name": "Healthy Human Breast Tissue (Komen Tissue Bank)",
            "repository": "GEO",
            "species": "Human",
            "condition": "Normal",
            "tissue": "Breast",
            "sample_count": 190,
            "data_type": "RNA-seq raw gene counts",
            "expression_available": True,
            "metadata_available": True,
            "study_quality": "high",
            "normal_controls": True,
            "biological_replicates": True,
            "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE205725",
            "accessions": ["GSE205725"],
            "platform": "Illumina RNA sequencing",
            "genome_build": "Not reported in GEO series metadata",
            "source_data_type": "FeatureCounts gene counts",
        },
        {
            "id": "geo-mouse-gse155577",
            "name": "Mouse Mammary Tumor Transcriptomes",
            "repository": "GEO",
            "species": "Mouse",
            "condition": "Cancer",
            "tissue": "Mammary tumor",
            "sample_count": 26,
            "data_type": "Normalized expression",
            "expression_available": True,
            "metadata_available": True,
            "study_quality": "good",
            "normal_controls": False,
            "biological_replicates": True,
            "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE155577",
            "accessions": ["GSE155577"],
            "platform": "Illumina HiSeq 1000",
            "genome_build": "Not reported in GEO series/sample metadata",
            "source_data_type": "Study-normalized RNA-Seq expression values",
        },
    ]
    return score_dataset_list(candidates)


jobs_store: Dict[str, Dict[str, Any]] = {}


def _dataset_metadata_from_candidate(dataset_id: str, disease: str) -> Dict[str, Any]:
    candidate_map = {item["id"]: item for item in build_candidate_datasets()}
    candidate = candidate_map.get(dataset_id, {})
    accession = (candidate.get("accessions") or [dataset_id])[0]
    species = (candidate.get("species") or "Human").strip()
    tissue = candidate.get("tissue") or "Breast"
    return {
        "id": dataset_id,
        "dataset_id": dataset_id,
        "name": candidate.get("name") or dataset_id.replace("-", " ").title(),
        "repository": candidate.get("repository") or "Downloaded dataset",
        "accession": accession,
        "species": species,
        "tissue": tissue,
        "condition": candidate.get("condition") or "Downloaded",
        "disease": disease or "Breast Cancer",
        "data_type": "raw_counts" if dataset_id.startswith("gdc-") or dataset_id == "geo-human-gse205725-normal" else "normalized",
        "source_data_type": candidate.get("source_data_type"),
        "platform": candidate.get("platform"),
        "genome_build": candidate.get("genome_build"),
        "download_date": datetime.now(timezone.utc).date().isoformat(),
        "sample_count": 0,
        "n_samples": 0,
        "gene_count": 0,
        "n_genes": 0,
        "status": "queued",
        "is_validated": False,
        "suitability_score": candidate.get("suitability_score") or 0,
        "source_url": candidate.get("source_url"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def _create_job(message: str = "Searching...") -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    jobs_store[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "error_message": None,
    }
    return jobs_store[job_id]


def _acquire_and_preprocess(candidate_id: str, dataset_id: str) -> Dict[str, Any]:
    import pandas as pd
    from app.bio.preprocessing import PreprocessingPipeline
    from app.services.data_acquisition.dataset_manager import PROCESSED_ROOT, RAW_ROOT
    from scripts.acquire_real_breast_data import (
        download_geo_normal_mammary,
        download_geo_series,
        download_geo_healthy_breast_counts,
        download_tcga_brca_subset,
    )

    source_dir = "gdc" if candidate_id.startswith("gdc-") else "geo"
    raw_dir = RAW_ROOT / source_dir / dataset_id
    processed_dir = PROCESSED_ROOT / source_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    if candidate_id == "gdc-tcga-brca-paired":
        expression_path, metadata_path = download_tcga_brca_subset(raw_dir, limit_per_group=6, max_workers=4)
        normalization_method = "log2cpm"
        species = "Human"
    elif candidate_id == "geo-mouse-gse155577":
        expression_path, metadata_path = download_geo_series("GSE155577", raw_dir)
        normalization_method = "none"
        species = "Mouse"
    elif candidate_id == "geo-mouse-gse116385-normal":
        expression_path, metadata_path = download_geo_normal_mammary(raw_dir)
        normalization_method = "none"
        species = "Mouse"
    elif candidate_id == "geo-human-gse205725-normal":
        expression_path, metadata_path = download_geo_healthy_breast_counts(raw_dir)
        normalization_method = "log2cpm"
        species = "Human"
    else:
        raise ValueError(f"Unsupported real-data source: {candidate_id}")

    expression = pd.read_csv(expression_path, sep="\t", compression="gzip", low_memory=False)
    if "gene_id" not in expression.columns:
        raise ValueError(f"Downloaded expression matrix is missing gene_id: {expression_path}")
    expression = expression.set_index("gene_id")
    expected_species = "human" if species == "Human" else "mouse"
    if candidate_id == "geo-mouse-gse116385-normal":
        excluded_gene_ids = []
    else:
        expression, excluded_gene_ids = enforce_ensembl_gene_ids(expression, expected_species)
    metadata = pd.read_csv(metadata_path, sep="\t")
    if "sample_id" not in metadata.columns or "disease_state" not in metadata.columns:
        raise ValueError(f"Downloaded sample metadata has invalid columns: {metadata_path}")
    metadata["sample_id"] = metadata["sample_id"].astype(str)
    expression.columns = expression.columns.astype(str)
    matched_samples = [sample for sample in metadata["sample_id"] if sample in expression.columns]
    if not matched_samples:
        raise ValueError("Downloaded metadata contains no sample IDs present in the expression matrix")
    expression = expression.loc[:, matched_samples]
    metadata = metadata.drop_duplicates("sample_id").set_index("sample_id").loc[matched_samples].reset_index()

    pipeline = PreprocessingPipeline(
        normalization_method=normalization_method,
        low_expr_threshold=1.0 if normalization_method == "log2cpm" else 0.0,
        low_expr_min_samples=3 if normalization_method == "log2cpm" else 1,
        min_gene_variance=0.0,
        outlier_detection=False,
    )
    processed, log = pipeline.run(expression, metadata, dataset_id, species)
    processed_path = processed_dir / f"{dataset_id}_processed.parquet"
    processed.to_parquet(processed_path)

    labels = metadata["disease_state"].str.lower()
    return {
        "expression_path": str(expression_path),
        "metadata_path": str(metadata_path),
        "processed_path": str(processed_path),
        "n_genes": int(processed.shape[0]),
        "n_samples": int(processed.shape[1]),
        "n_healthy": int(labels.isin(["healthy", "normal", "control"]).sum()),
        "n_cancer": int((~labels.isin(["healthy", "normal", "control"])).sum()),
        "normalization_method": normalization_method,
        "preprocessing_log": log.to_text(),
        "expression_sha256": hashlib.sha256(expression_path.read_bytes()).hexdigest(),
        "excluded_unmapped_gene_ids": excluded_gene_ids,
    }


def _run_acquisition_job(job_id: str, user_id: str, selections: List[Dict[str, Any]], disease: str) -> None:
    from app.tasks.analysis_tasks import get_sync_db

    db = get_sync_db()
    job = jobs_store[job_id]
    job.update({"status": "running", "progress": 5, "message": "Connecting to public data repositories..."})
    try:
        manifest_datasets = list_acquired_datasets()
        for index, selection in enumerate(selections, start=1):
            candidate_id = selection["candidate_id"]
            dataset_id = selection["dataset_id"]
            metadata = _dataset_metadata_from_candidate(candidate_id, disease)
            job.update({
                "progress": 10 + int((index - 1) / max(len(selections), 1) * 75),
                "message": f"Downloading real data from {metadata['repository']} ({metadata['accession']})...",
            })
            try:
                result = _acquire_and_preprocess(candidate_id, dataset_id)
                dataset = db.query(Dataset).filter(
                    Dataset.id == dataset_id,
                    Dataset.owner_id == user_id,
                ).first()
                if not dataset:
                    raise ValueError(f"Project dataset {dataset_id} disappeared during acquisition")

                dataset.description = f"Real public expression data from {metadata['repository']} ({metadata['accession']}); processed with {result['normalization_method']}."
                dataset.expression_file_path = result["processed_path"]
                dataset.metadata_file_path = result["metadata_path"]
                dataset.data_type = DataTypeEnum.NORMALIZED
                dataset.n_genes = result["n_genes"]
                dataset.n_samples = result["n_samples"]
                dataset.n_healthy = result["n_healthy"]
                dataset.n_cancer = result["n_cancer"]
                dataset.is_validated = True
                db.commit()

                metadata.update({
                    "id": dataset_id,
                    "dataset_id": dataset_id,
                    "sample_count": result["n_samples"],
                    "n_samples": result["n_samples"],
                    "gene_count": result["n_genes"],
                    "n_genes": result["n_genes"],
                    "n_healthy": result["n_healthy"],
                    "n_cancer": result["n_cancer"],
                    "data_type": "normalized",
                    "status": "ready",
                    "is_validated": True,
                    "raw_expression_path": result["expression_path"],
                    "metadata_path": result["metadata_path"],
                    "processed_expression_path": result["processed_path"],
                    "normalization_method": result["normalization_method"],
                    "expression_sha256": result["expression_sha256"],
                    "excluded_unmapped_gene_ids": result["excluded_unmapped_gene_ids"],
                    "preprocessing_log": result["preprocessing_log"],
                    "source_candidate_id": candidate_id,
                    "sample_preview": [],
                })
                manifest_datasets = [entry for entry in manifest_datasets if entry.get("accession") != metadata["accession"]]
                manifest_datasets.append(metadata)
                write_manifest({"datasets": manifest_datasets})
                from app.services.data_acquisition.dataset_registry import write_dataset_registry
                write_dataset_registry()
            except Exception as exc:
                db.rollback()
                job.update({
                    "status": "failed",
                    "progress": 0,
                    "message": f"Acquisition failed for {metadata['accession']}",
                    "error_message": str(exc),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
                return

            job.update({
                "progress": 10 + int(index / max(len(selections), 1) * 85),
                "message": f"Acquired and preprocessed {index}/{len(selections)} real dataset(s).",
            })

        job.update({
            "status": "completed",
            "progress": 100,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "message": "Real public data acquired, preprocessed, and registered in the selected project.",
        })
    finally:
        db.close()


@router.get("/search", response_model=SearchResponse)
async def search_datasets(
    disease: str = "Breast Cancer",
    species: str = "Human,Mouse",
):
    species_list = [term.strip().title() for term in species.split(",") if term.strip()]
    datasets = build_candidate_datasets()
    return SearchResponse(
        disease=disease,
        species=species_list or ["Human", "Mouse"],
        datasets=[
            DatasetCandidate(
                id=item["id"],
                name=item["name"],
                repository=item["repository"],
                species=item["species"],
                condition=item["condition"],
                tissue=item["tissue"],
                sample_count=item["sample_count"],
                data_type=item["data_type"],
                expression_available=item["expression_available"],
                metadata_available=item["metadata_available"],
                suitability_score=item["suitability_score"],
                suitability_reasons=item.get("suitability_reasons", []),
                accessions=item.get("accessions", []),
                source_url=item.get("source_url"),
                sample_preview=[
                    SamplePreview(**preview) for preview in item.get("sample_preview", [])
                ],
            )
            for item in datasets
        ],
        message="Dataset discovery completed. Review the candidates and explicitly download the selected data.",
    )


@router.post("/select")
async def select_datasets(
    payload: DatasetSelectionRequest,
):
    selected = payload.selected_ids or []
    return {
        "selected_ids": selected,
        "disease": payload.disease,
        "species": payload.species,
        "analysis_type": payload.analysis_type,
        "message": "Selected datasets ready for review and download.",
    }


@router.post("/download")
async def download_selected_data(
    payload: DownloadRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    if not payload.selected_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select at least one dataset before downloading.")

    project_result = await db.execute(
        select(Project).where(Project.id == payload.project_id, Project.owner_id == current_user.id)
    )
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    candidate_map = {item["id"]: item for item in build_candidate_datasets()}
    unsupported = [item for item in payload.selected_ids if item not in candidate_map]
    if unsupported:
        raise HTTPException(status_code=400, detail=f"Unsupported public dataset selection: {', '.join(unsupported)}")

    ensure_data_directories()
    selections = []
    for candidate_id in payload.selected_ids:
        metadata = _dataset_metadata_from_candidate(candidate_id, payload.disease)
        species = SpeciesEnum.MOUSE if metadata["species"].lower().startswith("mouse") else SpeciesEnum.HUMAN
        existing_result = await db.execute(
            select(Dataset).where(
                Dataset.project_id == payload.project_id,
                Dataset.owner_id == current_user.id,
                Dataset.accession == metadata["accession"],
            )
        )
        dataset = existing_result.scalar_one_or_none()
        if not dataset:
            dataset = Dataset(
                project_id=payload.project_id,
                owner_id=current_user.id,
                name=metadata["name"],
                species=species,
                tissue=metadata["tissue"],
                source=metadata["repository"],
                accession=metadata["accession"],
                data_type=DataTypeEnum.RAW_COUNTS if metadata["data_type"] == "raw_counts" else DataTypeEnum.NORMALIZED,
            )
            db.add(dataset)
            await db.flush()
        selections.append({"candidate_id": candidate_id, "dataset_id": str(dataset.id)})

    await db.commit()
    job = await _create_job("Queued real public-data acquisition...")
    background_tasks.add_task(_run_acquisition_job, job["job_id"], current_user.id, selections, payload.disease)
    return {"job_id": job["job_id"], "status": job["status"], "message": "Acquisition queued; poll the job endpoint for progress.", "paths": {
        "uploads": str(UPLOAD_ROOT),
        "data_root": str(DATA_ROOT),
    }}


@router.post("/validate")
async def validate_selected_dataset(
    payload: ValidationRequest,
):
    file_path = payload.file_path or str(RAW_ROOT / f"{payload.dataset_id}.csv")
    report = validate_expression_matrix(file_path)
    return {
        "dataset_id": payload.dataset_id,
        "status": "ready" if report["valid"] else "failed",
        "report": report,
    }


@router.post("/process")
async def process_selected_dataset(
    payload: ProcessingRequest,
):
    file_path = payload.file_path or str(RAW_ROOT / f"{payload.dataset_id}.csv")
    processed_file = Path(file_path)
    if not processed_file.exists():
        raise HTTPException(status_code=404, detail="Dataset file not found. Download the dataset first.")

    import pandas as pd

    suffixes = processed_file.suffixes
    if ".parquet" in suffixes:
        df = pd.read_parquet(processed_file)
    elif ".gz" in suffixes:
        separator = "\t" if any(suffix in suffixes for suffix in (".tsv", ".txt")) else ","
        df = pd.read_csv(processed_file, sep=separator, compression="gzip", low_memory=False)
    elif processed_file.suffix.lower() in {".csv", ".tsv", ".txt"}:
        separator = "," if processed_file.suffix.lower() == ".csv" else "\t"
        df = pd.read_csv(processed_file, sep=separator, low_memory=False)
    else:
        raise HTTPException(status_code=415, detail="Unsupported expression matrix format.")
    working, summary = preprocess_expression_matrix(df)
    output_path = PROCESSED_ROOT / f"{payload.dataset_id}_processed.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    working.to_csv(output_path, index=False)
    return {
        "dataset_id": payload.dataset_id,
        "status": "processed",
        "output_path": str(output_path),
        "summary": summary,
    }


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job = jobs_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        error_message=job.get("error_message"),
        created_at=job.get("created_at"),
        completed_at=job.get("completed_at"),
    )


@router.get("/datasets")
async def list_datasets():
    return _manifest_datasets()


@router.get("/manifest-datasets")
async def list_manifest_datasets():
    return _manifest_datasets()


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    offset: int = 0,
    limit: int = DEFAULT_EXPRESSION_PAGE_SIZE,
):
    if offset < 0:
        raise HTTPException(status_code=422, detail="Offset cannot be negative.")
    if limit < 1 or limit > MAX_EXPRESSION_PAGE_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"Limit must be between 1 and {MAX_EXPRESSION_PAGE_SIZE}.",
        )
    dataset = _find_manifest_dataset(dataset_id)
    return {**dataset, **_build_manifest_preview(dataset, offset, limit)}


@router.get("/health")
async def health():
    ensure_data_directories()
    return {
        "status": "ok",
        "data_root": str(DATA_ROOT),
        "message": "Data acquisition engine is available.",
    }
