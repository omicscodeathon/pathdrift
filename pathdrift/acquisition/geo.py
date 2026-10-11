from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from .downloader import DownloadReceipt, copy_cached_file


EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def validate_geo_accession(accession: str, expected_species: str = "Mus musculus") -> dict[str, Any]:
    normalized = accession.strip().upper()
    if not normalized.startswith("GSE") or not normalized[3:].isdigit():
        raise ValueError(f"Invalid GEO series accession: {accession!r}")
    with httpx.Client(timeout=45) as client:
        search = client.get(
            f"{EUTILS}/esearch.fcgi",
            params={"db": "gds", "term": f"{normalized}[Accession]", "retmode": "json"},
        )
        search.raise_for_status()
        identifiers = search.json().get("esearchresult", {}).get("idlist", [])
        if not identifiers:
            raise ValueError(f"GEO accession does not exist: {normalized}")
        summary = client.get(
            f"{EUTILS}/esummary.fcgi",
            params={"db": "gds", "id": ",".join(identifiers), "retmode": "json"},
        )
        summary.raise_for_status()
    records = summary.json().get("result", {})
    record = next((records.get(identifier) for identifier in identifiers if records.get(identifier, {}).get("accession") == normalized), None)
    if not record:
        raise ValueError(f"NCBI GEO did not return an exact record for {normalized}")
    title = str(record.get("title") or "")
    description = str(record.get("summary") or "")
    taxon = str(record.get("taxon") or "")
    if expected_species.casefold() not in taxon.casefold():
        raise ValueError(f"{normalized} organism is {taxon!r}, expected {expected_species!r}")
    subject = f"{title} {description}".casefold()
    if not any(term in subject for term in ("mammary", "breast")):
        raise ValueError(f"{normalized} is not documented as breast/mammary tissue")
    if not any(term in subject for term in ("tumor", "tumour", "cancer", "carcinoma")):
        raise ValueError(f"{normalized} is not documented as a cancer/tumor study")
    sample_count = int(record.get("n_samples") or 0)
    if sample_count < 2:
        raise ValueError(f"{normalized} has fewer than two GEO samples")
    return {
        "accession": normalized,
        "title": title,
        "summary": description,
        "species": taxon,
        "platform_id": record.get("gpl"),
        "series_sample_count": sample_count,
        "retrieval_url": f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={normalized}",
        "metadata_url": f"{EUTILS}/esummary.fcgi?db=gds&id={identifiers[0]}&retmode=json",
    }


def acquire_geo(config: dict[str, Any], raw_dir: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    accession = str(config.get("accession", "")).strip().upper()
    if not accession:
        raise ValueError("Mouse GEO accession is required; configure datasets.mouse.accession")
    source_info = validate_geo_accession(accession, str(config.get("organism", "Mus musculus")))
    source_expression = config.get("expression_file")
    source_metadata = config.get("metadata_file")
    target_dir = Path(raw_dir)
    expression_path = target_dir / f"{accession}_expression.tsv.gz"
    metadata_path = target_dir / f"{accession}_metadata.tsv"
    if source_expression and source_metadata:
        expression_receipt = copy_cached_file(
            source_expression,
            expression_path,
            expected_sha256=config.get("expression_sha256"),
        )
        metadata_receipt = copy_cached_file(
            source_metadata,
            metadata_path,
            expected_sha256=config.get("metadata_sha256"),
        )
    else:
        backend_root = Path(__file__).resolve().parents[2] / "backend"
        sys.path.insert(0, str(backend_root))
        from scripts.acquire_real_breast_data import download_geo_series

        expression_path, metadata_path = download_geo_series(accession, target_dir)
        from .downloader import sha256_file

        expression_receipt = DownloadReceipt(str(expression_path.resolve()), sha256_file(expression_path), expression_path.stat().st_size, False, False, source_info["retrieval_url"])
        metadata_receipt = DownloadReceipt(str(metadata_path.resolve()), sha256_file(metadata_path), metadata_path.stat().st_size, False, False, source_info["metadata_url"])
    metadata = pd.read_csv(metadata_path, sep="\t", dtype=str).fillna("")
    if len(metadata) != source_info["series_sample_count"]:
        raise ValueError(
            f"GEO metadata contains {len(metadata)} samples but NCBI reports {source_info['series_sample_count']}"
        )
    if "geo_sample_id" not in metadata or metadata["geo_sample_id"].eq("").any():
        raise ValueError("GEO sample metadata must retain each GSM accession")
    source_info.update({
        "source": "GEO",
        "data_type": str(config.get("data_type", "normalized")),
        "platform": source_info.get("platform_id"),
        "expression": expression_receipt.__dict__,
        "metadata": metadata_receipt.__dict__,
    })
    return Path(expression_path), Path(metadata_path), source_info