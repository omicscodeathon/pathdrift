"""
PathDrift SQLAlchemy ORM Models

Schema covers:
  users, projects, datasets, samples, genes, orthologues,
  preprocessing jobs, networks, network_edges, drift_results,
  network_modules, ml_experiments, model_metrics, predictions,
  pathway_results, analysis_audit_logs, background_jobs
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, JSON, Enum as SAEnum, UniqueConstraint, BigInteger,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, ARRAY, JSONB
from sqlalchemy.orm import relationship, mapped_column, Mapped
import enum

from app.db.base import Base


# ── Enumerations ──────────────────────────────────────────────────────────────

class SpeciesEnum(str, enum.Enum):
    HUMAN = "human"
    MOUSE = "mouse"


class DiseaseStateEnum(str, enum.Enum):
    HEALTHY = "healthy"
    EARLY_CANCER = "early_cancer"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    CANCER = "cancer"       # generic / unknown stage


class JobStatusEnum(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DataTypeEnum(str, enum.Enum):
    RAW_COUNTS = "raw_counts"
    NORMALIZED = "normalized"
    MICROARRAY = "microarray"
    UNKNOWN = "unknown"


class NormMethodEnum(str, enum.Enum):
    LOG2CPM = "log2cpm"
    VOOM = "voom"
    TPM = "tpm"
    FPKM = "fpkm"
    DESEQ2_VST = "deseq2_vst"
    QUANTILE = "quantile"
    NONE = "none"


class CorrelationMethodEnum(str, enum.Enum):
    PEARSON = "pearson"
    SPEARMAN = "spearman"
    PARTIAL = "partial"


class MLModelTypeEnum(str, enum.Enum):
    LOGISTIC_REGRESSION = "logistic_regression"
    RANDOM_FOREST = "random_forest"
    SVM = "svm"
    GRADIENT_BOOSTING = "gradient_boosting"


class ExperimentTypeEnum(str, enum.Enum):
    EXPRESSION_ONLY = "expression_only"
    DRIFT_ONLY = "drift_only"
    COMBINED = "combined"


class DriftClassEnum(str, enum.Enum):
    CONSERVED = "conserved"
    HUMAN_SPECIFIC = "human_specific"
    MOUSE_SPECIFIC = "mouse_specific"
    DIVERGENT = "divergent"


# ── Helper ────────────────────────────────────────────────────────────────────

def now_utc():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


# ── Users ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    institution: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")


# ── Projects ──────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    research_question: Mapped[Optional[str]] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    owner = relationship("User", back_populates="projects")
    datasets = relationship("Dataset", back_populates="project", cascade="all, delete-orphan")
    analyses = relationship("Analysis", back_populates="project", cascade="all, delete-orphan")
    acquisition_runs = relationship("AnalysisRun", back_populates="project", cascade="all, delete-orphan")


# ── Datasets ──────────────────────────────────────────────────────────────────

class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    species: Mapped[SpeciesEnum] = mapped_column(SAEnum(SpeciesEnum), nullable=False)
    tissue: Mapped[Optional[str]] = mapped_column(String(255))
    source: Mapped[Optional[str]] = mapped_column(String(255))   # TCGA, GEO, GTEx, etc.
    accession: Mapped[Optional[str]] = mapped_column(String(100))  # GEO accession e.g. GSE12345
    platform: Mapped[Optional[str]] = mapped_column(String(255))
    data_type: Mapped[DataTypeEnum] = mapped_column(SAEnum(DataTypeEnum), default=DataTypeEnum.UNKNOWN)

    # Storage
    expression_file_path: Mapped[Optional[str]] = mapped_column(String(512))
    metadata_file_path: Mapped[Optional[str]] = mapped_column(String(512))

    # Dimensions (populated after validation)
    n_genes: Mapped[Optional[int]] = mapped_column(Integer)
    n_samples: Mapped[Optional[int]] = mapped_column(Integer)
    n_healthy: Mapped[Optional[int]] = mapped_column(Integer)
    n_cancer: Mapped[Optional[int]] = mapped_column(Integer)

    # Validation
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_errors: Mapped[Optional[dict]] = mapped_column(JSON)
    validation_warnings: Mapped[Optional[dict]] = mapped_column(JSON)

    source_version: Mapped[Optional[str]] = mapped_column(String(100))
    retrieval_url: Mapped[Optional[str]] = mapped_column(String(1024))
    download_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    checksum: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    processing_steps: Mapped[Optional[dict]] = mapped_column(JSONB)
    provenance: Mapped[Optional[dict]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    project = relationship("Project", back_populates="datasets")
    samples = relationship("Sample", back_populates="dataset", cascade="all, delete-orphan")
    run_links = relationship("AnalysisRunDataset", back_populates="dataset", cascade="all, delete-orphan")


# ── Samples ───────────────────────────────────────────────────────────────────

class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    sample_id: Mapped[str] = mapped_column(String(255), nullable=False)  # original sample identifier
    disease_state: Mapped[DiseaseStateEnum] = mapped_column(SAEnum(DiseaseStateEnum), nullable=False)
    stage: Mapped[Optional[str]] = mapped_column(String(100))  # e.g. Stage_I, Stage_II
    batch: Mapped[Optional[str]] = mapped_column(String(100))
    age: Mapped[Optional[float]] = mapped_column(Float)
    sex: Mapped[Optional[str]] = mapped_column(String(10))
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("dataset_id", "sample_id", name="uq_sample_dataset"),
    )

    dataset = relationship("Dataset", back_populates="samples")


class AnalysisRun(Base):
    """Durable acquisition/preprocessing/QC run and its result locations."""
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    qc_summary: Mapped[Optional[dict]] = mapped_column(JSONB)
    run_dir: Mapped[Optional[str]] = mapped_column(String(1024))
    manifest_path: Mapped[Optional[str]] = mapped_column(String(1024))
    provenance_path: Mapped[Optional[str]] = mapped_column(String(1024))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    project = relationship("Project", back_populates="acquisition_runs")
    dataset_links = relationship("AnalysisRunDataset", back_populates="run", cascade="all, delete-orphan")
    sample_qc = relationship("SampleQC", back_populates="run", cascade="all, delete-orphan")


class AnalysisRunDataset(Base):
    __tablename__ = "analysis_run_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    provenance: Mapped[Optional[dict]] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("run_id", "dataset_id", name="uq_analysis_run_dataset"),)

    run = relationship("AnalysisRun", back_populates="dataset_links")
    dataset = relationship("Dataset", back_populates="run_links")


class SampleQC(Base):
    """Structured sample-level quality metrics for a specific run and dataset."""
    __tablename__ = "sample_qc"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    sample_id: Mapped[str] = mapped_column(String(255), nullable=False)
    library_size: Mapped[Optional[float]] = mapped_column(Float)
    detected_genes: Mapped[Optional[int]] = mapped_column(Integer)
    missing_fraction: Mapped[Optional[float]] = mapped_column(Float)
    zero_fraction: Mapped[Optional[float]] = mapped_column(Float)
    mean_expression: Mapped[Optional[float]] = mapped_column(Float)
    median_expression: Mapped[Optional[float]] = mapped_column(Float)
    outlier_score: Mapped[Optional[float]] = mapped_column(Float)
    is_outlier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclusion_reason: Mapped[Optional[str]] = mapped_column(Text)
    pca_coordinates: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cluster: Mapped[Optional[int]] = mapped_column(Integer)
    batch_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sample_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (UniqueConstraint("run_id", "dataset_id", "sample_id", name="uq_sample_qc_run_dataset_sample"),)

    run = relationship("AnalysisRun", back_populates="sample_qc")


class RunDifferentialExpression(Base):
    __tablename__ = "run_differential_expression"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    gene_id: Mapped[str] = mapped_column(String(36), ForeignKey("genes.id", ondelete="CASCADE"), nullable=False)
    species: Mapped[str] = mapped_column(String(16), nullable=False)
    comparison: Mapped[str] = mapped_column(String(100), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    log2fc: Mapped[Optional[float]] = mapped_column(Float)
    pvalue: Mapped[Optional[float]] = mapped_column(Float)
    adjusted_p_value: Mapped[Optional[float]] = mapped_column(Float)
    statistic: Mapped[Optional[float]] = mapped_column(Float)
    base_mean: Mapped[Optional[float]] = mapped_column(Float)
    average_expression: Mapped[Optional[float]] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    significant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "dataset_id", "comparison", "gene_id", name="uq_run_de_comparison_gene"),
        Index("ix_run_de_run_species", "run_id", "species"),
        Index("ix_run_de_run_comparison", "run_id", "comparison"),
        Index("ix_run_de_gene", "gene_id"),
        Index("ix_run_de_adjusted_p", "adjusted_p_value"),
        Index("ix_run_de_significant", "significant"),
    )


class RunGeneNetwork(Base):
    __tablename__ = "run_gene_networks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    species: Mapped[str] = mapped_column(String(16), nullable=False)
    disease_state: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "dataset_id", "name", name="uq_run_network_dataset_name"),
        Index("ix_run_networks_run_species", "run_id", "species"),
    )


class RunNetworkModule(Base):
    __tablename__ = "run_network_modules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    network_id: Mapped[str] = mapped_column(String(36), ForeignKey("run_gene_networks.id", ondelete="CASCADE"), nullable=False)
    module_key: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    detection_method: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    statistics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("network_id", "module_key", name="uq_run_network_module_key"),
        Index("ix_run_modules_network", "network_id"),
    )


class RunNetworkNode(Base):
    __tablename__ = "run_network_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    network_id: Mapped[str] = mapped_column(String(36), ForeignKey("run_gene_networks.id", ondelete="CASCADE"), nullable=False)
    gene_id: Mapped[str] = mapped_column(String(36), ForeignKey("genes.id", ondelete="CASCADE"), nullable=False)
    module_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("run_network_modules.id", ondelete="SET NULL"))
    degree: Mapped[int] = mapped_column(Integer, nullable=False)
    weighted_degree: Mapped[float] = mapped_column(Float, nullable=False)
    betweenness_centrality: Mapped[Optional[float]] = mapped_column(Float)
    closeness_centrality: Mapped[Optional[float]] = mapped_column(Float)
    eigenvector_centrality: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("network_id", "gene_id", name="uq_run_network_node_gene"),
        Index("ix_run_network_nodes_network", "network_id"),
        Index("ix_run_network_nodes_gene", "gene_id"),
    )


class RunNetworkEdge(Base):
    __tablename__ = "run_network_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    network_id: Mapped[str] = mapped_column(String(36), ForeignKey("run_gene_networks.id", ondelete="CASCADE"), nullable=False)
    source_gene_id: Mapped[str] = mapped_column(String(36), ForeignKey("genes.id", ondelete="CASCADE"), nullable=False)
    target_gene_id: Mapped[str] = mapped_column(String(36), ForeignKey("genes.id", ondelete="CASCADE"), nullable=False)
    correlation: Mapped[float] = mapped_column(Float, nullable=False)
    absolute_correlation: Mapped[float] = mapped_column(Float, nullable=False)
    pvalue: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_p_value: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("network_id", "source_gene_id", "target_gene_id", name="uq_run_network_undirected_edge"),
        Index("ix_run_network_edges_network", "network_id"),
        Index("ix_run_network_edges_source", "source_gene_id"),
        Index("ix_run_network_edges_target", "target_gene_id"),
    )


class RunModuleGene(Base):
    __tablename__ = "run_module_genes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    module_id: Mapped[str] = mapped_column(String(36), ForeignKey("run_network_modules.id", ondelete="CASCADE"), nullable=False)
    gene_id: Mapped[str] = mapped_column(String(36), ForeignKey("genes.id", ondelete="CASCADE"), nullable=False)
    membership: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("module_id", "gene_id", name="uq_run_module_gene"),
        Index("ix_run_module_genes_gene", "gene_id"),
    )


class RunPhase4Summary(Base):
    __tablename__ = "run_phase4_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    __table_args__ = (Index("ix_run_phase4_status", "status"),)


class RunOrthologyMapping(Base):
    __tablename__ = "run_orthology_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    human_ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False)
    mouse_ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False)
    human_original_id: Mapped[Optional[str]] = mapped_column(String(64))
    mouse_original_id: Mapped[Optional[str]] = mapped_column(String(64))
    human_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    mouse_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    orthology_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "human_ensembl_id", "mouse_ensembl_id", "source_version", name="uq_run_orthology_pair_version"),
        Index("ix_run_orthology_run_human", "run_id", "human_ensembl_id"),
        Index("ix_run_orthology_run_mouse", "run_id", "mouse_ensembl_id"),
        Index("ix_run_orthology_type", "run_id", "orthology_type"),
    )


class RunCrossSpeciesNodeAlignment(Base):
    __tablename__ = "run_cross_species_node_alignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    human_ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False)
    mouse_ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False)
    human_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    mouse_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    orthology_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    human_network_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mouse_network_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "human_ensembl_id", "mouse_ensembl_id", name="uq_run_cross_species_node_pair"),
        Index("ix_run_cross_species_nodes_run", "run_id"),
    )


class RunNetworkEdgeDrift(Base):
    __tablename__ = "run_network_edge_drift"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    human_edge_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("run_network_edges.id", ondelete="SET NULL"))
    mouse_edge_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("run_network_edges.id", ondelete="SET NULL"))
    human_source_gene_id: Mapped[Optional[str]] = mapped_column(String(50))
    human_target_gene_id: Mapped[Optional[str]] = mapped_column(String(50))
    mouse_source_gene_id: Mapped[Optional[str]] = mapped_column(String(50))
    mouse_target_gene_id: Mapped[Optional[str]] = mapped_column(String(50))
    human_weight: Mapped[Optional[float]] = mapped_column(Float)
    mouse_weight: Mapped[Optional[float]] = mapped_column(Float)
    human_p_value: Mapped[Optional[float]] = mapped_column(Float)
    mouse_p_value: Mapped[Optional[float]] = mapped_column(Float)
    human_adjusted_p_value: Mapped[Optional[float]] = mapped_column(Float)
    mouse_adjusted_p_value: Mapped[Optional[float]] = mapped_column(Float)
    weight_difference: Mapped[Optional[float]] = mapped_column(Float)
    absolute_weight_difference: Mapped[Optional[float]] = mapped_column(Float)
    relative_weight_change: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        Index("ix_run_network_edge_drift_run_status", "run_id", "status"),
        Index("ix_run_network_edge_drift_run_human", "run_id", "human_source_gene_id"),
        Index("ix_run_network_edge_drift_run_mouse", "run_id", "mouse_source_gene_id"),
    )


class RunGeneDrift(Base):
    __tablename__ = "run_gene_drift"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    human_ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False)
    mouse_ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False)
    human_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    mouse_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    human_degree: Mapped[int] = mapped_column(Integer, nullable=False)
    mouse_degree: Mapped[int] = mapped_column(Integer, nullable=False)
    degree_difference: Mapped[int] = mapped_column(Integer, nullable=False)
    human_neighbor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mouse_neighbor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    conserved_neighbor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lost_neighbor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gained_neighbor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    neighbor_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    edge_loss_rate: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_degree_difference: Mapped[float] = mapped_column(Float, nullable=False)
    module_conservation: Mapped[Optional[float]] = mapped_column(Float)
    drift_score: Mapped[float] = mapped_column(Float, nullable=False)
    drift_category: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "human_ensembl_id", "mouse_ensembl_id", name="uq_run_gene_drift_pair"),
        Index("ix_run_gene_drift_run_score", "run_id", "drift_score"),
        Index("ix_run_gene_drift_run_category", "run_id", "drift_category"),
    )


class RunModuleDrift(Base):
    __tablename__ = "run_module_drift"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    human_module_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_mouse_module_id: Mapped[Optional[str]] = mapped_column(String(36))
    human_module_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mapped_gene_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mouse_module_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    overlap_fraction: Mapped[float] = mapped_column(Float, nullable=False)
    module_conservation_score: Mapped[float] = mapped_column(Float, nullable=False)
    internal_edge_conservation: Mapped[Optional[float]] = mapped_column(Float)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        Index("ix_run_module_drift_run_human", "run_id", "human_module_id"),
        Index("ix_run_module_drift_run_class", "run_id", "classification"),
    )


class RunFigure(Base):
    __tablename__ = "run_figures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"))
    network_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("run_gene_networks.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    figure_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    format: Mapped[str] = mapped_column(String(12), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        Index("ix_run_figures_run_stage", "run_id", "stage"),
    )


# ── Genes ─────────────────────────────────────────────────────────────────────

class Gene(Base):
    """Gene catalogue, one row per unique gene per species."""
    __tablename__ = "genes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False)
    gene_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    species: Mapped[SpeciesEnum] = mapped_column(SAEnum(SpeciesEnum), nullable=False)
    gene_name: Mapped[Optional[str]] = mapped_column(Text)
    chromosome: Mapped[Optional[str]] = mapped_column(String(50))
    biotype: Mapped[Optional[str]] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("ensembl_id", "species", name="uq_gene_species"),
        Index("ix_gene_symbol_species", "gene_symbol", "species"),
    )


# ── Orthology ─────────────────────────────────────────────────────────────────

class OrthologyMapping(Base):
    """
    Human–mouse one-to-one orthologues.
    Source: Ensembl compara (loaded via seed_orthology.py).
    """
    __tablename__ = "orthology_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    human_ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    mouse_ensembl_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    human_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    mouse_symbol: Mapped[Optional[str]] = mapped_column(String(100))
    orthology_type: Mapped[str] = mapped_column(String(50), default="ortholog_one2one")
    confidence: Mapped[Optional[float]] = mapped_column(Float)  # 0–1
    source: Mapped[Optional[str]] = mapped_column(String(100))
    source_version: Mapped[Optional[str]] = mapped_column(String(50))  # e.g. Ensembl Compara release 116
    source_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    __table_args__ = (
        UniqueConstraint(
            "human_ensembl_id", "mouse_ensembl_id", "source", "source_version",
            name="uq_orthology_source_pair_version",
        ),
        Index("ix_orthology_source_version", "source", "source_version"),
    )


# ── Analysis (top-level job grouping) ─────────────────────────────────────────

class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Configuration snapshot for reproducibility
    config_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    software_versions: Mapped[Optional[dict]] = mapped_column(JSON)
    random_seed: Mapped[int] = mapped_column(Integer, default=42)

    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    project = relationship("Project", back_populates="analyses")
    preprocessing_jobs = relationship("PreprocessingJob", back_populates="analysis", cascade="all, delete-orphan")
    deg_results = relationship("DEGResult", back_populates="analysis", cascade="all, delete-orphan")
    networks = relationship("GeneNetwork", back_populates="analysis", cascade="all, delete-orphan")
    drift_analyses = relationship("DriftAnalysis", back_populates="analysis", cascade="all, delete-orphan")
    ml_experiments = relationship("MLExperiment", back_populates="analysis", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="analysis", cascade="all, delete-orphan")
    background_jobs = relationship("BackgroundJob", back_populates="analysis", cascade="all, delete-orphan")


# ── Background Jobs ───────────────────────────────────────────────────────────

class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="SET NULL"))
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    progress_message: Mapped[Optional[str]] = mapped_column(Text)
    result_ref: Mapped[Optional[str]] = mapped_column(String(512))  # path or id to result
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_traceback: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    analysis = relationship("Analysis", back_populates="background_jobs")


# ── Preprocessing ─────────────────────────────────────────────────────────────

class PreprocessingJob(Base):
    __tablename__ = "preprocessing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)

    # Parameters (recorded for reproducibility)
    normalization_method: Mapped[NormMethodEnum] = mapped_column(SAEnum(NormMethodEnum), default=NormMethodEnum.LOG2CPM)
    low_expr_threshold: Mapped[float] = mapped_column(Float, default=1.0)
    low_expr_min_samples: Mapped[int] = mapped_column(Integer, default=3)
    min_gene_variance: Mapped[float] = mapped_column(Float, default=0.0)
    remove_duplicates: Mapped[bool] = mapped_column(Boolean, default=True)
    impute_missing: Mapped[bool] = mapped_column(Boolean, default=False)
    batch_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    batch_correction_method: Mapped[Optional[str]] = mapped_column(String(50))
    outlier_detection: Mapped[bool] = mapped_column(Boolean, default=True)

    # Outputs
    n_genes_before: Mapped[Optional[int]] = mapped_column(Integer)
    n_genes_after: Mapped[Optional[int]] = mapped_column(Integer)
    n_samples_before: Mapped[Optional[int]] = mapped_column(Integer)
    n_samples_after: Mapped[Optional[int]] = mapped_column(Integer)
    outlier_samples: Mapped[Optional[List[str]]] = mapped_column(JSON)
    processing_log: Mapped[Optional[str]] = mapped_column(Text)
    output_file_path: Mapped[Optional[str]] = mapped_column(String(512))

    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    analysis = relationship("Analysis", back_populates="preprocessing_jobs")


# ── DEG Results ───────────────────────────────────────────────────────────────

class DEGResult(Base):
    __tablename__ = "deg_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    preprocessing_job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("preprocessing_jobs.id"))

    method: Mapped[str] = mapped_column(String(50), nullable=False)  # DESeq2-pydeseq2, t-test, etc.
    fdr_threshold: Mapped[float] = mapped_column(Float, default=0.05)
    lfc_threshold: Mapped[float] = mapped_column(Float, default=1.0)
    n_deg_total: Mapped[Optional[int]] = mapped_column(Integer)
    n_deg_up: Mapped[Optional[int]] = mapped_column(Integer)
    n_deg_down: Mapped[Optional[int]] = mapped_column(Integer)

    # Full results stored as file path (parquet)
    results_file_path: Mapped[Optional[str]] = mapped_column(String(512))

    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    analysis = relationship("Analysis", back_populates="deg_results")


# ── Gene Networks ─────────────────────────────────────────────────────────────

class GeneNetwork(Base):
    __tablename__ = "gene_networks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    preprocessing_job_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("preprocessing_jobs.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    species: Mapped[SpeciesEnum] = mapped_column(SAEnum(SpeciesEnum), nullable=False)
    disease_state: Mapped[DiseaseStateEnum] = mapped_column(SAEnum(DiseaseStateEnum), nullable=False)

    # Construction parameters
    correlation_method: Mapped[CorrelationMethodEnum] = mapped_column(SAEnum(CorrelationMethodEnum), default=CorrelationMethodEnum.PEARSON)
    correlation_threshold: Mapped[float] = mapped_column(Float, default=0.6)
    fdr_threshold: Mapped[float] = mapped_column(Float, default=0.05)
    top_n_genes: Mapped[Optional[int]] = mapped_column(Integer)
    min_gene_variance: Mapped[float] = mapped_column(Float, default=0.1)

    # Statistics
    n_nodes: Mapped[Optional[int]] = mapped_column(Integer)
    n_edges: Mapped[Optional[int]] = mapped_column(Integer)
    density: Mapped[Optional[float]] = mapped_column(Float)
    avg_clustering_coefficient: Mapped[Optional[float]] = mapped_column(Float)
    avg_degree: Mapped[Optional[float]] = mapped_column(Float)

    # File paths
    adjacency_file_path: Mapped[Optional[str]] = mapped_column(String(512))
    node_features_file_path: Mapped[Optional[str]] = mapped_column(String(512))

    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    analysis = relationship("Analysis", back_populates="networks")
    modules = relationship("NetworkModule", back_populates="network", cascade="all, delete-orphan")


class NetworkModule(Base):
    __tablename__ = "network_modules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    network_id: Mapped[str] = mapped_column(String(36), ForeignKey("gene_networks.id", ondelete="CASCADE"), nullable=False)
    module_id: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "M1", "M2"
    genes: Mapped[List[str]] = mapped_column(JSON, nullable=False)   # list of Ensembl IDs
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    hub_gene: Mapped[Optional[str]] = mapped_column(String(50))
    intra_connectivity: Mapped[Optional[float]] = mapped_column(Float)

    network = relationship("GeneNetwork", back_populates="modules")


# ── Drift Analysis ────────────────────────────────────────────────────────────

class DriftAnalysis(Base):
    __tablename__ = "drift_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    healthy_network_id: Mapped[str] = mapped_column(String(36), ForeignKey("gene_networks.id"), nullable=False)
    disease_network_id: Mapped[str] = mapped_column(String(36), ForeignKey("gene_networks.id"), nullable=False)
    species: Mapped[SpeciesEnum] = mapped_column(SAEnum(SpeciesEnum), nullable=False)

    # Global drift statistics
    n_conserved_edges: Mapped[Optional[int]] = mapped_column(Integer)
    n_gained_edges: Mapped[Optional[int]] = mapped_column(Integer)
    n_lost_edges: Mapped[Optional[int]] = mapped_column(Integer)
    global_drift_score: Mapped[Optional[float]] = mapped_column(Float)

    # File paths for per-gene / per-edge results
    node_drift_file_path: Mapped[Optional[str]] = mapped_column(String(512))
    edge_drift_file_path: Mapped[Optional[str]] = mapped_column(String(512))
    module_drift_file_path: Mapped[Optional[str]] = mapped_column(String(512))

    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    analysis = relationship("Analysis", back_populates="drift_analyses")
    healthy_network = relationship("GeneNetwork", foreign_keys=[healthy_network_id])
    disease_network = relationship("GeneNetwork", foreign_keys=[disease_network_id])


# ── Cross-Species Analysis ────────────────────────────────────────────────────

class CrossSpeciesAnalysis(Base):
    __tablename__ = "cross_species_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    human_drift_id: Mapped[str] = mapped_column(String(36), ForeignKey("drift_analyses.id"), nullable=False)
    mouse_drift_id: Mapped[str] = mapped_column(String(36), ForeignKey("drift_analyses.id"), nullable=False)
    orthology_source_version: Mapped[Optional[str]] = mapped_column(String(50))

    n_orthologous_genes: Mapped[Optional[int]] = mapped_column(Integer)
    n_conserved_drift: Mapped[Optional[int]] = mapped_column(Integer)
    n_human_specific: Mapped[Optional[int]] = mapped_column(Integer)
    n_mouse_specific: Mapped[Optional[int]] = mapped_column(Integer)
    n_divergent: Mapped[Optional[int]] = mapped_column(Integer)
    conservation_score: Mapped[Optional[float]] = mapped_column(Float)  # 0-1

    # File paths
    conserved_genes_file_path: Mapped[Optional[str]] = mapped_column(String(512))
    comparison_file_path: Mapped[Optional[str]] = mapped_column(String(512))

    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    human_drift = relationship("DriftAnalysis", foreign_keys=[human_drift_id])
    mouse_drift = relationship("DriftAnalysis", foreign_keys=[mouse_drift_id])


# ── ML Experiments ────────────────────────────────────────────────────────────

class MLExperiment(Base):
    __tablename__ = "ml_experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    experiment_type: Mapped[ExperimentTypeEnum] = mapped_column(SAEnum(ExperimentTypeEnum), nullable=False)
    model_type: Mapped[MLModelTypeEnum] = mapped_column(SAEnum(MLModelTypeEnum), nullable=False)

    # Dataset references
    training_dataset_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("datasets.id"))
    validation_dataset_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("datasets.id"))
    preprocessing_job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("preprocessing_jobs.id"))
    drift_analysis_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("drift_analyses.id"))
    cross_species_analysis_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("cross_species_analyses.id"))

    # Configuration
    random_seed: Mapped[int] = mapped_column(Integer, default=42)
    cv_folds: Mapped[int] = mapped_column(Integer, default=5)
    test_size: Mapped[float] = mapped_column(Float, default=0.2)
    hyperparams: Mapped[Optional[dict]] = mapped_column(JSON)
    feature_selection_config: Mapped[Optional[dict]] = mapped_column(JSON)
    class_weight: Mapped[Optional[str]] = mapped_column(String(50), default="balanced")

    # Leakage guard flags
    leakage_warnings: Mapped[Optional[List[str]]] = mapped_column(JSON)

    # Results
    n_features_used: Mapped[Optional[int]] = mapped_column(Integer)
    model_file_path: Mapped[Optional[str]] = mapped_column(String(512))
    feature_importance_path: Mapped[Optional[str]] = mapped_column(String(512))

    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    analysis = relationship("Analysis", back_populates="ml_experiments")
    metrics = relationship("ModelMetric", back_populates="experiment", cascade="all, delete-orphan")


class ModelMetric(Base):
    __tablename__ = "model_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    experiment_id: Mapped[str] = mapped_column(String(36), ForeignKey("ml_experiments.id", ondelete="CASCADE"), nullable=False)
    split: Mapped[str] = mapped_column(String(50), nullable=False)  # train / cv / external_val

    auroc: Mapped[Optional[float]] = mapped_column(Float)
    auprc: Mapped[Optional[float]] = mapped_column(Float)
    accuracy: Mapped[Optional[float]] = mapped_column(Float)
    sensitivity: Mapped[Optional[float]] = mapped_column(Float)
    specificity: Mapped[Optional[float]] = mapped_column(Float)
    precision: Mapped[Optional[float]] = mapped_column(Float)
    recall: Mapped[Optional[float]] = mapped_column(Float)
    f1: Mapped[Optional[float]] = mapped_column(Float)
    # 95% CI
    auroc_ci_lower: Mapped[Optional[float]] = mapped_column(Float)
    auroc_ci_upper: Mapped[Optional[float]] = mapped_column(Float)
    # Full confusion matrix
    confusion_matrix: Mapped[Optional[dict]] = mapped_column(JSON)
    calibration_data: Mapped[Optional[dict]] = mapped_column(JSON)

    experiment = relationship("MLExperiment", back_populates="metrics")


# ── Pathway Results ───────────────────────────────────────────────────────────

class PathwayResult(Base):
    __tablename__ = "pathway_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    gene_set: Mapped[str] = mapped_column(String(50), nullable=False)  # GO_BP, KEGG, Reactome
    source: Mapped[str] = mapped_column(String(255), nullable=False)   # drift, deg, conserved
    species: Mapped[SpeciesEnum] = mapped_column(SAEnum(SpeciesEnum), nullable=False)

    # Full results file
    results_file_path: Mapped[Optional[str]] = mapped_column(String(512))
    n_significant: Mapped[Optional[int]] = mapped_column(Integer)
    fdr_threshold: Mapped[float] = mapped_column(Float, default=0.05)

    status: Mapped[JobStatusEnum] = mapped_column(SAEnum(JobStatusEnum), default=JobStatusEnum.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("analyses.id", ondelete="SET NULL"))
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    warning: Mapped[Optional[str]] = mapped_column(Text)  # data-leakage warnings, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    analysis = relationship("Analysis", back_populates="audit_logs")
