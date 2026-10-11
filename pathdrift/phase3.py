from __future__ import annotations

import json
import hashlib
import logging
import subprocess
from functools import lru_cache
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func, select

from .acquisition.registry import ROOT, json_safe, open_session, set_run_state
from .differential_expression.service import analyze_comparison, write_deg_comparison
from .differential_expression.cross_study import prepare_mouse_cross_study_expression
from .differential_expression.validation import ExpressionValidationError, normalize_ensembl_id
from .modules.detection import detect_modules
from .networks.construction import construct_network
from .networks.plots import write_network_figures, write_top_centrality_subnetwork
from .phase3_repository import (
    delete_phase3_results,
    persist_de_results,
    persist_network_result,
)
from .pipeline import load_config

logger = logging.getLogger("pathdrift.phase3")
CONDITION_ALIASES = {
    "healthy": {"healthy", "normal", "control", "solid tissue normal"},
    "cancer": {"cancer", "tumor", "tumour", "carcinoma", "disease"},
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(value), indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _read_dataset(dataset, *, run_id: str) -> dict[str, Any]:
    provenance = dataset.provenance or {}
    expression_path = Path(
        provenance.get("processed_expression_path") or dataset.expression_file_path or ""
    )
    metadata_path = Path(provenance.get("metadata_path") or dataset.metadata_file_path or "")
    raw_expression_path = Path(provenance.get("raw_expression_path") or "")
    artifact_resolution = "registered_provenance"
    if not expression_path.is_file():
        processed_root = ROOT / "data" / "processed"
        filename = f"{dataset.accession.replace('/', '_')}_normalized.parquet"
        candidates = [
            project_dir / run_id / filename
            for project_dir in processed_root.iterdir()
            if project_dir.is_dir() and (project_dir / run_id / filename).is_file()
        ] if processed_root.is_dir() else []
        if len(candidates) > 1:
            raise ExpressionValidationError(
                f"Multiple run-scoped Phase 2 matrices were found for {dataset.accession}; "
                "the run provenance is ambiguous."
            )
        if candidates:
            expression_path = candidates[0]
            artifact_resolution = "recovered_by_unique_run_id"
    if not expression_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError(
            f"Phase 2 expression or metadata artifact is missing for {dataset.accession}: "
            f"{expression_path}, {metadata_path}"
        )
    if expression_path.suffix == ".parquet":
        expression = pd.read_parquet(expression_path)
    elif expression_path.name.endswith((".tsv", ".tsv.gz")):
        expression = pd.read_csv(
            expression_path,
            sep="\t",
            index_col=0,
            compression="infer",
        )
    else:
        raise ValueError(
            f"Unsupported Phase 2 expression matrix format for {dataset.accession}: "
            f"{expression_path.suffix}"
        )
    if "gene_id" in expression.columns:
        expression = expression.set_index("gene_id")
    expression.index = expression.index.astype(str)
    expression.columns = expression.columns.astype(str)
    if dataset.n_genes is not None and len(expression.index) != dataset.n_genes:
        raise ExpressionValidationError(
            f"Recovered Phase 2 matrix gene count differs from the registered dataset for {dataset.accession}."
        )
    if dataset.n_samples is not None and len(expression.columns) != dataset.n_samples:
        raise ExpressionValidationError(
            f"Recovered Phase 2 matrix sample count differs from the registered dataset for {dataset.accession}."
        )
    metadata = pd.read_csv(metadata_path, sep="\t")
    if "sample_id" not in metadata or "disease_state" not in metadata:
        raise ExpressionValidationError(
            f"Phase 2 metadata for {dataset.accession} lacks sample_id or disease_state."
        )
    metadata["sample_id"] = metadata["sample_id"].astype(str).str.strip()
    missing = set(expression.columns) - set(metadata["sample_id"])
    if missing:
        raise ExpressionValidationError(
            f"Phase 2 metadata for {dataset.accession} is missing {len(missing)} QC-retained samples."
        )
    # The normalized matrix is already restricted to Phase 2 QC-retained samples.
    metadata = metadata[metadata["sample_id"].isin(expression.columns)].copy()
    if dataset.species.value not in {"human", "mouse"}:
        raise ExpressionValidationError(f"Unsupported dataset species for {dataset.accession}.")
    return {
        "dataset": dataset,
        "expression": expression,
        "metadata": metadata,
        "raw_expression_path": raw_expression_path,
        "expression_path": expression_path,
        "metadata_path": metadata_path,
        "artifact_resolution": artifact_resolution,
    }


def _condition_mask(values: pd.Series, condition: str) -> pd.Series:
    key = condition.casefold()
    aliases = CONDITION_ALIASES.get(key, {key})
    return values.astype(str).str.strip().str.casefold().isin(aliases)


def _load_raw_counts(path: Path, samples: list[str], genes: pd.Index) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Raw count input required by the configured DEG method is missing: {path}")
    counts = pd.read_csv(path, sep="\t", index_col=0, compression="infer")
    counts.index = counts.index.map(normalize_ensembl_id)
    counts.columns = counts.columns.astype(str)
    if counts.index.has_duplicates:
        raise ExpressionValidationError("Raw count matrix contains duplicate gene IDs after Ensembl version normalization.")
    missing = set(samples) - set(counts.columns)
    if missing:
        raise ExpressionValidationError(f"Raw count matrix is missing {len(missing)} selected samples.")
    return counts.loc[genes, samples]


def _save_figure_records(session, *, run_id: str, dataset_id: str | None, network_id: str | None, stage: str, figures: list[dict], metadata: dict) -> None:
    from app.models import RunFigure

    session.add_all([
        RunFigure(
            run_id=run_id,
            dataset_id=dataset_id,
            network_id=network_id,
            stage=stage,
            figure_type=figure["figure_type"],
            file_path=str(Path(figure["path"]).resolve()),
            format=figure["format"],
            metadata_json=json_safe(metadata),
        )
        for figure in figures
    ])
    session.flush()


@lru_cache(maxsize=2)
def _mouse_gene_symbols(mapping_path: str) -> dict[str, str]:
    mapping = pd.read_csv(mapping_path, sep="\t", dtype=str)
    required = {"mouse_ensembl_id", "mouse_symbol", "orthology_type"}
    if not required.issubset(mapping.columns):
        raise ValueError("Mouse orthology mapping lacks Ensembl IDs, symbols, or relationship types.")
    mapping = mapping.loc[
        mapping["orthology_type"].astype(str).str.casefold().eq("ortholog_one2one")
    ].dropna(subset=["mouse_ensembl_id", "mouse_symbol"])
    mapping["mouse_ensembl_id"] = mapping["mouse_ensembl_id"].astype(str).str.strip()
    mapping["mouse_symbol"] = mapping["mouse_symbol"].astype(str).str.strip()
    mapping = mapping.loc[
        mapping["mouse_ensembl_id"].ne("")
        & mapping["mouse_symbol"].ne("")
        & ~mapping["mouse_ensembl_id"].duplicated(keep=False)
    ]
    return dict(zip(mapping["mouse_ensembl_id"], mapping["mouse_symbol"]))


def _attach_gene_symbols(session, nodes: pd.DataFrame, species: str) -> None:
    from app.models import Gene, SpeciesEnum

    ids = nodes["gene_id"].astype(str).tolist()
    genes_by_id: dict[str, Gene] = {}
    for offset in range(0, len(ids), 1000):
        batch = ids[offset:offset + 1000]
        genes_by_id.update({
            gene.ensembl_id: gene
            for gene in session.execute(
                select(Gene).where(
                    Gene.species == SpeciesEnum(species),
                    Gene.ensembl_id.in_(batch),
                )
            ).scalars()
        })
    fallback_symbols = (
        _mouse_gene_symbols(str(ROOT / "data" / "pathdrift" / "raw" / "orthology" / "ensembl_one_to_one.tsv"))
        if species == "mouse"
        else {}
    )
    symbols: dict[str, str | None] = {}
    for ensembl_id, gene in genes_by_id.items():
        if not gene.gene_symbol and ensembl_id in fallback_symbols:
            gene.gene_symbol = fallback_symbols[ensembl_id]
        symbols[ensembl_id] = gene.gene_symbol
    nodes["gene_symbol"] = nodes["gene_id"].astype(str).map(symbols)


def _recover_deg_outputs(
    session,
    *,
    run_id: str,
    phase3_root: Path,
    by_accession: dict[str, dict[str, Any]],
    de_config: dict,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict], list[dict]] | None:
    from app.models import RunDifferentialExpression, RunFigure

    results: dict[str, pd.DataFrame] = {}
    summaries: dict[str, dict] = {}
    figures: list[dict] = []
    for species in ("human", "mouse"):
        species_config = de_config.get(species, {})
        accession = str(species_config.get("dataset_accession", ""))
        item = by_accession.get(accession)
        summary_path = phase3_root / "deg" / species / "summary.json"
        if not summary_path.is_file():
            return None
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if summary.get("run_id") != run_id or summary.get("dataset_accession") != accession:
            return None
        if summary.get("status") == "unavailable":
            summaries[species] = summary
            continue
        if item is None or summary.get("dataset_id") != item["dataset"].id:
            return None
        csv_path = phase3_root / "deg" / species / "all_genes.csv"
        if not csv_path.is_file():
            return None
        frame = pd.read_csv(csv_path)
        expected = int(summary.get("total_genes_tested", -1))
        persisted = int(session.execute(
            select(func.count()).select_from(RunDifferentialExpression).where(
                RunDifferentialExpression.run_id == run_id,
                RunDifferentialExpression.dataset_id == item["dataset"].id,
                RunDifferentialExpression.comparison == str(summary.get("comparison", "")),
            )
        ).scalar_one())
        if expected < 1 or len(frame) != expected or persisted != expected:
            return None
        summary["status"] = "completed"
        results[species] = frame
        summaries[species] = summary
        figures.extend({
            "path": figure.file_path,
            "figure_type": figure.figure_type,
            "format": figure.format,
        } for figure in session.execute(
            select(RunFigure).where(
                RunFigure.run_id == run_id,
                RunFigure.dataset_id == item["dataset"].id,
                RunFigure.stage == "deg",
            )
        ).scalars())
    return results, summaries, figures


