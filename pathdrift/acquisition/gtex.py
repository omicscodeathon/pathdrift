from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .downloader import download_file


GTEX_V10_GCT_URL = "https://storage.googleapis.com/gtex_analysis_v10/rna_seq_data/GTEx_Analysis_v10_RNASeQCv2.4.2_gene_tpm.gct.gz"
GTEX_V10_SAMPLE_ATTRIBUTES_URL = "https://storage.googleapis.com/gtex_analysis_v10/annotations/GTEx_Analysis_v10_Annotations_SampleAttributesDS.txt"


def acquire_gtex_breast_reference(reference_dir: str | Path, version: str = "v10") -> tuple[Path, Path, dict[str, Any]]:
    """Download official GTEx v10 TPM and sample attributes, then retain breast samples."""
    if version.casefold() != "v10":
        raise ValueError("Only the explicitly versioned GTEx v10 resource is currently supported")
    root = Path(reference_dir)
    source_dir = root / "gtex" / version
    matrix_source = source_dir / "GTEx_Analysis_v10_RNASeQCv2.4.2_gene_tpm.gct.gz"
    attributes_path = source_dir / "GTEx_Analysis_v10_Annotations_SampleAttributesDS.txt"
    matrix_receipt = download_file(GTEX_V10_GCT_URL, matrix_source)
    attributes_receipt = download_file(GTEX_V10_SAMPLE_ATTRIBUTES_URL, attributes_path)

    attributes = pd.read_csv(attributes_path, sep="\t", dtype=str).fillna("")
    tissue_column = "SMTSD"
    sample_column = "SAMPID"
    if tissue_column not in attributes or sample_column not in attributes:
        raise ValueError("GTEx sample-attribute file lacks SMTSD/SAMPID fields")
    breast = attributes[attributes[tissue_column].str.casefold().eq("breast - mammary tissue".casefold())].copy()
    if breast.empty:
        raise ValueError("GTEx v10 metadata contains no breast mammary tissue samples")

    selected_samples = breast[sample_column].astype(str).tolist()
    header = pd.read_csv(matrix_source, sep="\t", compression="gzip", skiprows=2, nrows=0).columns.tolist()
    if "Name" not in header or not set(selected_samples).issubset(header):
        missing = sorted(set(selected_samples) - set(header))
        raise ValueError(f"GTEx TPM matrix does not contain all breast sample IDs: {missing[:10]}")
    use_columns = {"Name", "Description", *selected_samples}
    output_matrix = root / "processed" / "reference" / "gtex_v10_breast_tpm.tsv"
    output_matrix.parent.mkdir(parents=True, exist_ok=True)
    first = True
    for chunk in pd.read_csv(
        matrix_source,
        sep="\t",
        compression="gzip",
        skiprows=2,
        usecols=lambda column: column in use_columns,
        chunksize=5000,
    ):
        chunk = chunk.drop(columns=["Description"], errors="ignore").rename(columns={"Name": "gene_id"})
        chunk.to_csv(output_matrix, sep="\t", index=False, mode="w" if first else "a", header=first)
        first = False

    metadata = breast.rename(columns={sample_column: "sample_id", tissue_column: "tissue"})
    metadata["disease_state"] = "healthy"
    metadata["accession"] = "GTEx v10"
    metadata_path = root / "processed" / "reference" / "gtex_v10_breast_metadata.tsv"
    metadata.to_csv(metadata_path, sep="\t", index=False)
    return output_matrix, metadata_path, {
        "source": "GTEx",
        "accession": "GTEx v10",
        "version": "v10",
        "tissue": "Breast - Mammary Tissue",
        "sample_count": len(breast),
        "data_type": "tpm",
        "retrieval_urls": [GTEX_V10_GCT_URL, GTEX_V10_SAMPLE_ATTRIBUTES_URL],
        "checksums": {"matrix": matrix_receipt.sha256, "sample_attributes": attributes_receipt.sha256},
        "cache_verified": matrix_receipt.checksum_verified and attributes_receipt.checksum_verified,
    }