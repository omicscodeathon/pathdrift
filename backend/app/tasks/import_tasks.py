"""
Import tasks for GEO and TCGA data.

These tasks download real public data from NCBI GEO and TCGA/GDC.
They respect API rate limits and terms of service.
"""
import os
import time
import traceback
import gzip
import pandas as pd
import structlog

from app.tasks.celery_app import celery_app
from app.tasks.analysis_tasks import get_sync_db, _update_job
from app.models import Dataset, BackgroundJob, JobStatusEnum, DataTypeEnum

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="app.tasks.import_tasks.import_geo_task")
def import_geo_task(self, job_id: str, dataset_id: str, accession: str,
                     upload_dir: str, ncbi_email: str, ncbi_api_key: str = None):
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 10, f"Downloading {accession} from NCBI GEO")

        try:
            import GEOparse
        except ImportError:
            raise ImportError(
                "GEOparse is not installed. Add 'GEOparse' to requirements.txt and rebuild."
            )

        if ncbi_email:
            GEOparse.logger.setLevel("WARNING")

        logger.info("geo_download_starting", accession=accession)

        # Download the GSE series
        _update_job(db, job_id, JobStatusEnum.RUNNING, 20, f"Fetching GSE series {accession}")
        gse = GEOparse.get_GEO(geo=accession, destdir=os.path.join(upload_dir, "geo_cache"), silent=True)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 60, "Parsing expression matrix")

        # Extract expression matrix
        pivot_tables = []
        for gsm_name, gsm in gse.gsms.items():
            if gsm.table is not None and not gsm.table.empty:
                col = gsm.table.set_index(gsm.table.columns[0])[gsm.table.columns[-1]]
                col.name = gsm_name
                pivot_tables.append(col)

        if not pivot_tables:
            raise ValueError(f"Could not extract expression data from {accession}")

        expr_df = pd.DataFrame(pivot_tables).T
        expr_df.index.name = "gene_id"

        # Save expression matrix
        out_dir = os.path.join(upload_dir, dataset_id)
        os.makedirs(out_dir, exist_ok=True)
        expr_path = os.path.join(out_dir, "expression.tsv.gz")
        expr_df.to_csv(expr_path, sep="\t", compression="gzip")

        # Extract metadata
        meta_rows = []
        for gsm_name, gsm in gse.gsms.items():
            state = "unknown"
            title = " ".join(gsm.metadata.get("title", [""])).lower()
            chars = " ".join([
                str(v) for vals in gsm.metadata.get("characteristics_ch1", [[]]) for v in (vals if isinstance(vals, list) else [vals])
            ]).lower()
            combined = title + " " + chars
            if any(w in combined for w in ["normal", "healthy", "non-tumor", "non-cancerous"]):
                state = "healthy"
            elif any(w in combined for w in ["tumor", "cancer", "carcinoma", "malignant"]):
                state = "cancer"
            meta_rows.append({"sample_id": gsm_name, "disease_state": state})

        meta_df = pd.DataFrame(meta_rows)
        meta_path = os.path.join(out_dir, "metadata.tsv")
        meta_df.to_csv(meta_path, sep="\t", index=False)

        # Update dataset record
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if dataset:
            dataset.expression_file_path = expr_path
            dataset.metadata_file_path = meta_path
            dataset.n_genes = expr_df.shape[0]
            dataset.n_samples = expr_df.shape[1]
            n_healthy = (meta_df["disease_state"] == "healthy").sum()
            n_cancer = (meta_df["disease_state"] == "cancer").sum()
            dataset.n_healthy = int(n_healthy)
            dataset.n_cancer = int(n_cancer)
        db.commit()

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100,
                    f"GEO import complete: {expr_df.shape[0]} genes, {expr_df.shape[1]} samples")
        return {"status": "completed", "n_genes": expr_df.shape[0], "n_samples": expr_df.shape[1]}

    except Exception as e:
        err = str(e)
        logger.error("geo_import_failed", error=err, accession=accession)
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", err)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="app.tasks.import_tasks.import_tcga_task")
def import_tcga_task(self, job_id: str, dataset_id: str, project_code: str,
                      upload_dir: str, gdc_api_url: str):
    """
    Import TCGA RNA-seq data via the GDC API.
    Downloads HTSeq count files for the specified project.
    """
    import httpx
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 10, f"Querying GDC API for {project_code}")

        # Query files from GDC
        files_endpoint = f"{gdc_api_url}/files"
        filters = {
            "op": "and",
            "content": [
                {"op": "=", "content": {"field": "cases.project.project_id", "value": project_code}},
                {"op": "=", "content": {"field": "data_type", "value": "Gene Expression Quantification"}},
                {"op": "=", "content": {"field": "analysis.workflow_type", "value": "STAR - Counts"}},
            ],
        }
        params = {
            "filters": str(filters),
            "fields": "file_id,file_name,cases.submitter_id,cases.disease_type",
            "format": "json",
            "size": 500,
        }

        _update_job(db, job_id, JobStatusEnum.RUNNING, 30, "Downloading file manifest")

        with httpx.Client(timeout=60) as client:
            resp = client.post(files_endpoint, json={
                "filters": filters,
                "fields": "file_id,file_name,cases.submitter_id",
                "format": "JSON",
                "size": 500,
            })
            resp.raise_for_status()
            files_data = resp.json()

        hits = files_data.get("data", {}).get("hits", [])
        file_ids = [hit["file_id"] for hit in hits]
        if not file_ids:
            raise ValueError(
                f"No STAR-Counts files found for project {project_code} in GDC. "
                "The project may not exist or may have a different workflow type."
            )

        logger.info("tcga_files_found", n_files=len(file_ids), project=project_code)
        _update_job(db, job_id, JobStatusEnum.RUNNING, 50, f"Found {len(file_ids)} files; downloading data bundle")

        out_dir = os.path.join(upload_dir, dataset_id)
        os.makedirs(out_dir, exist_ok=True)

        manifest = pd.DataFrame({"file_id": file_ids})
        manifest_path = os.path.join(out_dir, "gdc_manifest.tsv")
        manifest.to_csv(manifest_path, sep="\t", index=False)

        # Download the individual STAR-count files so the imported dataset is usable
        # immediately. Large cohorts should still be filtered before importing.
        expression_by_sample = {}
        metadata_rows = []
        with httpx.Client(base_url=gdc_api_url, timeout=120) as client:
            for index, hit in enumerate(hits[:200], start=1):
                response = client.get(f"/data/{hit['file_id']}")
                response.raise_for_status()
                payload = response.content
                if payload[:2] == b"\\x1f\\x8b":
                    payload = gzip.decompress(payload)
                sample_id = (hit.get("cases") or [{}])[0].get("submitter_id") or hit.get("file_name") or hit["file_id"]
                counts = {}
                for line in payload.decode("utf-8", errors="replace").splitlines():
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 4 or parts[0].startswith("N_") or parts[0] == "gene_id":
                        continue
                    try:
                        counts[parts[0]] = float(parts[3])
                    except ValueError:
                        continue
                if counts:
                    expression_by_sample[sample_id] = counts
                    metadata_rows.append({"sample_id": sample_id, "disease_state": "cancer"})
                _update_job(db, job_id, JobStatusEnum.RUNNING, 50 + int(index / max(min(len(hits), 200), 1) * 35), f"Downloaded {index}/{min(len(hits), 200)} count files")

        if not expression_by_sample:
            raise ValueError(f"GDC returned no parseable STAR count files for {project_code}")

        expr_df = pd.DataFrame(expression_by_sample).fillna(0)
        expr_df.index.name = "gene_id"
        expr_path = os.path.join(out_dir, "expression.tsv.gz")
        expr_df.to_csv(expr_path, sep="\t", compression="gzip")
        meta_path = os.path.join(out_dir, "metadata.tsv")
        pd.DataFrame(metadata_rows).to_csv(meta_path, sep="\t", index=False)

        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if dataset:
            dataset.expression_file_path = expr_path
            dataset.metadata_file_path = meta_path
            dataset.n_genes = expr_df.shape[0]
            dataset.n_samples = expr_df.shape[1]
            dataset.n_cancer = expr_df.shape[1]
        db.commit()

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100,
                    f"GDC import complete: {expr_df.shape[0]} genes, {expr_df.shape[1]} samples")
        return {"status": "completed", "n_files": len(expression_by_sample), "expression_path": expr_path, "manifest_path": manifest_path}

    except Exception as e:
        logger.error("tcga_import_failed", error=str(e))
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", str(e))
        raise
    finally:
        db.close()
