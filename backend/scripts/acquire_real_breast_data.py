from __future__ import annotations

import gzip
import io
import json
import re
import sys
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bio.preprocessing import PreprocessingPipeline
from app.bio.identifiers import enforce_ensembl_gene_ids

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "uploads" / "data_acquisition"
RAW_ROOT = DATA_ROOT / "raw"
PROCESSED_ROOT = DATA_ROOT / "processed"
MANIFEST_PATH = DATA_ROOT / "manifests" / "dataset_manifest.json"


def fetch_with_retry(url: str, *, timeout: float = 180, max_retries: int = 5) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Python-urllib/3.11"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return httpx.Response(
                    status_code=response.status,
                    headers=dict(response.headers),
                    content=response.read(),
                    request=httpx.Request("GET", url),
                )
        except Exception as exc:  # pragma: no cover - retry loop for transient network errors
            last_error = exc
            if attempt < max_retries:
                continue
    raise last_error or RuntimeError(f"Failed to fetch {url}")

RAW_ROOT.mkdir(parents=True, exist_ok=True)
PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)


def _download_tcga_count_file(hit: dict, state: str) -> tuple[str, dict[str, str], dict[str, float]] | None:
    file_id = hit["file_id"]
    cases = hit.get("cases") or [{}]
    samples = cases[0].get("samples") or [{}]
    sample = samples[0]
    portions = sample.get("portions") or [{}]
    analytes = portions[0].get("analytes") or [{}]
    aliquots = analytes[0].get("aliquots") or [{}]
    aliquot = aliquots[0]
    sample_id = sample.get("submitter_id") or cases[0].get("submitter_id") or hit.get("file_name") or file_id
    url = f"https://api.gdc.cancer.gov/data/{file_id}"
    resp = fetch_with_retry(url, timeout=180, max_retries=5)
    payload = resp.content
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    counts: dict[str, float] = {}
    for line in payload.decode("utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4 or parts[0].startswith("N_") or parts[0] in {"gene_id", "GeneID"}:
            continue
        try:
            counts[parts[0]] = float(parts[3])
        except ValueError:
            continue

    if not counts:
        return None

    metadata_row = {
        "sample_id": sample_id,
        "sample_uuid": sample.get("sample_id"),
        "sample_type": sample.get("sample_type"),
        "case_id": cases[0].get("case_id"),
        "case_submitter_id": cases[0].get("submitter_id"),
        "file_uuid": file_id,
        "file_name": hit.get("file_name"),
        "aliquot_uuid": aliquot.get("aliquot_id"),
        "aliquot_submitter_id": aliquot.get("submitter_id"),
        "disease_state": state,
    }
    return sample_id, metadata_row, counts


def download_tcga_brca_subset(output_dir: Path, limit_per_group: int = 6, max_workers: int = 4) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    hits_by_state: list[tuple[dict, str]] = []
    with httpx.Client(timeout=120) as client:
        for sample_type, state in (("Primary Tumor", "cancer"), ("Solid Tissue Normal", "healthy")):
            filters = {
                "op": "and",
                "content": [
                    {"op": "=", "content": {"field": "cases.project.project_id", "value": "TCGA-BRCA"}},
                    {"op": "=", "content": {"field": "data_type", "value": "Gene Expression Quantification"}},
                    {"op": "=", "content": {"field": "analysis.workflow_type", "value": "STAR - Counts"}},
                    {"op": "=", "content": {"field": "cases.samples.sample_type", "value": sample_type}},
                ],
            }
            resp = client.post(
                "https://api.gdc.cancer.gov/files",
                json={
                    "filters": filters,
                    "fields": (
                        "file_id,file_name,cases.case_id,cases.submitter_id,"
                        "cases.samples.sample_id,cases.samples.submitter_id,cases.samples.sample_type,"
                        "cases.samples.portions.analytes.aliquots.aliquot_id,"
                        "cases.samples.portions.analytes.aliquots.submitter_id"
                    ),
                    "format": "JSON",
                    "size": max(limit_per_group * 8, 32),
                },
            )
            resp.raise_for_status()
            seen_cases: set[str] = set()
            for hit in resp.json().get("data", {}).get("hits", []):
                cases = hit.get("cases") or [{}]
                case_id = cases[0].get("submitter_id")
                if not case_id or case_id in seen_cases:
                    continue
                seen_cases.add(case_id)
                hits_by_state.append((hit, state))
                if len(seen_cases) >= limit_per_group:
                    break

    expression_by_sample: dict[str, dict[str, float]] = {}
    metadata_rows: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_download_tcga_count_file, hit, state): (hit, state) for hit, state in hits_by_state}
        for future in as_completed(future_map):
            result = future.result()
            if result is None:
                continue
            sample_id, metadata_row, counts = result
            expression_by_sample[sample_id] = counts
            metadata_rows.append(metadata_row)

    if not expression_by_sample:
        raise RuntimeError("No parseable GDC STAR-count data downloaded for TCGA-BRCA")

    expr_df = pd.DataFrame(expression_by_sample).fillna(0)
    expr_df.index.name = "gene_id"
    expr_path = output_dir / "tcga_brca_real_expression.tsv.gz"
    expr_df.to_csv(expr_path, sep="\t", compression="gzip")
    meta_path = output_dir / "tcga_brca_real_metadata.tsv"
    pd.DataFrame(metadata_rows).to_csv(meta_path, sep="\t", index=False)
    enrich_tcga_metadata(expr_path, meta_path)
    return expr_path, meta_path


