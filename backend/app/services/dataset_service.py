"""
DatasetService: handles file upload, validation, and metadata parsing.
Enforces security: path traversal protection, file type validation, size limits.
"""
import os
import uuid
import hashlib
from typing import Optional
from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pandas as pd
import numpy as np
import structlog

from app.models import Dataset, Sample, Project, SpeciesEnum, DataTypeEnum, DiseaseStateEnum
from app.schemas.schemas import DatasetValidationResult

logger = structlog.get_logger(__name__)

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".txt", ".gz", ".zip"}
MAX_FILENAME_LENGTH = 128


class DatasetService:
    def __init__(self, db: AsyncSession, current_user, settings):
        self.db = db
        self.user = current_user
        self.settings = settings

    async def _assert_project_access(self, project_id: str) -> Project:
        result = await self.db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.owner_id == self.user.id,
            )
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found or access denied")
        return project

    async def get_dataset(self, dataset_id: str) -> Dataset:
        result = await self.db.execute(
            select(Dataset).where(
                Dataset.id == dataset_id,
                Dataset.owner_id == self.user.id,
            )
        )
        dataset = result.scalar_one_or_none()
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found or access denied")
        return dataset

    async def list_datasets(self, project_id: str) -> list[Dataset]:
        await self._assert_project_access(project_id)
        result = await self.db.execute(
            select(Dataset).where(
                Dataset.project_id == project_id,
                Dataset.owner_id == self.user.id,
            )
        )
        return result.scalars().all()

    async def create_dataset(
        self,
        project_id: str,
        name: str,
        species: SpeciesEnum,
        data_type: DataTypeEnum,
        expression_file: UploadFile,
        metadata_file: Optional[UploadFile],
        tissue: Optional[str] = None,
        source: Optional[str] = None,
        accession: Optional[str] = None,
        platform: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dataset:
        await self._assert_project_access(project_id)

        # Validate file extension
        expr_ext = self._safe_extension(expression_file.filename)
        if expr_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Expression file type '{expr_ext}' not supported. Allowed: {ALLOWED_EXTENSIONS}",
            )

        # Read and check size
        expr_content = await expression_file.read()
        max_bytes = self.settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(expr_content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Expression file exceeds maximum allowed size ({self.settings.MAX_UPLOAD_SIZE_MB} MB)",
            )

        # Save expression file securely
        dataset_id = str(uuid.uuid4())
        upload_base = os.path.join(self.settings.UPLOAD_DIR, dataset_id)
        os.makedirs(upload_base, exist_ok=True)

        expr_filename = f"expression{expr_ext}"
        expr_path = os.path.join(upload_base, expr_filename)
        with open(expr_path, "wb") as f:
            f.write(expr_content)

        # Save metadata file if provided
        meta_path = None
        if metadata_file and metadata_file.filename:
            meta_ext = self._safe_extension(metadata_file.filename)
            if meta_ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"Metadata file type '{meta_ext}' not supported")
            meta_content = await metadata_file.read()
            if len(meta_content) > max_bytes:
                raise HTTPException(status_code=413, detail="Metadata file too large")
            meta_filename = f"metadata{meta_ext}"
            meta_path = os.path.join(upload_base, meta_filename)
            with open(meta_path, "wb") as f:
                f.write(meta_content)

        dataset = Dataset(
            id=dataset_id,
            project_id=project_id,
            owner_id=self.user.id,
            name=name,
            description=description,
            species=species,
            tissue=tissue,
            source=source,
            accession=accession,
            platform=platform,
            data_type=data_type,
            expression_file_path=expr_path,
            metadata_file_path=meta_path,
        )
        self.db.add(dataset)
        await self.db.flush()
        await self.db.refresh(dataset)
        logger.info("dataset_created", dataset_id=dataset_id, user_id=self.user.id)
        return dataset

    async def validate_dataset(self, dataset_id: str) -> DatasetValidationResult:
        dataset = await self.get_dataset(dataset_id)
        errors: list[str] = []
        warnings: list[str] = []
        summary: dict = {}

        if not dataset.expression_file_path or not os.path.exists(dataset.expression_file_path):
            errors.append("Expression file not found on disk.")
            dataset.is_validated = False
            dataset.validation_errors = {"errors": errors}
            return DatasetValidationResult(
                dataset_id=dataset_id, is_valid=False, errors=errors, warnings=warnings, summary=summary
            )

        try:
            expr_df = self._load_expression_matrix(dataset.expression_file_path)
        except Exception as e:
            errors.append(f"Could not parse expression matrix: {e}")
            dataset.is_validated = False
            dataset.validation_errors = {"errors": errors}
            return DatasetValidationResult(
                dataset_id=dataset_id, is_valid=False, errors=errors, warnings=warnings, summary=summary
            )

        n_genes, n_samples = expr_df.shape
        summary["n_genes"] = n_genes
        summary["n_samples"] = n_samples

        # Minimum size check
        if n_genes < 100:
            errors.append(f"Expression matrix has only {n_genes} genes. Minimum required: 100.")
        if n_samples < 6:
            errors.append(f"Expression matrix has only {n_samples} samples. Minimum required: 6.")

        # Duplicate genes
        dup_genes = expr_df.index[expr_df.index.duplicated()].unique().tolist()
        if dup_genes:
            warnings.append(f"{len(dup_genes)} duplicate gene identifiers detected: {dup_genes[:5]}...")
            summary["duplicate_genes"] = len(dup_genes)

        # Duplicate samples
        dup_samples = expr_df.columns[expr_df.columns.duplicated()].unique().tolist()
        if dup_samples:
            errors.append(f"{len(dup_samples)} duplicate sample identifiers: {dup_samples[:5]}...")

        # Missing values
        n_missing = int(expr_df.isnull().sum().sum())
        if n_missing > 0:
            frac_missing = n_missing / (n_genes * n_samples)
            msg = f"{n_missing} missing values ({frac_missing:.1%} of matrix)"
            if frac_missing > 0.2:
                errors.append(msg + " — exceeds 20% threshold.")
            else:
                warnings.append(msg)
            summary["missing_values"] = n_missing

        # Non-numeric values
        non_numeric = (~expr_df.apply(lambda c: pd.to_numeric(c, errors="coerce")).notnull()).sum().sum()
        if non_numeric > 0:
            errors.append(f"{non_numeric} non-numeric values in expression matrix.")

        # Negative values (unusual for counts / normalized data)
        if (expr_df < 0).any().any():
            warnings.append("Negative expression values detected. Verify normalization method matches data type.")

        # Load metadata if present
        n_healthy = None
        n_cancer = None
        if dataset.metadata_file_path and os.path.exists(dataset.metadata_file_path):
            try:
                meta_df = self._load_metadata(dataset.metadata_file_path)
                required_cols = {"sample_id", "disease_state"}
                missing_cols = required_cols - set(meta_df.columns.str.lower())
                if missing_cols:
                    errors.append(f"Metadata missing required columns: {missing_cols}")
                else:
                    meta_df.columns = meta_df.columns.str.lower()
                    # Check sample overlap
                    expr_samples = set(expr_df.columns)
                    meta_samples = set(meta_df["sample_id"].astype(str))
                    not_in_meta = expr_samples - meta_samples
                    not_in_expr = meta_samples - expr_samples
                    if not_in_meta:
                        warnings.append(f"{len(not_in_meta)} expression samples not found in metadata.")
                    if not_in_expr:
                        warnings.append(f"{len(not_in_expr)} metadata samples not found in expression matrix.")
                    # Count states
                    states = meta_df["disease_state"].str.lower().value_counts().to_dict()
                    summary["disease_states"] = states
                    n_healthy = sum(v for k, v in states.items() if "healthy" in k or "normal" in k)
                    n_cancer = sum(v for k, v in states.items() if "cancer" in k or "tumor" in k or "disease" in k)
                    if n_healthy == 0:
                        errors.append("No healthy/normal samples detected in metadata.")
                    if n_cancer == 0:
                        errors.append("No cancer/disease samples detected in metadata.")
            except Exception as e:
                warnings.append(f"Could not parse metadata file: {e}")

        # Update dataset record
        is_valid = len(errors) == 0
        dataset.is_validated = is_valid
        dataset.validation_errors = {"errors": errors} if errors else {}
        dataset.validation_warnings = {"warnings": warnings} if warnings else {}
        dataset.n_genes = n_genes
        dataset.n_samples = n_samples
        dataset.n_healthy = n_healthy
        dataset.n_cancer = n_cancer
        await self.db.flush()

        return DatasetValidationResult(
            dataset_id=dataset_id,
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            summary=summary,
        )

    async def delete_dataset(self, dataset_id: str) -> None:
        dataset = await self.get_dataset(dataset_id)
        # Remove uploaded files
        import shutil
        upload_dir = os.path.join(self.settings.UPLOAD_DIR, dataset_id)
        if os.path.isdir(upload_dir):
            shutil.rmtree(upload_dir)
        await self.db.delete(dataset)
        await self.db.flush()

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _safe_extension(filename: str) -> str:
        """Return lower-case extension; reject unsafe filenames."""
        if not filename:
            raise HTTPException(status_code=400, detail="Filename is required.")
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename.")
        _, ext = os.path.splitext(filename.lower())
        return ext

    @staticmethod
    def _load_expression_matrix(path: str) -> pd.DataFrame:
        """Load expression matrix. Rows = genes, columns = samples."""
        if path.endswith(".gz"):
            compression = "gzip"
        elif path.endswith(".zip"):
            compression = "zip"
        else:
            compression = None

        sep = "\t" if path.endswith((".tsv", ".txt", ".tsv.gz", ".txt.gz")) else ","
        df = pd.read_csv(path, sep=sep, index_col=0, compression=compression, low_memory=False)
        return df

    @staticmethod
    def _load_metadata(path: str) -> pd.DataFrame:
        if path.endswith(".gz"):
            compression = "gzip"
        else:
            compression = None
        sep = "\t" if path.endswith((".tsv", ".txt", ".tsv.gz", ".txt.gz")) else ","
        return pd.read_csv(path, sep=sep, compression=compression)
