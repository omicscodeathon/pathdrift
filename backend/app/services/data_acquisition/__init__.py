"""Additive data acquisition engine for PathDrift.

This module is intentionally isolated from the existing analysis pipeline and only
provides dataset discovery, ranking, download orchestration, validation, and
preprocessing for public biomedical datasets. It is designed to be extended for
future diseases/species without disturbing the existing PathDrift architecture.
"""

from .dataset_manager import ensure_data_directories, write_manifest
from .dataset_scoring import score_geo_dataset, score_dataset_list
from .validator import validate_expression_matrix, validate_metadata_file
from .preprocessing import normalize_gene_ids, preprocess_expression_matrix

__all__ = [
    "ensure_data_directories",
    "write_manifest",
    "score_geo_dataset",
    "score_dataset_list",
    "validate_expression_matrix",
    "validate_metadata_file",
    "normalize_gene_ids",
    "preprocess_expression_matrix",
]
