"""
PathDrift Pydantic Schemas (request/response models)
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models import (
    SpeciesEnum, DiseaseStateEnum, JobStatusEnum, DataTypeEnum,
    NormMethodEnum, CorrelationMethodEnum, MLModelTypeEnum,
    ExperimentTypeEnum,
)


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8)
    full_name: Optional[str] = None
    institution: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        from email_validator import validate_email, EmailNotValidError
        try:
            info = validate_email(v, check_deliverability=False)
            return info.normalized
        except EmailNotValidError as e:
            raise ValueError(f"Invalid email address: {e}")


class UserOut(BaseModel):
    id: str
    email: str
    username: str
    full_name: Optional[str]
    institution: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginIn(BaseModel):
    username: str   # email or username
    password: str


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    research_question: Optional[str] = None
    is_public: bool = False


class ProjectOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    research_question: Optional[str]
    is_public: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Datasets ──────────────────────────────────────────────────────────────────

class DatasetCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    species: SpeciesEnum
    tissue: Optional[str] = None
    source: Optional[str] = None
    accession: Optional[str] = None
    platform: Optional[str] = None
    data_type: DataTypeEnum = DataTypeEnum.UNKNOWN


class DatasetOut(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str]
    species: SpeciesEnum
    tissue: Optional[str]
    source: Optional[str]
    accession: Optional[str]
    platform: Optional[str]
    data_type: DataTypeEnum
    n_genes: Optional[int]
    n_samples: Optional[int]
    n_healthy: Optional[int]
    n_cancer: Optional[int]
    is_validated: bool
    validation_errors: Optional[Dict[str, Any]]
    validation_warnings: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetValidationResult(BaseModel):
    dataset_id: str
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    summary: Dict[str, Any]


# ── Samples ───────────────────────────────────────────────────────────────────

class SampleOut(BaseModel):
    id: str
    sample_id: str
    disease_state: DiseaseStateEnum
    stage: Optional[str]
    batch: Optional[str]
    age: Optional[float]
    sex: Optional[str]

    model_config = {"from_attributes": True}


# ── Analysis ──────────────────────────────────────────────────────────────────

class AnalysisCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    random_seed: int = 42


class AnalysisOut(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str]
    status: JobStatusEnum
    random_seed: int
    config_snapshot: Optional[Dict[str, Any]]
    software_versions: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Preprocessing ─────────────────────────────────────────────────────────────

class PreprocessingConfig(BaseModel):
    analysis_id: str
    dataset_id: str
    normalization_method: NormMethodEnum = NormMethodEnum.LOG2CPM
    low_expr_threshold: float = Field(1.0, ge=0)
    low_expr_min_samples: int = Field(3, ge=1)
    min_gene_variance: float = Field(0.0, ge=0)
    remove_duplicates: bool = True
    impute_missing: bool = False
    batch_correct: bool = False
    batch_correction_method: Optional[str] = None
    outlier_detection: bool = True


class PreprocessingJobOut(BaseModel):
    id: str
    analysis_id: str
    dataset_id: str
    normalization_method: NormMethodEnum
    status: JobStatusEnum
    n_genes_before: Optional[int]
    n_genes_after: Optional[int]
    n_samples_before: Optional[int]
    n_samples_after: Optional[int]
    outlier_samples: Optional[List[str]]
    processing_log: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── DEG ───────────────────────────────────────────────────────────────────────

class DEGConfig(BaseModel):
    analysis_id: str
    dataset_id: str
    preprocessing_job_id: Optional[str] = None
    method: str = "pydeseq2"  # or "ttest", "limma-like"
    fdr_threshold: float = Field(0.05, gt=0, lt=1)
    lfc_threshold: float = Field(1.0, ge=0)


class DEGResultOut(BaseModel):
    id: str
    analysis_id: str
    dataset_id: str
    method: str
    fdr_threshold: float
    lfc_threshold: float
    n_deg_total: Optional[int]
    n_deg_up: Optional[int]
    n_deg_down: Optional[int]
    status: JobStatusEnum
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Networks ──────────────────────────────────────────────────────────────────

class NetworkConfig(BaseModel):
    analysis_id: str
    dataset_id: str
    preprocessing_job_id: Optional[str] = None
    name: str
    species: SpeciesEnum
    disease_state: DiseaseStateEnum
    correlation_method: CorrelationMethodEnum = CorrelationMethodEnum.PEARSON
    correlation_threshold: float = Field(0.6, ge=0, le=1)
    fdr_threshold: float = Field(0.05, gt=0, lt=1)
    top_n_genes: Optional[int] = Field(None, ge=100, le=5000)
    min_gene_variance: float = Field(0.1, ge=0)


class NetworkOut(BaseModel):
    id: str
    analysis_id: str
    name: str
    species: SpeciesEnum
    disease_state: DiseaseStateEnum
    correlation_method: CorrelationMethodEnum
    correlation_threshold: float
    n_nodes: Optional[int]
    n_edges: Optional[int]
    density: Optional[float]
    avg_clustering_coefficient: Optional[float]
    avg_degree: Optional[float]
    status: JobStatusEnum
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Drift ─────────────────────────────────────────────────────────────────────

class DriftConfig(BaseModel):
    analysis_id: str
    healthy_network_id: str
    disease_network_id: str
    species: SpeciesEnum


class DriftResultOut(BaseModel):
    id: str
    analysis_id: str
    healthy_network_id: str
    disease_network_id: str
    species: SpeciesEnum
    n_conserved_edges: Optional[int]
    n_gained_edges: Optional[int]
    n_lost_edges: Optional[int]
    global_drift_score: Optional[float]
    status: JobStatusEnum
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Cross-Species ──────────────────────────────────────────────────────────────

class CrossSpeciesConfig(BaseModel):
    analysis_id: str
    human_drift_id: str
    mouse_drift_id: str


class CrossSpeciesOut(BaseModel):
    id: str
    analysis_id: str
    human_drift_id: str
    mouse_drift_id: str
    n_orthologous_genes: Optional[int]
    n_conserved_drift: Optional[int]
    n_human_specific: Optional[int]
    n_mouse_specific: Optional[int]
    n_divergent: Optional[int]
    conservation_score: Optional[float]
    status: JobStatusEnum
    created_at: datetime

    model_config = {"from_attributes": True}


# ── ML ────────────────────────────────────────────────────────────────────────

class MLExperimentConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    analysis_id: str
    name: str
    experiment_type: ExperimentTypeEnum
    model_type: MLModelTypeEnum
    training_dataset_id: str
    validation_dataset_id: Optional[str] = None
    cross_species_analysis_id: Optional[str] = None
    drift_analysis_id: Optional[str] = None
    preprocessing_job_id: Optional[str] = None
    random_seed: int = 42
    cv_folds: int = Field(5, ge=2, le=20)
    test_size: float = Field(0.2, gt=0, lt=0.5)
    hyperparams: Optional[Dict[str, Any]] = None
    feature_selection_config: Optional[Dict[str, Any]] = None
    class_weight: str = "balanced"


class MLExperimentOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), from_attributes=True)
    id: str
    analysis_id: str
    name: str
    experiment_type: ExperimentTypeEnum
    model_type: MLModelTypeEnum
    random_seed: int
    cv_folds: int
    n_features_used: Optional[int]
    leakage_warnings: Optional[List[str]]
    status: JobStatusEnum
    created_at: datetime

class ModelMetricOut(BaseModel):
    id: str
    experiment_id: str
    split: str
    auroc: Optional[float]
    auprc: Optional[float]
    accuracy: Optional[float]
    sensitivity: Optional[float]
    specificity: Optional[float]
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    auroc_ci_lower: Optional[float]
    auroc_ci_upper: Optional[float]
    confusion_matrix: Optional[Dict[str, Any]]

    model_config = {"from_attributes": True}


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobOut(BaseModel):
    id: str
    analysis_id: Optional[str]
    celery_task_id: Optional[str]
    task_name: str
    status: JobStatusEnum
    progress: int
    progress_message: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    result_ref: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Pathways ──────────────────────────────────────────────────────────────────

class PathwayConfig(BaseModel):
    analysis_id: str
    gene_set: str = "GO_Biological_Process_2023"  # gseapy gene set name
    source: str = "drift"  # drift | deg | conserved
    species: SpeciesEnum
    fdr_threshold: float = Field(0.05, gt=0, lt=1)
    source_id: str  # drift_analysis_id or deg_result_id


class PathwayResultOut(BaseModel):
    id: str
    analysis_id: str
    gene_set: str
    source: str
    species: SpeciesEnum
    n_significant: Optional[int]
    fdr_threshold: float
    status: JobStatusEnum
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Reports ───────────────────────────────────────────────────────────────────

class ReportConfig(BaseModel):
    analysis_id: str
    include_sections: List[str] = Field(default_factory=lambda: [
        "dataset", "preprocessing", "deg", "networks", "drift",
        "cross_species", "ml", "pathways", "limitations",
    ])
    format: str = "pdf"  # pdf | html


# ── Data Import ───────────────────────────────────────────────────────────────

class GEOImportRequest(BaseModel):
    project_id: str
    accession: str = Field(pattern=r"^GSE\d+$")
    species: SpeciesEnum
    tissue: Optional[str] = None


class TCGAImportRequest(BaseModel):
    project_id: str
    project_code: str  # e.g. TCGA-BRCA
    tissue: Optional[str] = "breast"


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    pages: int
