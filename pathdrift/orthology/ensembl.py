from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import httpx
import pandas as pd

from .mapping import normalize_mapping

ENSEMBL_REST = "https://rest.ensembl.org"
BIOMART_URL = "https://www.ensembl.org/biomart/martservice"


def fetch_current_release(client: httpx.Client) -> int:
    response = client.get(f"{ENSEMBL_REST}/info/data")
    response.raise_for_status()
    releases = response.json().get("releases", [])
    if not releases:
        raise RuntimeError("Ensembl did not report a current data release.")
    return int(max(releases))


def fetch_human_mouse_homologies(timeout: float = 300.0) -> tuple[pd.DataFrame, dict]:
    query = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE Query>
<Query virtualSchemaName="default" formatter="TSV" header="1" uniqueRows="1" count="" datasetConfigVersion="0.6">
  <Dataset name="hsapiens_gene_ensembl" interface="default">
    <Filter name="with_mmusculus_homolog" excluded="0" />
    <Attribute name="ensembl_gene_id" />
    <Attribute name="external_gene_name" />
    <Attribute name="mmusculus_homolog_ensembl_gene" />
    <Attribute name="mmusculus_homolog_associated_gene_name" />
    <Attribute name="mmusculus_homolog_orthology_type" />
    <Attribute name="mmusculus_homolog_orthology_confidence" />
  </Dataset>
</Query>"""
    with httpx.Client(
        timeout=timeout,
        headers={"Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        release = fetch_current_release(client)
        response = client.get(
            BIOMART_URL,
            params={"query": query},
            headers={"Accept": "text/plain"},
        )
        response.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(response.text), delimiter="\t"))
    if not rows:
        raise RuntimeError("Ensembl BioMart returned no human-mouse homologies.")
    frame = pd.DataFrame(rows).rename(columns={
        "Gene stable ID": "human_ensembl_id",
        "Gene name": "human_symbol",
        "Mouse gene stable ID": "mouse_ensembl_id",
        "Mouse gene name": "mouse_symbol",
        "Mouse homology type": "orthology_type",
        "Mouse orthology confidence [0 low, 1 high]": "confidence",
    })
    frame = frame.dropna(subset=["human_ensembl_id", "mouse_ensembl_id", "orthology_type"])
    frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce")
    if frame["confidence"].dropna().lt(0).any() or frame["confidence"].dropna().gt(1).any():
        raise ValueError("Ensembl returned orthology confidence outside [0, 1].")
    normalized = normalize_mapping(frame)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "source": "Ensembl Compara BioMart",
        "source_version": f"Ensembl Compara release {release}",
        "ensembl_release": release,
        "retrieved_at": retrieved_at,
        "endpoint": str(response.url.copy_with(query=None)),
        "species": ["homo_sapiens", "mus_musculus"],
        "attributes": [
            "ensembl_gene_id",
            "external_gene_name",
            "mmusculus_homolog_ensembl_gene",
            "mmusculus_homolog_associated_gene_name",
            "mmusculus_homolog_orthology_type",
            "mmusculus_homolog_orthology_confidence",
        ],
        "mapping_count": len(normalized),
    }
    normalized["source"] = metadata["source"]
    normalized["source_version"] = metadata["source_version"]
    return normalized, metadata