def enrich_tcga_metadata(expression_path: Path, metadata_path: Path) -> pd.DataFrame:
    metadata = pd.read_csv(metadata_path, sep="\t", dtype=str).fillna("")
    expression_header = pd.read_csv(expression_path, sep="\t", compression="gzip", nrows=0).columns[1:]
    sample_ids = [str(sample_id) for sample_id in expression_header]
    if not sample_ids:
        raise ValueError("TCGA expression matrix has no sample columns")

    filters = {
        "op": "and",
        "content": [
            {"op": "=", "content": {"field": "cases.project.project_id", "value": "TCGA-BRCA"}},
            {"op": "=", "content": {"field": "data_type", "value": "Gene Expression Quantification"}},
            {"op": "=", "content": {"field": "analysis.workflow_type", "value": "STAR - Counts"}},
            {"op": "in", "content": {"field": "cases.samples.submitter_id", "value": sample_ids}},
        ],
    }
    fields = (
        "file_id,file_name,cases.case_id,cases.submitter_id,"
        "cases.samples.sample_id,cases.samples.submitter_id,cases.samples.sample_type,"
        "cases.samples.portions.analytes.aliquots.aliquot_id,"
        "cases.samples.portions.analytes.aliquots.submitter_id"
    )
    with httpx.Client(timeout=120) as client:
        file_response = client.post(
            "https://api.gdc.cancer.gov/files",
            json={"filters": filters, "fields": fields, "format": "JSON", "size": max(len(sample_ids) * 5, 100)},
        )
        file_response.raise_for_status()

    records: dict[str, dict[str, object]] = {}
    for hit in file_response.json().get("data", {}).get("hits", []):
        cases = hit.get("cases") or [{}]
        case = cases[0]
        for sample in case.get("samples") or []:
            sample_submitter_id = sample.get("submitter_id")
            if sample_submitter_id not in sample_ids or sample_submitter_id in records:
                continue
            portions = sample.get("portions") or [{}]
            analytes = portions[0].get("analytes") or [{}]
            aliquots = analytes[0].get("aliquots") or [{}]
            aliquot = aliquots[0]
            records[sample_submitter_id] = {
                "file_uuid": hit.get("file_id"),
                "file_name": hit.get("file_name"),
                "case_uuid": case.get("case_id"),
                "case_submitter_id": case.get("submitter_id"),
                "sample_uuid": sample.get("sample_id"),
                "sample_type": sample.get("sample_type"),
                "aliquot_uuid": aliquot.get("aliquot_id"),
                "aliquot_submitter_id": aliquot.get("submitter_id"),
            }
    missing_samples = sorted(set(sample_ids) - set(records))
    if missing_samples:
        raise RuntimeError(f"GDC metadata did not resolve expression samples: {missing_samples}")

    case_uuids = sorted({str(record["case_uuid"]) for record in records.values() if record.get("case_uuid")})
    clinical_fields = (
        "case_id,submitter_id,demographic.sex_at_birth,demographic.race,demographic.ethnicity,"
        "demographic.days_to_birth,demographic.vital_status,demographic.age_at_index,"
        "diagnoses.age_at_diagnosis,diagnoses.ajcc_pathologic_stage,diagnoses.primary_diagnosis,"
        "diagnoses.tumor_grade,diagnoses.days_to_last_follow_up,diagnoses.morphology,"
        "diagnoses.diagnosis_is_primary_disease"
    )
    clinical_by_case: dict[str, dict[str, object]] = {}
    if case_uuids:
        with httpx.Client(timeout=120) as client:
            clinical_response = client.post(
                "https://api.gdc.cancer.gov/cases",
                json={
                    "filters": {"op": "in", "content": {"field": "case_id", "value": case_uuids}},
                    "fields": clinical_fields,
                    "expand": "demographic,diagnoses",
                    "format": "JSON",
                    "size": len(case_uuids),
                },
            )
            clinical_response.raise_for_status()
        for case in clinical_response.json().get("data", {}).get("hits", []):
            diagnoses = case.get("diagnoses") or []
            diagnosis = next(
                (item for item in diagnoses if item.get("diagnosis_is_primary_disease") is True),
                diagnoses[0] if diagnoses else {},
            )
            demographic = case.get("demographic") or {}
            clinical_by_case[case.get("case_id", "")] = {
                "sex_at_birth": demographic.get("sex_at_birth"),
                "race": demographic.get("race"),
                "ethnicity": demographic.get("ethnicity"),
                "days_to_birth": demographic.get("days_to_birth"),
                "age_at_index_years": demographic.get("age_at_index"),
                "vital_status": demographic.get("vital_status"),
                "age_at_diagnosis_days": diagnosis.get("age_at_diagnosis"),
                "ajcc_pathologic_stage": diagnosis.get("ajcc_pathologic_stage"),
                "primary_diagnosis": diagnosis.get("primary_diagnosis"),
                "tumor_grade": diagnosis.get("tumor_grade"),
                "morphology": diagnosis.get("morphology"),
                "days_to_last_follow_up": diagnosis.get("days_to_last_follow_up"),
            }

    enriched_rows = []
    previous_by_sample = metadata.set_index("sample_id").to_dict(orient="index")
    for sample_id in sample_ids:
        source = records[sample_id]
        row = {**previous_by_sample.get(sample_id, {}), **source}
        row["sample_id"] = sample_id
        row["case_id"] = source.get("case_submitter_id")
        row.update(clinical_by_case.get(str(source.get("case_uuid") or ""), {}))
        enriched_rows.append(row)
    enriched = pd.DataFrame(enriched_rows)
    enriched.to_csv(metadata_path, sep="\t", index=False)
    return enriched


