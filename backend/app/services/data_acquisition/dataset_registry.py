from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MANIFEST = ROOT / "data" / "pathdrift" / "manifests" / "dataset_manifest.json"
DEFAULT_REGISTRY = ROOT / "data" / "registry" / "datasets.yaml"
REQUIRED_FIELDS = (
    "accession",
    "source",
    "species",
    "tissue",
    "disease",
    "platform",
    "data_type",
    "genome_build",
    "download_date",
    "samples",
    "genes",
)
GENE_ID_PATTERNS = {
    "human": re.compile(r"^ENSG\d+(?:_PAR_Y)?$"),
    "mouse": re.compile(r"^ENSMUSG\d+$"),
}


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _relative_path(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _resolve_path(value).relative_to(ROOT).as_posix()
    except ValueError:
        return value


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _read_expression_gene_ids(path: Path) -> list[str]:
    frame = pd.read_csv(path, sep="\t", compression="infer", usecols=[0], dtype=str, low_memory=False)
    return frame.iloc[:, 0].fillna("").astype(str).str.strip().tolist()


def _stable_ensembl_ids(gene_ids: list[str], species: str) -> tuple[list[str], list[str]]:
    pattern = GENE_ID_PATTERNS.get(species.lower())
    if pattern is None:
        raise ValueError(f"Unsupported registry species: {species}")
    stable_ids = [re.sub(r"\.\d+(?=_PAR_Y$|$)", "", gene_id) for gene_id in gene_ids]
    valid = sorted({gene_id for gene_id in stable_ids if pattern.fullmatch(gene_id)})
    excluded = sorted({gene_id for gene_id in stable_ids if gene_id and not pattern.fullmatch(gene_id)})
    return valid, excluded


def _tcga_samples(metadata_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records = _read_tsv(metadata_path)
    seen_case_states: set[tuple[str, str]] = set()
    analysis_sample_ids: list[str] = []
    samples = []
    for row in records:
        case_id = row.get("case_id") or row.get("case_submitter_id") or ""
        state = row.get("disease_state", "")
        key = (case_id, state)
        included = bool(case_id) and key not in seen_case_states
        if included:
            seen_case_states.add(key)
            analysis_sample_ids.append(row.get("sample_id", ""))
        samples.append({
            "sample_id": row.get("sample_id"),
            "sample_type": row.get("sample_type"),
            "disease_state": state,
            "case_uuid": row.get("case_uuid"),
            "case_submitter_id": row.get("case_submitter_id"),
            "sample_uuid": row.get("sample_uuid"),
            "aliquot_uuid": row.get("aliquot_uuid"),
            "aliquot_submitter_id": row.get("aliquot_submitter_id"),
            "file_uuid": row.get("file_uuid"),
            "file_name": row.get("file_name"),
            "included_in_patient_grouped_analysis": included,
        })
    return samples, analysis_sample_ids


def _geo_samples(metadata_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records = _read_tsv(metadata_path)
    samples = []
    in_vivo_ids = []
    for row in records:
        title = row.get("geo_title", "")
        origin = "cultured tumor cell line" if "cell line" in title.lower() else "in-vivo mammary tumor cells"
        sample_id = row.get("sample_id", "")
        if origin == "in-vivo mammary tumor cells":
            in_vivo_ids.append(sample_id)
        samples.append({
            "expression_column": sample_id,
            "geo_sample_id": row.get("geo_sample_id"),
            "biosample_accession": row.get("biosample_accession"),
            "sra_accession": row.get("sra_accession"),
            "title": title,
            "origin": origin,
            "source_name": row.get("geo_source_name"),
            "characteristics": row.get("geo_characteristics"),
        })
    return samples, in_vivo_ids


def _geo_normal_samples(metadata_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records = _read_tsv(metadata_path)
    samples = []
    analysis_sample_ids = []
    for row in records:
        sample_id = row.get("sample_id", "")
        analysis_sample_ids.append(sample_id)
        samples.append({
            "expression_column": sample_id,
            "geo_sample_id": row.get("geo_sample_id"),
            "title": row.get("geo_title"),
            "disease_state": row.get("disease_state"),
            "source_name": row.get("geo_source_name"),
            "tissue": row.get("tissue"),
        })
    return samples, analysis_sample_ids


def build_dataset_registry(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = []
    for entry in manifest.get("datasets", []):
        accession = entry.get("accession")
        if accession not in {"TCGA-BRCA", "GSE155577", "GSE116385"}:
            continue
        metadata_path = _resolve_path(entry["metadata_path"])
        expression_path = _resolve_path(entry["raw_expression_path"])
        if accession == "TCGA-BRCA":
            species = "human"
            sample_records, analysis_sample_ids = _tcga_samples(metadata_path)
            analysis_sample_count = len(analysis_sample_ids)
            uses_ensembl_ids = True
        elif accession == "GSE155577":
            species = "mouse"
            sample_records, analysis_sample_ids = _geo_samples(metadata_path)
            analysis_sample_count = len(analysis_sample_ids)
            uses_ensembl_ids = True
        else:
            species = "mouse"
            sample_records, analysis_sample_ids = _geo_normal_samples(metadata_path)
            analysis_sample_count = len(analysis_sample_ids)
            uses_ensembl_ids = False

        raw_gene_ids = _read_expression_gene_ids(expression_path)
        if uses_ensembl_ids:
            stable_ids, excluded_ids = _stable_ensembl_ids(raw_gene_ids, species)
            primary_identifier = "Ensembl Gene ID"
            species_id_pattern = "^ENSG[0-9]+(_PAR_Y)?$" if species == "human" else "^ENSMUSG[0-9]+$"
        else:
            stable_ids = sorted({gene_id for gene_id in raw_gene_ids if gene_id})
            excluded_ids = []
            primary_identifier = "Mouse gene symbol (source-provided)"
            species_id_pattern = None
        download_date = (entry.get("download_date") or entry.get("updated_at") or entry.get("created_at") or "").split("T")[0]
        dataset = {
            "accession": accession,
            "source": entry.get("repository"),
            "species": entry.get("species"),
            "tissue": entry.get("tissue"),
            "disease": entry.get("disease"),
            "platform": entry.get("platform"),
            "data_type": entry.get("source_data_type") or entry.get("data_type"),
            "genome_build": entry.get("genome_build"),
            "download_date": download_date,
            "samples": {
                "raw_count": len(sample_records),
                "analysis_count": analysis_sample_count,
                "metadata_path": metadata_path.relative_to(ROOT).as_posix(),
                "records": sample_records,
            },
            "genes": {
                "raw_row_count": len(raw_gene_ids),
                "unique_primary_gene_identifiers": len(stable_ids),
                "analysis_count_after_preprocessing": int(entry.get("n_genes", entry.get("gene_count", len(stable_ids)))),
                "primary_identifier": primary_identifier,
                "species_id_pattern": species_id_pattern,
                "primary_identifier_examples": stable_ids[:5],
                "excluded_unmapped_ids": excluded_ids,
                "expression_path": expression_path.relative_to(ROOT).as_posix(),
                "processed_expression_path": _relative_path(entry.get("processed_expression_path")),
            },
        }
        missing = [field for field in REQUIRED_FIELDS if dataset.get(field) in (None, "")]
        if missing:
            raise ValueError(f"{accession} is missing required registry fields: {missing}")
        datasets.append(dataset)

    if not datasets:
        raise ValueError("No supported expression datasets were found in the manifest")
    if len({dataset["accession"] for dataset in datasets}) != len(datasets):
        raise ValueError("Dataset registry accessions must be unique")

    return {
        "registry_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "identifier_policy": {
            "primary_gene_identifier": "Ensembl Gene ID",
            "human_pattern": "^ENSG[0-9]+(_PAR_Y)?$",
            "mouse_pattern": "^ENSMUSG[0-9]+$",
            "gene_symbols": "Display labels only; symbol conversion must use an explicit accessioned mapping table.",
            "other_identifier_systems": "Entrez, UniProt, and STRING IDs must remain separate columns and require an explicit source/versioned mapping before use.",
        },
        "datasets": datasets,
    }


def write_dataset_registry(
    manifest_path: Path = DEFAULT_MANIFEST,
    registry_path: Path = DEFAULT_REGISTRY,
) -> Path:
    registry = build_dataset_registry(manifest_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False, allow_unicode=False), encoding="utf-8")
    return registry_path