def _read_git_revision() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _git_worktree_dirty() -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(completed.stdout.strip())


def _software_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package in ("pathdrift", "pandas", "numpy", "scipy", "statsmodels", "pydeseq2", "networkx", "matplotlib"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return versions


def _network_sample_ids(
    item: dict[str, Any],
    state: str,
    *,
    excluded_samples: set[str],
    excluded_case_ids: set[str],
    case_id_column: str | None,
) -> list[str]:
    metadata = item["metadata"].set_index("sample_id", drop=False)
    state_mask = _condition_mask(metadata["disease_state"], state)
    keep = state_mask & ~metadata.index.isin(excluded_samples)
    if excluded_case_ids:
        if not case_id_column or case_id_column not in metadata:
            raise ExpressionValidationError(
                f"Cannot apply configured patient exclusions: metadata lacks {case_id_column!r}."
            )
        keep &= ~metadata[case_id_column].astype(str).isin(excluded_case_ids)
    return [sample_id for sample_id in metadata.index[keep] if sample_id in item["expression"].columns]


def _persist_deg_and_export(
    session,
    *,
    run_id: str,
    item: dict[str, Any],
    species: str,
    comparison: str,
    results: pd.DataFrame,
    summary: dict,
    output_dir: Path,
    alpha: float,
    lfc_threshold: float,
) -> list[dict]:
    summary.update({
        "run_id": run_id,
        "dataset_id": item["dataset"].id,
        "dataset_accession": item["dataset"].accession,
        "input_expression_path": str(item["expression_path"].resolve()),
        "input_metadata_path": str(item["metadata_path"].resolve()),
    })
    figures = write_deg_comparison(
        results,
        summary,
        output_dir,
        accession=item["dataset"].accession,
        alpha=alpha,
        lfc_threshold=lfc_threshold,
    )
    persist_de_results(
        session,
        run_id=run_id,
        dataset_id=item["dataset"].id,
        species=species,
        comparison=comparison,
        results=results,
        summary=summary,
    )
    _save_figure_records(
        session,
        run_id=run_id,
        dataset_id=item["dataset"].id,
        network_id=None,
        stage="deg",
        figures=figures,
        metadata={"comparison": comparison, "species": species},
    )
    session.commit()
    return figures


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_file(root: Path, relative_path: str) -> Path:
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Acquisition manifest path escapes the repository: {relative_path!r}.")
    if not path.is_file():
        raise FileNotFoundError(f"Manifest source file is missing: {path}")
    return path


def run_mouse_cross_study_deg(run_id: str, *, force: bool = False) -> dict[str, Any]:
    from app.models import (
        AnalysisRun,
        AnalysisRunDataset,
        Dataset,
        Gene,
        SpeciesEnum,
    )

    session = open_session()
    try:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"Phase 2 run {run_id!r} does not exist.")
        run_dir = Path(run.run_dir or "")
        manifest_path = Path(run.manifest_path or "")
        if not run_dir.is_dir() or not manifest_path.is_file():
            raise FileNotFoundError("Completed Phase 2 run directory or manifest is missing.")
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if run_manifest.get("status") != "COMPLETED":
            raise ValueError("Exploratory mouse DEG requires a completed Phase 2 run manifest.")

        output_dir = run_dir / "deg" / "mouse" / "cross_study_exploratory"
        summary_path = output_dir / "summary.json"
        if summary_path.is_file() and not force:
            cached = json.loads(summary_path.read_text(encoding="utf-8"))
            if cached.get("status") == "COMPLETED":
                return cached

        links = session.execute(
            select(AnalysisRunDataset, Dataset)
            .join(Dataset, Dataset.id == AnalysisRunDataset.dataset_id)
            .where(
                AnalysisRunDataset.run_id == run_id,
                Dataset.accession == "GSE155577",
            )
        ).all()
        if len(links) != 1:
            raise ValueError("The Phase 2 run must contain exactly one registered GSE155577 tumor cohort.")
        _, tumor_dataset = links[0]
        tumor_item = _read_dataset(tumor_dataset, run_id=run_id)

        acquisition_manifest_path = ROOT / "data" / "pathdrift" / "manifests" / "dataset_manifest.json"
        acquisition_manifest = json.loads(acquisition_manifest_path.read_text(encoding="utf-8"))
        acquired = {
            entry["accession"]: entry
            for entry in acquisition_manifest.get("datasets", [])
        }
        tumor_source = acquired.get("GSE155577")
        healthy_source = acquired.get("GSE116385")
        if tumor_source is None or healthy_source is None:
            raise ValueError("The acquisition manifest must include both GSE155577 and GSE116385.")
        if healthy_source.get("species", "").casefold() != "mouse":
            raise ValueError("The acquired GSE116385 reference is not labelled as mouse.")

        healthy_expression_path = _manifest_file(ROOT, healthy_source["raw_expression_path"])
        healthy_metadata_path = _manifest_file(ROOT, healthy_source["metadata_path"])
        mapping_path = _manifest_file(ROOT, "data/pathdrift/raw/orthology/ensembl_one_to_one.tsv")
        checksums = {
            "GSE155577": {
                "raw_expression": _file_sha256(_manifest_file(ROOT, tumor_source["raw_expression_path"])),
                "metadata": _file_sha256(_manifest_file(ROOT, tumor_source["metadata_path"])),
            },
            "GSE116385": {
                "raw_expression": _file_sha256(healthy_expression_path),
                "metadata": _file_sha256(healthy_metadata_path),
            },
            "mouse_one_to_one_mapping": _file_sha256(mapping_path),
        }
        expected_checksums = {
            "GSE155577": {
                "raw_expression": tumor_source.get("expression_sha256"),
                "metadata": tumor_source.get("metadata_sha256"),
            },
            "GSE116385": {
                "raw_expression": healthy_source.get("file_checksums_sha256", {}).get("raw_expression"),
                "metadata": healthy_source.get("file_checksums_sha256", {}).get("metadata"),
            },
        }
        for accession, file_checksums in expected_checksums.items():
            for artifact, expected in file_checksums.items():
                observed = checksums[accession][artifact]
                if expected and observed.casefold() != str(expected).casefold():
                    raise ValueError(
                        f"{accession} {artifact} checksum does not match the acquisition manifest."
                    )

        healthy_expression = pd.read_csv(
            healthy_expression_path,
            sep="\t",
            compression="infer",
            index_col=0,
        )
        healthy_metadata = pd.read_csv(healthy_metadata_path, sep="\t")
        mapping = pd.read_csv(mapping_path, sep="\t", dtype=str)
        expression, sample_metadata, gene_table, input_info = prepare_mouse_cross_study_expression(
            tumor_item["expression"],
            tumor_item["metadata"],
            healthy_expression,
            healthy_metadata,
            mapping,
        )
        fallback = load_config("configs/breast_cancer.yaml")
        de_config = (run.config or {}).get(
            "differential_expression",
            fallback.get("differential_expression", {}),
        )
        statistics_config = de_config.get("statistics", {})
        alpha = float(statistics_config.get("alpha", 0.05))
        lfc_threshold = float(statistics_config.get("lfc_threshold", 1.0))
        results, summary, _ = analyze_comparison(
            expression,
            sample_metadata,
            raw_counts=None,
            species="mouse",
            sample_id_column="sample_id",
            condition_column="disease_state",
            case_condition="cancer",
            control_condition="healthy",
            minimum_samples_per_group=int(de_config.get("min_samples_per_group", 3)),
            alpha=alpha,
            lfc_threshold=lfc_threshold,
            data_type="normalized",
            method="continuous",
            min_count=int(de_config.get("filtering", {}).get("min_count", 10)),
            min_samples_fraction=float(de_config.get("filtering", {}).get("min_samples_fraction", 0.2)),
            expression_scale="log2",
        )
        comparison = "cancer_vs_healthy_cross_study_exploratory"
        symbols = gene_table.set_index("gene_id")["gene_symbol"]
        results["gene_symbol"] = results["gene_id"].map(symbols)
        summary.update({
            "status": "COMPLETED",
            "classification": "exploratory_cross_study_not_confirmatory",
            "comparison": comparison,
            "biological_contrast": "GSE155577 in-vivo E-A14 tumor-derived cells vs GSE116385 normal mammary cell populations",
            "run_id": run_id,
            "dataset_id": tumor_dataset.id,
            "case_dataset_accession": "GSE155577",
            "control_dataset_accession": "GSE116385",
            "case_samples": input_info["tumor_biological_replicates"],
            "control_samples": input_info["healthy_samples"],
            "input_info": input_info,
            "source_paths": {
                "tumor_phase2_expression": str(tumor_item["expression_path"].resolve()),
                "tumor_metadata": str(tumor_item["metadata_path"].resolve()),
                "healthy_expression": str(healthy_expression_path.resolve()),
                "healthy_metadata": str(healthy_metadata_path.resolve()),
                "mouse_one_to_one_mapping": str(mapping_path.resolve()),
                "phase2_run_manifest": str(manifest_path.resolve()),
                "acquisition_manifest": str(acquisition_manifest_path.resolve()),
            },
            "source_sha256": checksums,
            "study_design_warning": (
                "Cancer status is perfectly confounded with GEO study, assay/platform, and processing. "
                "The healthy samples are a separate RPKM cohort, so study and condition effects cannot "
                "be distinguished by this design. P-values and fold changes are exploratory only and "
                "must not be treated as confirmatory cancer-vs-normal findings."
            ),
            "biological_limitations": [
                "GSE155577 tumor samples are sorted E-A14 tumor-cell fractions; GSE116385 controls are four distinct normal mammary cell populations, including fetal and adult populations.",
                "The tumor and normal cohorts use separate GEO studies and expression quantification pipelines; no batch correction can identify condition separately from study in this design.",
                "Tumor samples were averaged within each matched EpCAM-positive/EpCAM-negative fraction pair to avoid treating two samples from one tumor specimen as independent biological replicates.",
                "Only exact, unique gene-symbol matches to the local Ensembl release 116 one-to-one orthology mapping and present tumor Ensembl IDs were tested; unmapped and ambiguous symbols were excluded.",
                "The mouse cohort has no same-study healthy control samples; this analysis does not replace a matched, confirmatory mouse DEG study.",
            ],
        })
        output_dir.mkdir(parents=True, exist_ok=True)
        sample_metadata.to_csv(output_dir / "sample_metadata.csv", index=False)
        gene_table.to_csv(output_dir / "gene_mapping.csv", index=False)
        figures = write_deg_comparison(
            results,
            summary,
            output_dir,
            accession="GSE155577_vs_GSE116385_exploratory",
            alpha=alpha,
            lfc_threshold=lfc_threshold,
        )
        persist_de_results(
            session,
            run_id=run_id,
            dataset_id=tumor_dataset.id,
            species="mouse",
            comparison=comparison,
            results=results,
            summary=summary,
        )
        symbol_by_id = dict(zip(gene_table["gene_id"], gene_table["gene_symbol"]))
        gene_ids = list(symbol_by_id)
        for offset in range(0, len(gene_ids), 1000):
            records = session.execute(
                select(Gene).where(
                    Gene.species == SpeciesEnum.MOUSE,
                    Gene.ensembl_id.in_(gene_ids[offset:offset + 1000]),
                )
            ).scalars()
            for gene in records:
                if not gene.gene_symbol:
                    gene.gene_symbol = symbol_by_id[gene.ensembl_id]
        _save_figure_records(
            session,
            run_id=run_id,
            dataset_id=tumor_dataset.id,
            network_id=None,
            stage="deg",
            figures=figures,
            metadata={
                "comparison": comparison,
                "species": "mouse",
                "classification": summary["classification"],
            },
        )
        summary["persisted_gene_rows"] = len(results)
        summary["persisted_significant_gene_rows"] = int(results["significant"].sum())
        summary["figure_artifacts"] = [
            {
                "path": figure["path"],
                "figure_type": figure["figure_type"],
                "format": figure["format"],
            }
            for figure in figures
        ]
        session.commit()
        _write_json(summary_path, summary)

        existing_mouse_summary_path = run_dir / "deg" / "mouse" / "summary.json"
        if existing_mouse_summary_path.is_file():
            existing_mouse_summary = json.loads(existing_mouse_summary_path.read_text(encoding="utf-8"))
            existing_mouse_summary["exploratory_cross_study"] = {
                "status": "COMPLETED",
                "comparison": comparison,
                "summary_path": str(summary_path.resolve()),
                "warning": summary["study_design_warning"],
            }
            _write_json(existing_mouse_summary_path, existing_mouse_summary)

        phase3_record = manifest_value = json.loads(manifest_path.read_text(encoding="utf-8")).get("phase3", {})
        phase3_summary = dict(phase3_record.get("summary", {}))
        deg_summary = dict(phase3_summary.get("deg", {}))
        deg_summary["mouse_cross_study_exploratory"] = summary
        phase3_summary["deg"] = deg_summary
        stages = dict(phase3_record.get("stages", {}))
        stages["mouse_cross_study_exploratory_deg"] = {
            "status": "COMPLETED",
            "summary": summary,
        }
        manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
        phase3_record["summary"] = phase3_summary
        phase3_record["stages"] = stages
        phase3_record["status"] = "COMPLETED"
        manifest_value["phase3"] = phase3_record
        manifest_value["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(manifest_path, manifest_value)
        run.config = {
            **(run.config or {}),
            "phase3_summary": phase3_summary,
            "mouse_cross_study_exploratory_deg": summary,
        }
        session.commit()
        return summary
    except Exception:
        session.rollback()
        logger.exception("Exploratory mouse cross-study DEG failed for run %s", run_id)
        raise
    finally:
        session.close()


def run_phase3(
    run_id: str,
    *,
    force: bool = False,
    stage: str = "phase3",
    max_network_genes: int | None = None,
) -> dict[str, Any]:
    from app.models import AnalysisRun, AnalysisRunDataset, Dataset

    if stage not in {"deg", "networks", "modules", "phase3"}:
        raise ValueError(f"Unknown Phase 3 stage: {stage!r}")
    session = open_session()
    run = None
    try:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"Phase 2 run {run_id!r} does not exist.")
        run_dir = Path(run.run_dir or "")
        manifest_path = Path(run.manifest_path or "")
        if not run_dir.is_dir() or not manifest_path.is_file():
            raise FileNotFoundError("Completed Phase 2 run directory or manifest is missing.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        phase3_interrupted_statuses = {
            "FAILED",
            "RUNNING",
            "DIFFERENTIAL_EXPRESSION",
            "NETWORK_CONSTRUCTION",
            "MODULE_DETECTION",
        }
        phase2_completed = manifest.get("status") == "COMPLETED"
        if run.status != "COMPLETED" and not (
            phase2_completed and run.status in phase3_interrupted_statuses
        ):
            raise ValueError(f"Phase 3 requires a completed Phase 2 run; current status is {run.status!r}.")
        phase3_root = run_dir
        prior = manifest.get("phase3", {})
        if prior.get("status") == "COMPLETED" and not force:
            return prior["summary"]
        stage_record = prior.get("stages", {}).get(stage)
        if stage_record and stage_record.get("status") == "COMPLETED" and not force:
            return stage_record["summary"]
        if stage == "phase3" and not force:
            completed_modules = prior.get("stages", {}).get("modules", {})
            if completed_modules.get("status") == "COMPLETED":
                summary = {
                    **completed_modules["summary"],
                    "status": "COMPLETED",
                    "target_stage": "phase3",
                }
                stage_summaries = dict(prior.get("stages", {}))
                stage_summaries["phase3"] = {"status": "COMPLETED", "summary": summary}
                manifest["phase3"] = {
                    "status": "COMPLETED",
                    "summary": summary,
                    "stages": stage_summaries,
                }
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_json(manifest_path, manifest)
                run.config = {**(run.config or {}), "phase3_summary": summary}
                run.status = "COMPLETED"
                run.stage = "COMPLETED"
                run.error_message = None
                session.commit()
                return summary

        config = run.config or {}
        phase3_sections = ("differential_expression", "networks", "modules")
        fallback_config = load_config("configs/breast_cancer.yaml")
        effective_sections = {
            section: config.get(section, fallback_config.get(section, {}))
            for section in phase3_sections
        }
        phase3_config_source = (
            "analysis_run_snapshot"
            if all(section in config for section in phase3_sections)
            else "configs/breast_cancer.yaml (Phase 3 settings absent from the Phase 2 run snapshot)"
        )
        de_config = effective_sections["differential_expression"]
        network_config = effective_sections["networks"]
        if max_network_genes is not None:
            if max_network_genes < 2:
                raise ValueError("The network gene cap must be at least 2.")
            effective_sections["networks"] = {
                **network_config,
                "max_genes": max_network_genes,
            }
            network_config = effective_sections["networks"]
            phase3_config_source += " + --max-network-genes override"
        module_config = effective_sections["modules"]
        if not de_config.get("enabled") and not network_config.get("enabled"):
            raise ValueError("Phase 3 has no enabled analysis stages in the run configuration.")
        links = session.execute(
            select(AnalysisRunDataset, Dataset)
            .join(Dataset, Dataset.id == AnalysisRunDataset.dataset_id)
            .where(AnalysisRunDataset.run_id == run_id)
        ).all()
        by_accession = {
            dataset.accession: _read_dataset(
                dataset,
                run_id=run_id,
            )
            for _, dataset in links
        }
        if not by_accession:
            raise ValueError("The completed Phase 2 run has no registered datasets.")
        if force:
            delete_phase3_results(session, run_id, stage=stage)
            session.commit()

        (phase3_root / "deg").mkdir(parents=True, exist_ok=True)
        (phase3_root / "networks").mkdir(parents=True, exist_ok=True)
        (phase3_root / "modules").mkdir(parents=True, exist_ok=True)
        (phase3_root / "integrated").mkdir(parents=True, exist_ok=True)
        warnings: list[str] = [
            (
                f"Resolved {item['dataset'].accession} QC-normalized matrix by unique Phase 2 run ID "
                "because the registered processed path no longer exists."
            )
            for item in by_accession.values()
            if item["artifact_resolution"] != "registered_provenance"
        ]
        run_de = de_config.get("enabled") and stage != "networks"
        run_networks = network_config.get("enabled") and stage != "deg"
        run_modules = module_config.get("enabled") and stage in {"modules", "phase3"}
        deg_results: dict[str, pd.DataFrame] = {}
        deg_summaries: dict[str, dict] = {}
        figure_records: list[dict] = []

        set_run_state(session, run, "RUNNING")
        if run_de:
            set_run_state(session, run, "DIFFERENTIAL_EXPRESSION")
            cached_stage = next((
                prior.get("stages", {}).get(candidate)
                for candidate in ("deg", "modules", "phase3")
                if prior.get("stages", {}).get(candidate, {}).get("status") == "COMPLETED"
            ), None) if not force else None
            cached_de_summary = (cached_stage or {}).get("summary", {}).get("deg", {})
            recovered = None
            if not cached_stage and not force:
                recovered = _recover_deg_outputs(
                    session,
                    run_id=run_id,
                    phase3_root=phase3_root,
                    by_accession=by_accession,
                    de_config=de_config,
                )
            if cached_stage:
                figure_records.extend(
                    figure for figure in cached_stage["summary"].get("figures", [])
                    if figure.get("figure_type") in {"volcano", "ma_plot"}
                )
            elif recovered:
                deg_results.update(recovered[0])
                deg_summaries.update(recovered[1])
                figure_records.extend(recovered[2])
            for species in ("human", "mouse"):
                if cached_stage or recovered:
                    cached_result = cached_de_summary.get(species)
                    if recovered:
                        cached_result = recovered[1].get(species)
                    if cached_result is not None:
                        deg_summaries[species] = cached_result
                        if cached_result.get("status") == "completed":
                            cached_path = phase3_root / "deg" / species / "all_genes.csv"
                            if not cached_path.is_file():
                                raise FileNotFoundError(
                                    f"Completed DEG stage is missing its full result table: {cached_path}"
                                )
                            deg_results[species] = pd.read_csv(cached_path)
                        continue
                spec = de_config.get(species, {})
                accession = str(spec.get("dataset_accession", ""))
                item = by_accession.get(accession)
                comparison = f"{spec.get('case_condition', 'cancer')}_vs_{spec.get('control_condition', 'healthy')}"
                output_dir = phase3_root / "deg" / species
                if item is None:
                    unavailable = {
                        "status": "unavailable",
                        "species": species,
                        "comparison": comparison,
                        "dataset_accession": accession,
                        "run_id": run_id,
                        "reason": "Configured comparison dataset is not registered in this Phase 2 run.",
                    }
                    _write_json(output_dir / "summary.json", unavailable)
                    warnings.append(unavailable["reason"] + f" ({accession})")
                    deg_summaries[species] = unavailable
                    continue
                if item["dataset"].species.value != species:
                    raise ExpressionValidationError(
                        f"Configured {species} DEG dataset {accession} is registered as "
                        f"{item['dataset'].species.value}."
                    )
                state_values = item["metadata"]["disease_state"]
                cases_present = int(_condition_mask(state_values, str(spec.get("case_condition", "cancer"))).sum())
                controls_present = int(_condition_mask(state_values, str(spec.get("control_condition", "healthy"))).sum())
                if cases_present == 0 or controls_present == 0:
                    unavailable = {
                        "status": "unavailable",
                        "species": species,
                        "comparison": comparison,
                        "dataset_id": item["dataset"].id,
                        "dataset_accession": accession,
                        "run_id": run_id,
                        "case_samples_available": cases_present,
                        "control_samples_available": controls_present,
                        "reason": (
                            "The configured Phase 2 dataset does not contain both comparison groups; "
                            "no other study was combined and no differential-expression output was generated."
                        ),
                    }
                    _write_json(output_dir / "summary.json", unavailable)
                    warnings.append(f"{species} DEG unavailable: {unavailable['reason']}")
                    deg_summaries[species] = unavailable
                    continue
                exclusions = set(map(str, spec.get("excluded_samples", [])))
                excluded_cases = set(map(str, spec.get("excluded_case_ids", [])))
                validated = None
                try:
                    raw_counts = None
                    data_type = item["dataset"].data_type.value
                    stats_config = de_config.get("statistics", {})
                    configured_method = str(stats_config.get("method", "auto")).casefold()
                    if data_type == "raw_counts" and configured_method != "continuous":
                        raw_counts = _load_raw_counts(
                            item["raw_expression_path"],
                            item["expression"].columns.tolist(),
                            item["expression"].index,
                        )
                    filter_config = de_config.get("filtering", {})
                    results, summary, validated = analyze_comparison(
                        item["expression"],
                        item["metadata"],
                        raw_counts=raw_counts,
                        species=species,
                        sample_id_column="sample_id",
                        condition_column="disease_state",
                        case_condition=str(spec["case_condition"]),
                        control_condition=str(spec["control_condition"]),
                        minimum_samples_per_group=int(spec.get("min_samples_per_group", 3)),
                        alpha=float(stats_config.get("alpha", 0.05)),
                        lfc_threshold=float(stats_config.get("lfc_threshold", 1.0)),
                        data_type=data_type,
                        method=str(stats_config.get("method", "auto")),
                        min_count=int(filter_config.get("min_count", 10)),
                        min_samples_fraction=float(filter_config.get("min_samples_fraction", 0.2)),
                        expression_scale=str(stats_config.get("continuous_expression_scale", "log2")),
                        excluded_samples=exclusions,
                        excluded_cases=excluded_cases,
                        case_id_column=spec.get("case_id_column"),
                        n_cpus=int(stats_config.get("n_cpus", 1)),
                    )
                except ExpressionValidationError as exc:
                    if cases_present == 0 or controls_present == 0:
                        raise
                    unavailable = {
                        "status": "unavailable",
                        "species": species,
                        "comparison": comparison,
                        "dataset_id": item["dataset"].id,
                        "dataset_accession": accession,
                        "run_id": run_id,
                        "reason": str(exc),
                    }
                    _write_json(output_dir / "summary.json", unavailable)
                    warnings.append(f"{species} DEG unavailable: {exc}")
                    deg_summaries[species] = unavailable
                    continue
                figures = _persist_deg_and_export(
                    session,
                    run_id=run_id,
                    item=item,
                    species=species,
                    comparison=comparison,
                    results=results,
                    summary=summary,
                    output_dir=output_dir,
                    alpha=float(summary["alpha"]),
                    lfc_threshold=float(summary["lfc_threshold"]),
                )
                figure_records.extend(figures)
                deg_results[species] = results
                deg_summaries[species] = {
                    **summary,
                    "status": "completed",
                    "comparison": comparison,
                    "dataset_id": item["dataset"].id,
                    "dataset_accession": accession,
                }
            stage_summaries = dict(prior.get("stages", {}))
            stage_summary = {
                "run_id": run_id,
                "status": "PARTIAL",
                "target_stage": "deg",
                "deg": deg_summaries,
                "figures": figure_records,
            }
            stage_summaries["deg"] = {"status": "COMPLETED", "summary": stage_summary}
            manifest["phase3"] = {
                "status": "PARTIAL",
                "summary": stage_summary,
                "stages": stage_summaries,
            }
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(manifest_path, manifest)
            run.config = {
                **(run.config or {}),
                **effective_sections,
                "phase3_config_source": phase3_config_source,
                "phase3_stages": stage_summaries,
            }
            session.commit()

        if run_networks:
            set_run_state(session, run, "NETWORK_CONSTRUCTION")
        network_summaries: list[dict] = []
        module_summaries: list[dict] = []
        module_tables: dict[str, list[pd.DataFrame]] = {
            species: [] for species in ("human", "mouse")
        }
        module_gene_tables: dict[str, list[pd.DataFrame]] = {
            species: [] for species in ("human", "mouse")
        }
        network_nodes_by_name: dict[str, pd.DataFrame] = {}
        for species in ("human", "mouse"):
            species_config = network_config.get("states", {}).get(species, [])
            if not run_networks:
                continue
            candidates = [
                item for item in by_accession.values()
                if item["dataset"].species.value == species
            ]
            for item in candidates:
                spec = de_config.get(species, {})
                sample_exclusions = set(map(str, spec.get("excluded_samples", [])))
                case_exclusions = set(map(str, spec.get("excluded_case_ids", [])))
                case_id_column = spec.get("case_id_column")
                if species == "mouse" and network_config.get("exclude_cell_line_samples", False):
                    sample_exclusions.update(map(str, spec.get("excluded_samples", [])))
                for state in species_config:
                    eligible_sample_ids = _network_sample_ids(
                        item,
                        str(state),
                        excluded_samples=set(),
                        excluded_case_ids=set(),
                        case_id_column=None,
                    )
                    sample_ids = _network_sample_ids(
                        item,
                        str(state),
                        excluded_samples=sample_exclusions,
                        excluded_case_ids=case_exclusions if species == "human" else set(),
                        case_id_column=case_id_column if species == "human" else None,
                    )
                    minimum_samples = int(network_config.get("minimum_samples", 3))
                    name = f"{species}_{str(state).casefold()}"
                    if len(sample_ids) < minimum_samples:
                        warning = f"Network {name} unavailable for {item['dataset'].accession}: {len(sample_ids)} samples (< {minimum_samples})."
                        warnings.append(warning)
                        continue
                    expression = item["expression"].loc[:, sample_ids]
                    network = construct_network(
                        expression,
                        species=species,
                        method=str(network_config.get("method", "spearman")),
                        min_abs_correlation=float(network_config.get("min_abs_correlation", 0.7)),
                        max_adjusted_p_value=float(network_config.get("max_adjusted_p_value", 0.05)),
                        min_gene_variance=float(network_config.get("min_gene_variance", 0.1)),
                        max_genes=int(network_config.get("max_genes", 5000)),
                        seed=int(config.get("random_seed", 42)),
                        centrality_sample_count=int(network_config.get("centrality_sample_count", 8)),
                    )
                    network["summary"].update({
                        "run_id": run_id,
                        "dataset_id": item["dataset"].id,
                        "dataset_accession": item["dataset"].accession,
                        "species": species,
                        "disease_state": str(state),
                        "sample_ids": sample_ids,
                        "sample_selection": {
                            "eligible_qc_retained_samples": len(eligible_sample_ids),
                            "samples_used": len(sample_ids),
                            "excluded_sample_ids": sorted(set(eligible_sample_ids) - set(sample_ids)),
                            "excluded_patient_ids": sorted(case_exclusions) if species == "human" else [],
                        },
                    })
                    deg_frame = deg_results.get(species)
                    module_result = None
                    if run_modules:
                        module_result = detect_modules(
                            network["graph"],
                            method=str(module_config.get("method", "louvain")),
                            resolution=float(module_config.get("resolution", 1.0)),
                            min_module_size=int(module_config.get("min_module_size", 10)),
                            seed=int(config.get("random_seed", 42)),
                            nodes=network["nodes"],
                            deg_results=deg_frame,
                        )
                    network_id = persist_network_result(
                        session,
                        run_id=run_id,
                        dataset_id=item["dataset"].id,
                        species=species,
                        state=str(state),
                        name=name,
                        method=str(network_config.get("method", "spearman")),
                        result=network,
                        module_result=module_result,
                    )
                    session.commit()
                    network_nodes = network["nodes"] if module_result is None else module_result["nodes"]
                    _attach_gene_symbols(session, network_nodes, species)
                    if module_result is not None:
                        module_result["genes"]["gene_symbol"] = module_result["genes"]["gene_id"].astype(str).map(
                            dict(zip(network_nodes["gene_id"].astype(str), network_nodes["gene_symbol"]))
                        )
                    network_dir = phase3_root / "networks"
                    network_dir.mkdir(parents=True, exist_ok=True)
                    network["edges"].to_csv(network_dir / f"{name}_edges.csv", index=False)
                    network_nodes.to_csv(network_dir / f"{name}_nodes.csv", index=False)
                    network_summaries.append({"network_id": network_id, **network["summary"]})
                    network_nodes_by_name[name] = (
                        network["nodes"] if module_result is None else module_result["nodes"]
                    )
                    figures = write_network_figures(
                        network_nodes,
                        network["summary"],
                        network_dir / name,
                        label=name,
                    )
                    figures.extend(write_top_centrality_subnetwork(
                        network["graph"],
                        network_nodes,
                        network_dir / name,
                        label=name,
                        seed=int(config.get("random_seed", 42)),
                    ))
                    _save_figure_records(
                        session,
                        run_id=run_id,
                        dataset_id=item["dataset"].id,
                        network_id=network_id,
                        stage="networks",
                        figures=figures,
                        metadata={"network_name": name, "species": species},
                    )
                    session.commit()
                    figure_records.extend(figures)
                    if module_result is not None:
                        module_dir = phase3_root / "modules" / species
                        module_dir.mkdir(parents=True, exist_ok=True)
                        modules = module_result["modules"].copy()
                        genes = module_result["genes"].copy()
                        modules.insert(0, "network_name", name)
                        genes.insert(0, "network_name", name)
                        module_tables[species].append(modules)
                        module_gene_tables[species].append(genes)
                        module_summary = {
                            "network_id": network_id,
                            "network_name": name,
                            "species": species,
                            **module_result["summary"],
                            "modules": modules.to_dict(orient="records"),
                        }
                        module_summaries.append(module_summary)

        if run_networks:
            network_summary_path = phase3_root / "networks" / "network_summary.csv"
            pd.DataFrame([{
                **{key: value for key, value in row.items() if key not in {
                    "degree_distribution", "filtering", "sample_ids", "sample_selection",
                }},
                "degree_distribution": json.dumps(row.get("degree_distribution", {}), sort_keys=True),
                "filtering": json.dumps(row.get("filtering", {}), sort_keys=True),
                "sample_ids": json.dumps(row.get("sample_ids", [])),
                "sample_selection": json.dumps(row.get("sample_selection", {}), sort_keys=True),
                "centrality": json.dumps(row.get("centrality", {}), sort_keys=True),
                "top_central_genes": json.dumps(row.get("top_central_genes", [])),
            } for row in network_summaries]).to_csv(network_summary_path, index=False)
        if run_modules:
            for species in ("human", "mouse"):
                module_dir = phase3_root / "modules" / species
                module_dir.mkdir(parents=True, exist_ok=True)
                modules = pd.concat(module_tables[species], ignore_index=True) if module_tables[species] else pd.DataFrame()
                genes = pd.concat(module_gene_tables[species], ignore_index=True) if module_gene_tables[species] else pd.DataFrame()
                modules.to_csv(module_dir / "modules.csv", index=False)
                genes.to_csv(module_dir / "module_genes.csv", index=False)
                modules.to_csv(module_dir / "module_statistics.csv", index=False)
            _write_json(phase3_root / "modules" / "module_summary.json", {
                "run_id": run_id,
                "module_network_count": len(module_summaries),
                "modules": module_summaries,
                "warnings": warnings,
            })
            set_run_state(session, run, "MODULE_DETECTION")

        for species in ("human", "mouse") if run_networks else ():
            network_name = f"{species}_cancer"
            network_nodes = network_nodes_by_name.get(network_name, pd.DataFrame(columns=[
                "gene_id", "degree", "weighted_degree", "betweenness_centrality",
                "closeness_centrality", "eigenvector_centrality", "module_id",
            ]))
            deg_frame = deg_results.get(species, pd.DataFrame(columns=[
                "gene_id", "log2fc", "adjusted_p_value", "significant", "direction",
            ]))
            integrated = deg_frame.merge(network_nodes, on="gene_id", how="outer")
            if integrated.empty:
                continue
            integrated.insert(0, "species", species)
            integrated["comparison_status"] = deg_summaries.get(species, {}).get("status", "unavailable")
            integrated.to_csv(phase3_root / "integrated" / f"{species}_gene_integration.csv", index=False)

        summary = {
            "run_id": run_id,
            "status": "COMPLETED" if stage == "phase3" else "PARTIAL",
            "target_stage": stage,
            "datasets": [
                {
                    "dataset_id": item["dataset"].id,
                    "accession": item["dataset"].accession,
                    "species": item["dataset"].species.value,
                    "expression_path": str(item["expression_path"].resolve()),
                    "metadata_path": str(item["metadata_path"].resolve()),
                    "artifact_resolution": item["artifact_resolution"],
                }
                for item in by_accession.values()
            ],
            "deg": deg_summaries,
            "networks": network_summaries,
            "modules": module_summaries,
            "figures": figure_records,
            "warnings": warnings,
            "limitations": [
                "GSE155577 has no healthy mouse controls, so mouse cancer-versus-normal DEG is unavailable.",
                "GSE116385 is a separate normal-only GEO cohort and was not merged with GSE155577.",
                "Cross-species orthology alignment is outside Phase 3.",
            ],
            "parameters": {
                "differential_expression": de_config,
                "networks": network_config,
                "modules": module_config,
                "phase3_config_source": phase3_config_source,
                "random_seed": int(config.get("random_seed", 42)),
            },
            "git_commit": _read_git_revision(),
            "git_worktree_dirty": _git_worktree_dirty(),
            "pipeline_version": "pathdrift-phase3/1.0.0",
            "software_versions": _software_versions(),
            "result_directory": str(phase3_root.resolve()),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        stage_summaries = dict(prior.get("stages", {}))
        stage_summaries[stage] = {"status": "COMPLETED", "summary": summary}
        if stage == "phase3":
            _write_json(phase3_root / "deg" / "network_module_summary.json", summary)
        manifest["phase3"] = {
            "status": "COMPLETED" if stage == "phase3" else "PARTIAL",
            "summary": summary,
            "stages": stage_summaries,
        }
        manifest["status"] = "COMPLETED"
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(manifest_path, manifest)
        run.config = {
            **(run.config or {}),
            **effective_sections,
            "phase3_config_source": phase3_config_source,
            "phase3_summary": summary,
        }
        run.status = "COMPLETED"
        run.stage = "COMPLETED"
        run.error_message = None
        run.config = {**(run.config or {}), "phase3_summary": summary}
        run.completed_at = datetime.now(timezone.utc)
        session.commit()
        return summary
    except Exception as exc:
        session.rollback()
        if run is not None:
            failed = session.get(type(run), run_id)
            if failed is not None:
                failed.status = "FAILED"
                failed.stage = "FAILED"
                failed.error_message = str(exc)
                failed.completed_at = datetime.now(timezone.utc)
                session.commit()
        logger.exception("Phase 3 execution failed for run %s", run_id)
        raise
    finally:
        session.close()