def download_geo_series(accession: str, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    series_dir = f"{accession[:-3]}nnn"
    prefix = f"https://ftp.ncbi.nlm.nih.gov/geo/series/{series_dir}/{accession}/suppl/"
    listing = fetch_with_retry(prefix).text
    match = re.search(r'href="([^"]+\.(?:csv|txt)\.gz)"', listing, re.IGNORECASE)
    if not match:
        raise RuntimeError(f"No downloadable expression file found in GEO supplement listing for {accession}")
    file_name = match.group(1)
    file_url = prefix + file_name

    resp = fetch_with_retry(file_url, timeout=300, max_retries=5)

    payload = gzip.decompress(resp.content)
    df = pd.read_csv(io.BytesIO(payload), sep=",", compression="infer")
    df = df.rename(columns={df.columns[0]: "gene_id"})
    import GEOparse

    gse = GEOparse.get_GEO(geo=accession, destdir=str(output_dir / "geo_cache"), silent=True)
    gsm_by_expression_sample: dict[str, dict[str, object]] = {}
    for gsm_id, gsm in gse.gsms.items():
        descriptions = gsm.metadata.get("description", [])
        expression_label = next(
            (match.group(0).lower() for value in descriptions if (match := re.search(r"sample\s*\d+", str(value), re.IGNORECASE))),
            None,
        )
        if not expression_label:
            continue
        characteristics = gsm.metadata.get("characteristics_ch1", [])
        relations = gsm.metadata.get("relation", [])
        gsm_by_expression_sample[expression_label] = {
            "geo_sample_id": gsm_id,
            "geo_title": " ".join(gsm.metadata.get("title", [])),
            "geo_source_name": " ".join(gsm.metadata.get("source_name_ch1", [])),
            "geo_characteristics": " | ".join(map(str, characteristics)),
            "biosample_accession": next((m.group(1) for value in relations if (m := re.search(r"biosample/(SAMN\d+)", str(value), re.IGNORECASE))), None),
            "sra_accession": next((m.group(1) for value in relations if (m := re.search(r"term=(SRX\d+)", str(value), re.IGNORECASE))), None),
        }
    expr_path = output_dir / f"{accession}_expression.tsv.gz"
    df.to_csv(expr_path, sep="\t", index=False, compression="gzip")

    sample_rows: list[dict[str, str]] = []
    for sample_name in df.columns[1:]:
        source_metadata = gsm_by_expression_sample.get(str(sample_name).lower())
        if source_metadata is None:
            raise ValueError(f"Could not map GEO expression column {sample_name} to an actual GSM record")
        sample_rows.append({
            "sample_id": sample_name,
            "disease_state": "cancer",
            **source_metadata,
        })
    meta_path = output_dir / f"{accession}_metadata.tsv"
    pd.DataFrame(sample_rows).to_csv(meta_path, sep="\t", index=False)
    return expr_path, meta_path


def download_geo_normal_mammary(output_dir: Path) -> tuple[Path, Path]:
    accession = "GSE116385"
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE116nnn/GSE116385/"
    source_name = "GSE116385_Normal_mammary_RNAseq_RPKM.csv.gz"
    source_path = output_dir / source_name
    source_path.write_bytes(fetch_with_retry(prefix + "suppl/" + source_name).content)

    matrix_name = "GSE116385_series_matrix.txt.gz"
    series_matrix_path = output_dir / matrix_name
    series_matrix_path.write_bytes(fetch_with_retry(prefix + "matrix/" + matrix_name).content)

    expression = pd.read_csv(source_path, compression="gzip", low_memory=False)
    expression = expression.rename(columns={expression.columns[0]: "gene_id"})
    expression_path = output_dir / f"{accession}_expression.tsv.gz"
    expression.to_csv(expression_path, sep="\t", index=False, compression="gzip")

    sample_details = {
        "Ba1": ("GSM3230416", "normal adult basal cells sample1"),
        "Ba2": ("GSM3230417", "normal adult basal cells sample2"),
        "fMaSC1": ("GSM3230414", "normal E18 fMaSC sample1"),
        "fMaSC2": ("GSM3230415", "normal E18 fMaSC sample2"),
        "LP1": ("GSM3230418", "normal adult luminal progenitor cells sample1"),
        "LP2": ("GSM3230419", "normal adult luminal progenitor cells sample2"),
        "ML1": ("GSM3230420", "normal adult mature luminal cells sample1"),
        "ML2": ("GSM3230421", "normal adult mature luminal cells sample2"),
    }
    sample_rows = []
    for sample_id in expression.columns[1:]:
        geo_sample_id, title = sample_details[str(sample_id)]
        sample_rows.append({
            "sample_id": sample_id,
            "disease_state": "healthy",
            "label": "normal",
            "geo_sample_id": geo_sample_id,
            "geo_title": title,
            "geo_source_name": "WT mammary gland",
            "tissue": "Mammary gland",
            "species": "Mouse",
        })
    metadata_path = output_dir / f"{accession}_metadata.tsv"
    pd.DataFrame(sample_rows).to_csv(metadata_path, sep="\t", index=False)
    return expression_path, metadata_path


def download_geo_healthy_breast_counts(output_dir: Path) -> tuple[Path, Path]:
    accession = "GSE205725"
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE205nnn/GSE205725/"
    archive_path = output_dir / "GSE205725_RAW.tar"
    archive_path.write_bytes(fetch_with_retry(prefix + "suppl/GSE205725_RAW.tar", timeout=600).content)

    matrix_path = output_dir / "GSE205725_series_matrix.txt.gz"
    matrix_path.write_bytes(fetch_with_retry(prefix + "matrix/GSE205725_series_matrix.txt.gz").content)
    filelist_path = output_dir / "GSE205725_filelist.txt"
    filelist_path.write_bytes(fetch_with_retry(prefix + "suppl/filelist.txt").content)

    import csv

    sample_fields: dict[str, list[str]] = {}
    characteristic_fields: list[list[str]] = []
    with gzip.open(matrix_path, "rt", encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if row and row[0].startswith("!Sample_"):
                if row[0] == "!Sample_characteristics_ch1":
                    characteristic_fields.append(row[1:])
                else:
                    sample_fields[row[0]] = row[1:]
    sample_ids = sample_fields.get("!Sample_geo_accession", [])
    if not sample_ids:
        raise RuntimeError("GSE205725 GEO metadata did not contain sample accessions")

    raw_samples_dir = output_dir / "individual_counts"
    raw_samples_dir.mkdir(parents=True, exist_ok=True)
    expression_columns: dict[str, pd.Series] = {}
    with tarfile.open(archive_path, mode="r:") as archive:
        members = [
            member for member in archive.getmembers()
            if member.isfile() and re.fullmatch(r"GSM\d+[^/]*\.ftcounts\.txt\.gz", Path(member.name).name)
        ]
        for member in members:
            sample_id = re.match(r"(GSM\d+)", Path(member.name).name).group(1)
            source = archive.extractfile(member)
            if source is None:
                continue
            compressed = source.read()
            (raw_samples_dir / Path(member.name).name).write_bytes(compressed)
            frame = pd.read_csv(io.BytesIO(gzip.decompress(compressed)), sep="\t", comment="#")
            if frame.empty:
                continue
            gene_column = next((column for column in frame.columns if str(column).casefold() in {"geneid", "gene_id"}), frame.columns[0])
            count_column = frame.columns[-1]
            counts = pd.DataFrame({
                "gene_id": frame[gene_column].astype(str),
                "count": pd.to_numeric(frame[count_column], errors="coerce").fillna(0),
            })
            expression_columns[sample_id] = counts.groupby("gene_id", sort=False)["count"].sum()

    if not expression_columns:
        raise RuntimeError("GSE205725 archive contained no usable feature-count sample files")

    expression = pd.DataFrame(expression_columns).fillna(0)
    expression.index.name = "gene_id"
    expression_path = output_dir / f"{accession}_expression.tsv.gz"
    expression.to_csv(expression_path, sep="\t", compression="gzip")

    metadata_rows = []
    for index, sample_id in enumerate(sample_ids):
        if sample_id not in expression.columns:
            continue
        def field_value(name: str) -> str:
            values = sample_fields.get(name, [])
            return values[index] if index < len(values) else ""

        metadata_rows.append({
            "sample_id": sample_id,
            "disease_state": "healthy",
            "label": "normal",
            "geo_sample_id": sample_id,
            "geo_title": field_value("!Sample_title"),
            "geo_source_name": field_value("!Sample_source_name_ch1"),
            "geo_characteristics": " | ".join(
                values[index] for values in characteristic_fields
                if index < len(values) and values[index]
            ),
            "tissue": "Normal breast tissue",
            "species": "Human",
        })
    metadata_path = output_dir / f"{accession}_metadata.tsv"
    pd.DataFrame(metadata_rows).to_csv(metadata_path, sep="\t", index=False)
    return expression_path, metadata_path


def write_manifest(entries: list[dict]) -> Path:
    existing = {}
    if MANIFEST_PATH.exists():
        try:
            existing = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing_by_accession = {entry.get("accession"): entry for entry in existing.get("datasets", [])}
    updated_accessions = {entry.get("accession") for entry in entries}
    merged = []
    for entry in entries:
        previous = existing_by_accession.get(entry.get("accession"), {})
        merged.append({**previous, **entry})
    merged.extend(
        entry for entry in existing.get("datasets", [])
        if entry.get("accession") not in updated_accessions
    )
    manifest = {
        "datasets": merged,
        "created_at": existing.get("created_at") or datetime.now(timezone.utc).isoformat(),
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return MANIFEST_PATH


def main() -> None:
    # 1) live TCGA-BRCA subset
    tcga_dir = RAW_ROOT / "gdc"
    expr_tcga, meta_tcga = download_tcga_brca_subset(tcga_dir, limit_per_group=6, max_workers=4)

    # 2) live mouse mammary cancer series
    geo_dir = RAW_ROOT / "geo"
    expr_geo, meta_geo = download_geo_series("GSE155577", geo_dir)

    # 3) pipeline sanity check with the actual files
    tcga_df = pd.read_csv(expr_tcga, sep="\t", compression="gzip")
    geo_df = pd.read_csv(expr_geo, sep="\t", compression="gzip")
    pipeline = PreprocessingPipeline(normalization_method="log2cpm", low_expr_threshold=1.0, low_expr_min_samples=3)
    tcga_meta = pd.read_csv(meta_tcga, sep="\t")
    geo_meta = pd.read_csv(meta_geo, sep="\t")
    tcga_matrix, excluded_human_ids = enforce_ensembl_gene_ids(tcga_df.set_index("gene_id"), "human")
    geo_matrix, excluded_mouse_ids = enforce_ensembl_gene_ids(geo_df.set_index("gene_id"), "mouse")
    tcga_clean, tcga_log = pipeline.run(tcga_matrix, tcga_meta, "TCGA-BRCA-real", "Human")
    geo_clean, geo_log = PreprocessingPipeline(normalization_method="none", low_expr_threshold=0.0, low_expr_min_samples=1).run(
        geo_matrix, geo_meta, "GSE155577-real", "Mouse"
    )

    tcga_processed = PROCESSED_ROOT / "gdc" / "tcga_brca_real_preprocessed.parquet"
    geo_processed = PROCESSED_ROOT / "geo" / "gse155577_real_preprocessed.parquet"
    tcga_processed.parent.mkdir(parents=True, exist_ok=True)
    geo_processed.parent.mkdir(parents=True, exist_ok=True)
    tcga_clean.to_parquet(tcga_processed)
    geo_clean.to_parquet(geo_processed)

    manifest_entries = [
        {
            "id": "tcga-brca-live",
            "dataset_id": "tcga-brca-live",
            "name": "TCGA-BRCA live subset",
            "repository": "GDC / TCGA",
            "accession": "TCGA-BRCA",
            "platform": "Illumina sequencing; GDC STAR - Counts workflow",
            "source_data_type": "RNA-Seq unstranded gene counts",
            "genome_build": "GRCh38 (GDC STAR - Counts; GENCODE v36 gene model)",
            "download_date": datetime.now(timezone.utc).date().isoformat(),
            "species": "Human",
            "tissue": "Breast",
            "condition": "Disease",
            "disease": "Breast Cancer",
            "data_type": "normalized",
            "sample_count": int(tcga_clean.shape[1]),
            "n_samples": int(tcga_clean.shape[1]),
            "n_healthy": int((tcga_meta["disease_state"] == "healthy").sum()),
            "n_cancer": int((tcga_meta["disease_state"] == "cancer").sum()),
            "raw_sample_count": int(len(tcga_meta)),
            "gene_count": int(tcga_clean.shape[0]),
            "n_genes": int(tcga_clean.shape[0]),
            "normalization_method": "log2cpm",
            "raw_expression_path": str(expr_tcga),
            "metadata_path": str(meta_tcga),
            "processed_expression_path": str(tcga_processed),
            "preprocessing_log": tcga_log.to_text(),
            "status": "ready",
            "is_validated": True,
            "suitability_score": 90,
            "source_url": "https://portal.gdc.cancer.gov/projects/TCGA-BRCA",
            "excluded_unmapped_gene_ids": excluded_human_ids,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "id": "gse155577-live",
            "dataset_id": "gse155577-live",
            "name": "GEO GSE155577 live subset",
            "repository": "GEO",
            "accession": "GSE155577",
            "platform": "Illumina HiSeq 1000",
            "source_data_type": "Study-normalized RNA-Seq expression values",
            "genome_build": "Not reported in GEO series/sample metadata",
            "download_date": datetime.now(timezone.utc).date().isoformat(),
            "species": "Mouse",
            "tissue": "Mammary tumor",
            "condition": "Cancer",
            "disease": "Breast Cancer",
            "data_type": "normalized",
            "sample_count": int(geo_clean.shape[1]),
            "n_samples": int(geo_clean.shape[1]),
            "n_healthy": int((geo_meta["disease_state"] == "healthy").sum()),
            "n_cancer": int((geo_meta["disease_state"] == "cancer").sum()),
            "gene_count": int(geo_clean.shape[0]),
            "n_genes": int(geo_clean.shape[0]),
            "normalization_method": "none",
            "raw_expression_path": str(expr_geo),
            "metadata_path": str(meta_geo),
            "processed_expression_path": str(geo_processed),
            "preprocessing_log": geo_log.to_text(),
            "status": "ready",
            "is_validated": True,
            "suitability_score": 88,
            "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE155577",
            "identifier_fields": ["sample_id", "geo_sample_id", "biosample_accession", "sra_accession"],
            "sample_origins": {
                "in_vivo_mammary_tumor_cells": int((~geo_meta["geo_title"].str.contains("cell line", case=False, na=False)).sum()),
                "cultured_tumor_cell_line": int(geo_meta["geo_title"].str.contains("cell line", case=False, na=False).sum()),
            },
            "excluded_unmapped_gene_ids": excluded_mouse_ids,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    ]

    write_manifest(manifest_entries)
    from app.services.data_acquisition.dataset_registry import write_dataset_registry
    write_dataset_registry()
    print("TCGA-BRCA live tumor + normal subset saved:", expr_tcga, meta_tcga)
    print("GEO GSE155577 live subset saved:", expr_geo, meta_geo)
    print("TCGA cleaned shape:", tcga_clean.shape)
    print("GEO cleaned shape:", geo_clean.shape)
    print("Manifest written:", MANIFEST_PATH)


if __name__ == "__main__":
    main()
