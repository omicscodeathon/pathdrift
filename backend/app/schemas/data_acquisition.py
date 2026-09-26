from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SamplePreview(BaseModel):
    sample_id: str
    disease_state: str
    label: str


class DatasetCandidate(BaseModel):
    id: str
    name: str
    repository: str
    species: str
    condition: str
    tissue: str
    sample_count: int
    data_type: str
    expression_available: bool = True
    metadata_available: bool = True
    suitability_score: int = 0
    suitability_reasons: List[str] = Field(default_factory=list)
    accessions: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    sample_preview: List[SamplePreview] = Field(default_factory=list)


class DatasetSelectionRequest(BaseModel):
    disease: str = "Breast Cancer"
    species: List[str] = Field(default_factory=lambda: ["Human", "Mouse"])
    selected_ids: List[str] = Field(default_factory=list)
    analysis_type: str = "Cross-Species Network Drift"


class DownloadRequest(BaseModel):
    project_id: str
    selected_ids: List[str] = Field(default_factory=list)
    disease: str = "Breast Cancer"


class ValidationRequest(BaseModel):
    dataset_id: str
    file_path: Optional[str] = None


class ProcessingRequest(BaseModel):
    dataset_id: str
    file_path: Optional[str] = None


class AcquiredDataset(BaseModel):
    id: str
    name: str
    repository: str
    accession: str
    species: str
    tissue: str
    condition: str
    disease: str
    data_type: str
    sample_count: int
    gene_count: Optional[int] = None
    status: str = "ready"
    suitability_score: int = 0
    source_url: Optional[str] = None
    created_at: Optional[str] = None


class SearchResponse(BaseModel):
    disease: str
    species: List[str]
    datasets: List[DatasetCandidate]
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    message: str
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class ManifestResponse(BaseModel):
    path: str
    created_at: str
