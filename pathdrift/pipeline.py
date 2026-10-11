from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import matplotlib
import pandas as pd
import yaml
from scipy.cluster.hierarchy import dendrogram, linkage

from .acquisition.gdc import acquire_gdc
from .acquisition.geo import acquire_geo
from .acquisition.gtex import acquire_gtex_breast_reference
from .acquisition.qc import QCConfig, run_quality_control, write_qc_outputs
from .acquisition.registry import (
    create_run,
    json_safe,
    open_session,
    register_dataset,
    resolve_project,
    set_run_state,
)
from .acquisition.validators import validate_dataset_files


ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("pathdrift.pipeline")


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    if not config_path.is_file():
        raise FileNotFoundError(f"Run configuration does not exist: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Run configuration must be a YAML mapping")
    for key in ("project", "datasets", "normal_reference", "qc"):
        if not isinstance(config.get(key), dict):
            raise ValueError(f"Run configuration is missing the {key} mapping")
    return config


def _date(value: Any) -> datetime:
    if value:
        parsed = date.fromisoformat(str(value)[:10])
        return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(value), indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _aggregate_qc(results: list[dict[str, Any]], qc_root: Path, run_config: dict[str, Any]) -> dict[str, Any]:
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    qc_root.mkdir(parents=True, exist_ok=True)
    sample_frames = []
    pca_frames = []
    cluster_frames = []
    correlation_records = []
    dataset_summaries = {}
    outliers = []
    batch_variables = []
    normalization_methods = {}

    for item in results:
        accession = item["accession"]
        result = item["qc"]
        sample_frame = result["sample_qc"].copy()
        sample_frame.insert(0, "accession", accession)
        sample_frames.append(sample_frame)
        pca_frame = result["pca_coordinates"].rename_axis("sample_id").reset_index()
        pca_frame.insert(0, "accession", accession)
        pca_frames.append(pca_frame)
        cluster_frame = result["sample_clustering"].copy()
        cluster_frame.insert(0, "accession", accession)
        cluster_frames.append(cluster_frame)
        corr = result["sample_correlation"]
        for sample_a in corr.index:
            for sample_b in corr.columns:
                correlation_records.append({
                    "accession": accession,
                    "sample_a": str(sample_a),
                    "sample_b": str(sample_b),
                    "pearson_r": float(corr.loc[sample_a, sample_b]),
                })
        dataset_summaries[accession] = result["summary"]
        outliers.extend({"accession": accession, **entry} for entry in result["summary"]["outliers"])
        batch_variables.extend({"accession": accession, **entry} for entry in result["summary"]["batch_variables"])
        normalization_methods[accession] = result["summary"]["normalization_method"]

    sample_qc = pd.concat(sample_frames, ignore_index=True)
    pca = pd.concat(pca_frames, ignore_index=True)
    clustering = pd.concat(cluster_frames, ignore_index=True)
    correlation = pd.DataFrame(correlation_records)
    sample_qc.to_csv(qc_root / "sample_qc.csv", index=False)
    pca.to_csv(qc_root / "pca_coordinates.csv", index=False)
    correlation.to_csv(qc_root / "sample_correlation.csv", index=False)
    clustering.to_csv(qc_root / "sample_clustering.csv", index=False)

    columns = 1 if len(results) == 1 else 2
    rows = (len(results) + columns - 1) // columns
    fig, axes = plt.subplots(rows, columns, figsize=(7 * columns, 5 * rows), squeeze=False)
    for axis, item in zip(axes.flat, results):
        accession = item["accession"]
        coords = item["qc"]["pca_coordinates"]
        qc = item["qc"]["sample_qc"].set_index("sample_id")
        for state in sorted(qc.loc[coords.index, "disease_state"].astype(str).unique()):
            ids = qc.index[qc["disease_state"].astype(str) == state].intersection(coords.index)
            axis.scatter(coords.loc[ids, "PC1"], coords.loc[ids, "PC2"], label=state, alpha=0.85)
        axis.set(title=f"{accession}: sample PCA", xlabel="PC1", ylabel="PC2")
        axis.legend(fontsize=8)
    for axis in axes.flat[len(results):]:
        axis.set_visible(False)
    fig.tight_layout()
    fig.savefig(qc_root / "pca.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(rows, columns, figsize=(7 * columns, 6 * rows), squeeze=False)
    for axis, item in zip(axes.flat, results):
        sns.heatmap(item["qc"]["sample_correlation"], cmap="vlag", vmin=-1, vmax=1, square=True, ax=axis)
        axis.set_title(f"{item['accession']}: sample Pearson correlation")
    for axis in axes.flat[len(results):]:
        axis.set_visible(False)
    fig.tight_layout()
    fig.savefig(qc_root / "sample_correlation.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(rows, columns, figsize=(8 * columns, 6 * rows), squeeze=False)
    for axis, item in zip(axes.flat, results):
        expression = item["qc"]["normalized_expression"].T.to_numpy(dtype=float)
        tree = linkage(expression, method="average", metric="correlation")
        dendrogram(tree, labels=item["qc"]["pca_coordinates"].index.tolist(), leaf_rotation=90, leaf_font_size=6, ax=axis)
        axis.set_title(f"{item['accession']}: hierarchical sample clustering")
        axis.set_ylabel("Correlation distance")
    for axis in axes.flat[len(results):]:
        axis.set_visible(False)
    fig.tight_layout()
    fig.savefig(qc_root / "sample_clustering.png", dpi=160)
    plt.close(fig)

    summary = {
        "datasets": dataset_summaries,
        "dataset_count": len(results),
        "initial_samples": sum(item["initial_samples"] for item in dataset_summaries.values()),
        "retained_samples": sum(item["retained_samples"] for item in dataset_summaries.values()),
        "initial_genes": {key: value["initial_genes"] for key, value in dataset_summaries.items()},
        "retained_genes": {key: value["retained_genes"] for key, value in dataset_summaries.items()},
        "excluded_samples": [
            {"accession": accession, "sample_id": sample_id}
            for accession, entry in dataset_summaries.items()
            for sample_id in entry["excluded_samples"]
        ],
        "excluded_genes": {key: value["excluded_genes"] for key, value in dataset_summaries.items()},
        "outliers": outliers,
        "batch_variables": batch_variables,
        "normalization_method": normalization_methods,
        "normal_reference": run_config["normal_reference"],
    }
    _write_json(qc_root / "summary.json", summary)
    return summary


def run_phase2(config_path: str | Path) -> dict[str, Any]:
    config = load_config(config_path)
    datasets_config = config["datasets"]
    if not datasets_config.get("human", {}).get("project"):
        raise ValueError("Configure datasets.human.project with a GDC project accession")
    if not datasets_config.get("mouse", {}).get("accession"):
        raise ValueError("Mouse GEO accession is empty; configure datasets.mouse.accession. No substitute will be selected.")
    if config["normal_reference"].get("primary_strategy") != "tcga_adjacent_normal":
        raise ValueError("This run requires an explicit human normal-reference strategy")

    output_root = ROOT / "results" / "runs"
    acquisition_root = ROOT / "backend" / "uploads" / "data_acquisition"
    raw_root = acquisition_root / "raw"
    processed_root = acquisition_root / "processed"
    run_id = str(uuid4())
    run_dir = output_root / run_id
    qc_root = run_dir / "qc"
    run_dir.mkdir(parents=True, exist_ok=False)

    session = open_session()
    run = None
    try:
        project = resolve_project(
            session,
            str(config["project"].get("name", "")),
            str(config["project"].get("owner_username", "")),
        )
        run = create_run(session, project.id, config, run_id)
        run.run_dir = str(run_dir.resolve())
        session.commit()
        set_run_state(session, run, "RUNNING")
        set_run_state(session, run, "ACQUIRING_DATA")
        logger.info("Acquiring TCGA-BRCA", extra={"run_id": run_id})

        acquired = []
        for key in ("human", "mouse"):
            dataset_config = dict(datasets_config[key])
            source = str(dataset_config.get("source", "")).casefold()
            destination = raw_root / ("gdc" if source == "gdc" else "geo")
            if source == "gdc":
                expression_path, metadata_path, source_info = acquire_gdc(dataset_config, destination)
                accession = str(dataset_config["project"])
            elif source == "geo":
                expression_path, metadata_path, source_info = acquire_geo(dataset_config, destination)
                accession = str(dataset_config["accession"])
            else:
                raise ValueError(f"Unsupported configured source for datasets.{key}: {source!r}")
            acquired.append({
                "key": key,
                "config": dataset_config,
                "accession": accession,
                "expression_path": expression_path,
                "metadata_path": metadata_path,
                "source_info": source_info,
            })
            logger.info("Downloaded files verified", extra={"run_id": run_id, "accession": accession})

        reference_config = config["normal_reference"]
        if reference_config.get("enabled"):
            expression_path, metadata_path, source_info = acquire_gtex_breast_reference(
                ROOT / "data" / "reference", str(reference_config.get("version", "v10"))
            )
            acquired.append({
                "key": "normal_reference",
                "config": {
                    "source": "gtex", "species": "human", "tissue": reference_config["tissue"],
                    "data_type": "tpm", "version": reference_config["version"],
                    "normalization_method": "auto", "source_download_date": date.today().isoformat(),
                },
                "accession": source_info["accession"],
                "expression_path": expression_path,
                "metadata_path": metadata_path,
                "source_info": source_info,
            })

        set_run_state(session, run, "VALIDATING_DATA")
        logger.info("Validating acquired data", extra={"run_id": run_id})
        validated = []
        for item in acquired:
            cfg = item["config"]
            files = validate_dataset_files(
                item["expression_path"],
                item["metadata_path"],
                expected_expression_sha256=item["source_info"]["expression"]["sha256"],
                expected_metadata_sha256=item["source_info"]["metadata"]["sha256"],
            )
            if files["sample_columns"] != item["source_info"].get("series_sample_count", files["sample_columns"]):
                raise ValueError(f"Observed sample count does not match source metadata for {item['accession']}")
            if cfg["species"] == "human":
                normal = files["metadata"]["disease_state"].astype(str).str.casefold().isin({"healthy", "normal", "control"})
                if item["accession"] == "TCGA-BRCA" and int(normal.sum()) == 0:
                    raise ValueError("TCGA-BRCA data has no adjacent-normal samples for the configured reference strategy")
                    files["metadata"]["species"] = str(cfg["species"])
                    files["metadata"]["tissue"] = str(cfg["tissue"])
                    files["metadata"]["accession"] = item["accession"]
                    files["metadata"]["source"] = str(item["source_info"].get("source", cfg["source"]))
                    files["metadata"]["platform"] = str(cfg.get("platform") or item["source_info"].get("platform") or "unknown")
                    files["metadata"]["study"] = item["accession"]
            item.update(files)
            validated.append(item)
            logger.info("Validation passed", extra={
                "run_id": run_id,
                "accession": item["accession"],
                "samples": files["sample_columns"],
                "genes": files["gene_rows"],
            })

        set_run_state(session, run, "QC")
        logger.info("Starting sample quality control", extra={"run_id": run_id})
        qc_config = QCConfig(**config["qc"])
        results = []
        registered = []
        for item in validated:
            accession = item["accession"]
            cfg = item["config"]
            qc = run_quality_control(
                item["expression"],
                item["metadata"],
                species=str(cfg["species"]),
                data_type=str(cfg["data_type"]),
                config=qc_config,
                normalization_method=str(cfg.get("normalization_method", "auto")),
            )
            dataset_dir = qc_root / accession.replace("/", "_")
            write_qc_outputs(qc, dataset_dir)
            processed_path = processed_root / run_id / f"{accession.replace('/', '_')}_normalized.parquet"
            processed_path.parent.mkdir(parents=True, exist_ok=True)
            qc["normalized_expression"].rename_axis("gene_id").to_parquet(processed_path)
            results.append({"accession": accession, "qc": qc, "processed_path": processed_path, "dataset_dir": dataset_dir})
            logger.info("Normalization and QC completed", extra={
                "run_id": run_id,
                "accession": accession,
                "normalization_method": qc["summary"]["normalization_method"],
                "retained_samples": qc["summary"]["retained_samples"],
                "retained_genes": qc["summary"]["retained_genes"],
            })

        summary = _aggregate_qc(results, qc_root, config)
        provenance = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "normal_reference_strategy": config["normal_reference"],
            "datasets": [
                {
                    "accession": item["accession"],
                    "source": item["source_info"],
                    "expression_sha256": item["expression_sha256"],
                    "metadata_sha256": item["metadata_sha256"],
                    "raw_paths": [str(item["expression_path"].resolve()), str(item["metadata_path"].resolve())],
                    "processed_path": str(result["processed_path"].resolve()),
                    "qc_directory": str(result["dataset_dir"].resolve()),
                }
                for item, result in zip(validated, results)
            ],
            "processing_steps": [
                "verify remote accession and repository metadata",
                "verify raw file SHA-256 and expression/metadata sample alignment",
                "normalize stable Ensembl IDs and aggregate version-equivalent duplicate IDs",
                "apply configured gene/sample expression and missingness filters",
                "apply normalization selected from declared data type",
                "calculate sample QC, PCA, Pearson correlation, hierarchical clustering, and outlier flags",
            ],
            "limitations": [
                "GSE155577 contains mammary tumor samples and no healthy mouse mammary controls.",
                "The primary human normal reference is TCGA adjacent normal; GTEx remains a separate optional external reference and was not acquired or merged in this run.",
            ],
        }
        manifest = {
            "run_id": run_id,
            "project": config["project"],
            "status": "COMPLETED",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "datasets": [
                {
                    "accession": item["accession"],
                    "source": item["source_info"].get("source"),
                    "species": item["config"]["species"],
                    "tissue": item["config"]["tissue"],
                    "data_type": item["config"]["data_type"],
                    "raw_expression_path": str(item["expression_path"].resolve()),
                    "metadata_path": str(item["metadata_path"].resolve()),
                    "processed_path": str(result["processed_path"].resolve()),
                    **result["qc"]["summary"],
                }
                for item, result in zip(validated, results)
            ],
            "qc": summary,
        }
        manifest_path = run_dir / "manifest.json"
        provenance_path = run_dir / "provenance.json"
        _write_json(manifest_path, manifest)
        _write_json(provenance_path, provenance)

        project = resolve_project(
            session,
            str(config["project"]["name"]),
            str(config["project"]["owner_username"]),
        )
        for item, result in zip(validated, results):
            cfg = item["config"]
            dataset = register_dataset(
                session,
                run,
                project,
                accession=item["accession"],
                name=str(cfg.get("name", f"{item['accession']} expression dataset")),
                source=str(item["source_info"].get("source", cfg["source"])).upper(),
                species=str(cfg["species"]),
                tissue=str(cfg["tissue"]),
                platform=str(cfg.get("platform") or item["source_info"].get("platform") or "Not reported"),
                data_type=str(cfg["data_type"]),
                version=cfg.get("version"),
                expression_path=str(result["processed_path"].resolve()),
                metadata_path=str(item["metadata_path"].resolve()),
                raw_expression_path=str(item["expression_path"].resolve()),
                checksum=item["expression_sha256"],
                download_date=_date(cfg.get("source_download_date")),
                retrieval_url=str(item["source_info"].get("retrieval_url", "")),
                processing_steps={
                    "normalization_method": result["qc"]["summary"]["normalization_method"],
                    "qc_config": result["qc"]["summary"]["configuration"],
                    "qc_summary": result["qc"]["summary"],
                },
                provenance=item["source_info"],
                metadata=item["metadata"],
                qc_result=result["qc"],
            )
            registered.append(dataset)
        run.qc_summary = json_safe(summary)
        run.manifest_path = str(manifest_path.resolve())
        run.provenance_path = str(provenance_path.resolve())
        run.run_dir = str(run_dir.resolve())
        run.status = "COMPLETED"
        run.stage = "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        session.commit()
        logger.info("QC completed", extra={"run_id": run_id})
        return {"run_id": run_id, "status": "COMPLETED", "summary": summary, "run_dir": str(run_dir.resolve())}
    except Exception as error:
        session.rollback()
        if run is not None:
            failed_run = session.get(type(run), run_id)
            if failed_run is not None:
                failed_run.status = "FAILED"
                failed_run.stage = "FAILED"
                failed_run.error_message = str(error)
                failed_run.completed_at = datetime.now(timezone.utc)
                session.commit()
        raise
    finally:
        session.close()