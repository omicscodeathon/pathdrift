from __future__ import annotations

import csv
import html
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bio.deg import DEGAnalyzer
from app.bio.identifiers import enforce_ensembl_gene_ids
from app.bio.network import NetworkConstructor, compute_network_statistics
from app.bio.orthology import validate_one_to_one_mappings
from app.bio.preprocessing import PreprocessingPipeline
from app.ml.engine import MLEngine

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "pathdrift"
RAW_ROOT = DATA_ROOT / "raw"
PROCESSED_ROOT = DATA_ROOT / "processed"
RUN_ID = datetime.now(timezone.utc).strftime("real_breast_%Y%m%dT%H%M%SZ")
RUN_ROOT = ROOT / "results" / "runs" / RUN_ID
RANDOM_SEED = 42
NETWORK_TOP_N = 300


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def current_ensembl_release() -> int:
    response = httpx.get(
        "https://rest.ensembl.org/info/data",
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    releases = response.json().get("releases", [])
    if not releases:
        raise RuntimeError("Ensembl REST did not report a data release")
    return int(max(releases))


def download_orthology() -> pd.DataFrame:
    ensembl_release = current_ensembl_release()
    query = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE Query><Query virtualSchemaName="default" formatter="TSV" header="1" '
        'uniqueRows="1" count="" datasetConfigVersion="0.6">'
        '<Dataset name="hsapiens_gene_ensembl" interface="default">'
        '<Filter name="with_mmusculus_homolog" excluded="0"/>'
        '<Attribute name="ensembl_gene_id"/><Attribute name="external_gene_name"/>'
        '<Attribute name="mmusculus_homolog_ensembl_gene"/>'
        '<Attribute name="mmusculus_homolog_associated_gene_name"/>'
        '<Attribute name="mmusculus_homolog_orthology_type"/>'
        '<Attribute name="mmusculus_homolog_orthology_confidence"/>'
        '</Dataset></Query>'
    )
    response = httpx.post(
        "https://mart.ensembl.org/biomart/martservice",
        content=f"query={query}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=300,
    )
    response.raise_for_status()
    rows = []
    for row in csv.DictReader(io.StringIO(response.text), delimiter="\t"):
        human_id = row.get("Gene stable ID", "").strip()
        mouse_id = row.get("Mouse gene stable ID", "").strip()
        if not human_id or not mouse_id or row.get("Mouse homology type") != "ortholog_one2one":
            continue
        rows.append({
            "human_ensembl_id": human_id,
            "mouse_ensembl_id": mouse_id,
            "human_symbol": row.get("Gene name", "").strip(),
            "mouse_symbol": row.get("Mouse gene name", "").strip(),
            "orthology_type": "ortholog_one2one",
            "confidence": float(row.get("Mouse orthology confidence [0 low, 1 high]", "0") or 0),
            "ensembl_release": ensembl_release,
        })
    if not rows:
        raise RuntimeError("Ensembl BioMart returned no one-to-one human-mouse orthologues")
    return validate_one_to_one_mappings(pd.DataFrame(rows))


def build_network(expression: pd.DataFrame, sample_ids: list[str], name: str, output_dir: Path) -> tuple[object, pd.DataFrame, dict]:
    constructor = NetworkConstructor(
        correlation_method="spearman",
        correlation_threshold=0.7,
        fdr_threshold=0.05,
        top_n_genes=NETWORK_TOP_N,
        min_gene_variance=0.0,
        random_seed=RANDOM_SEED,
    )
    graph, nodes = constructor.build(expression, sample_ids)
    output_dir.mkdir(parents=True, exist_ok=True)
    edge_rows = [
        {"gene1": left, "gene2": right, "weight": attrs["weight"], "correlation": attrs.get("correlation")}
        for left, right, attrs in graph.edges(data=True)
    ]
    pd.DataFrame(edge_rows, columns=["gene1", "gene2", "weight", "correlation"]).to_parquet(output_dir / "edges.parquet", index=False)
    nodes.reset_index().to_parquet(output_dir / "nodes_modules.parquet", index=False)
    stats = compute_network_statistics(graph)
    stats.update({"name": name, "n_samples": len(sample_ids), "n_genes_selected": len(nodes), "top_n_genes": NETWORK_TOP_N})
    return graph, nodes, stats


def main() -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    raw_human = pd.read_csv(RAW_ROOT / "gdc" / "tcga_brca_real_expression.tsv.gz", sep="\t", compression="gzip", index_col=0, low_memory=False)
    human_metadata = pd.read_csv(RAW_ROOT / "gdc" / "tcga_brca_real_metadata.tsv", sep="\t")
    raw_mouse = pd.read_csv(RAW_ROOT / "geo" / "GSE155577_expression.tsv.gz", sep="\t", compression="gzip", low_memory=False).set_index("gene_id")
    mouse_metadata = pd.read_csv(RAW_ROOT / "geo" / "GSE155577_metadata.tsv", sep="\t")
    raw_human, excluded_human_gene_ids = enforce_ensembl_gene_ids(raw_human, "human")
    raw_mouse, excluded_mouse_gene_ids = enforce_ensembl_gene_ids(raw_mouse, "mouse")

    human_metadata["sample_id"] = human_metadata["sample_id"].astype(str)
    human_metadata["disease_state"] = human_metadata["disease_state"].astype(str).str.lower()
    human_metadata["patient_id"] = human_metadata.get("case_id", human_metadata["sample_id"].str[:12]).astype(str)
    human_metadata = human_metadata.drop_duplicates(["patient_id", "disease_state"], keep="first")
    human_metadata = human_metadata[human_metadata["sample_id"].isin(raw_human.columns)]
    raw_human = raw_human.loc[:, human_metadata["sample_id"].tolist()]

    human_expr, human_log = PreprocessingPipeline(
        normalization_method="log2cpm", low_expr_threshold=1.0, low_expr_min_samples=3,
        min_gene_variance=0.0, outlier_detection=False,
    ).run(raw_human, human_metadata, "TCGA-BRCA", "Human")
    mouse_expr, mouse_log = PreprocessingPipeline(
        normalization_method="none", low_expr_threshold=0.0, low_expr_min_samples=1,
        min_gene_variance=0.0, outlier_detection=False,
    ).run(raw_mouse, mouse_metadata, "GSE155577", "Mouse")

    human_metadata = human_metadata[human_metadata["sample_id"].isin(human_expr.columns)]
    healthy_samples = human_metadata.loc[human_metadata["disease_state"].isin(["healthy", "normal", "control"]), "sample_id"].tolist()
    cancer_samples = human_metadata.loc[human_metadata["disease_state"].isin(["cancer", "tumor", "disease"]), "sample_id"].tolist()
    if len(healthy_samples) < 2 or len(cancer_samples) < 2:
        raise RuntimeError(f"Human DEG requires >=2 samples per group; found healthy={len(healthy_samples)}, cancer={len(cancer_samples)}")

    human_processed_path = PROCESSED_ROOT / "gdc" / "tcga_brca_real_preprocessed.parquet"
    mouse_processed_path = PROCESSED_ROOT / "geo" / "gse155577_real_preprocessed.parquet"
    human_processed_path.parent.mkdir(parents=True, exist_ok=True)
    mouse_processed_path.parent.mkdir(parents=True, exist_ok=True)
    human_expr.to_parquet(human_processed_path)
    mouse_expr.to_parquet(mouse_processed_path)
    human_expr.to_parquet(RUN_ROOT / "human_expression_preprocessed.parquet")
    mouse_expr.to_parquet(RUN_ROOT / "mouse_expression_preprocessed.parquet")
    human_metadata.to_csv(RUN_ROOT / "human_sample_metadata.tsv", sep="\t", index=False)
    mouse_metadata.to_csv(RUN_ROOT / "mouse_sample_metadata.tsv", sep="\t", index=False)

    manifest_path = DATA_ROOT / "manifests" / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"datasets": []}
    manifest_by_accession = {entry.get("accession"): entry for entry in manifest.get("datasets", [])}
    manifest_updates = {
        "TCGA-BRCA": {
            "data_type": "normalized",
            "raw_sample_count": int(len(pd.read_csv(RAW_ROOT / "gdc" / "tcga_brca_real_metadata.tsv", sep="\t"))),
            "sample_count": int(human_expr.shape[1]),
            "n_samples": int(human_expr.shape[1]),
            "n_healthy": len(healthy_samples),
            "n_cancer": len(cancer_samples),
            "gene_count": int(human_expr.shape[0]),
            "n_genes": int(human_expr.shape[0]),
            "normalization_method": "log2cpm",
            "platform": "Illumina sequencing; GDC STAR - Counts workflow",
            "source_data_type": "RNA-Seq unstranded gene counts",
            "genome_build": "GRCh38 (GDC STAR - Counts; GENCODE v36 gene model)",
            "download_date": "2026-10-04",
            "processed_expression_path": str(human_processed_path),
            "identifier_fields": ["file_uuid", "file_name", "case_uuid", "case_submitter_id", "sample_uuid", "sample_id", "aliquot_uuid", "aliquot_submitter_id"],
            "clinical_fields": ["sex_at_birth", "race", "ethnicity", "days_to_birth", "age_at_index_years", "vital_status", "age_at_diagnosis_days", "ajcc_pathologic_stage", "primary_diagnosis", "tumor_grade", "morphology", "days_to_last_follow_up"],
            "clinical_coverage": {
                "samples_with_demographic_fields": int(human_metadata["sex_at_birth"].notna().sum()),
                "samples_with_pathologic_stage": int(human_metadata["ajcc_pathologic_stage"].notna().sum()),
                "samples_with_aliquot_uuid": int(human_metadata["aliquot_uuid"].notna().sum()),
            },
            "analysis_note": "Raw matrix retains all retrieved aliquots; patient-grouped analysis excludes repeated tumor aliquots. TCGA adjacent normals are used to avoid cross-repository batch effects; GTEx was not mixed into the primary DEG contrast.",
        },
        "GSE155577": {
            "data_type": "normalized",
            "sample_count": int(mouse_expr.shape[1]),
            "n_samples": int(mouse_expr.shape[1]),
            "n_healthy": 0,
            "n_cancer": int(mouse_expr.shape[1]),
            "gene_count": int(mouse_expr.shape[0]),
            "n_genes": int(mouse_expr.shape[0]),
            "normalization_method": "none",
            "platform": "Illumina HiSeq 1000",
            "source_data_type": "Study-normalized RNA-Seq expression values",
            "genome_build": "Not reported in GEO series/sample metadata",
            "download_date": "2026-10-04",
            "unmapped_source_gene_ids_excluded_from_analysis": excluded_mouse_gene_ids,
            "processed_expression_path": str(mouse_processed_path),
            "identifier_fields": ["sample_id", "geo_sample_id", "biosample_accession", "sra_accession"],
            "sample_origins": {
                "in_vivo_mammary_tumor_cells": int((~mouse_metadata["geo_title"].str.contains("cell line", case=False, na=False)).sum()),
                "cultured_tumor_cell_line": int(mouse_metadata["geo_title"].str.contains("cell line", case=False, na=False).sum()),
            },
            "analysis_note": "Study-provided normalized values. The series contains 24 in-vivo tumor-cell samples and two cultured cell-line samples; no healthy mouse mammary controls.",
        },
    }
    for accession, updates in manifest_updates.items():
        entry = manifest_by_accession.get(accession)
        if entry is not None:
            entry.update(updates)
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(manifest_path, manifest)
    from app.services.data_acquisition.dataset_registry import write_dataset_registry
    write_dataset_registry(manifest_path)

    deg = DEGAnalyzer(method="ttest", fdr_threshold=0.05, lfc_threshold=1.0).run(human_expr, healthy_samples, cancer_samples)
    deg.to_parquet(RUN_ROOT / "human_deg.parquet")
    deg.reset_index().to_csv(RUN_ROOT / "human_deg.tsv", sep="\t", index=False)

    human_healthy_graph, human_healthy_nodes, human_healthy_stats = build_network(
        human_expr, healthy_samples, "human_healthy", RUN_ROOT / "networks" / "human_healthy"
    )
    human_cancer_graph, human_cancer_nodes, human_cancer_stats = build_network(
        human_expr, cancer_samples, "human_cancer", RUN_ROOT / "networks" / "human_cancer"
    )
    in_vivo_mouse = ~mouse_metadata["geo_title"].astype(str).str.contains("cell line", case=False, na=False)
    mouse_samples = [
        str(sample)
        for sample in mouse_metadata.loc[in_vivo_mouse, "sample_id"]
        if str(sample) in mouse_expr.columns
    ]
    mouse_cancer_graph, mouse_cancer_nodes, mouse_cancer_stats = build_network(
        mouse_expr, mouse_samples, "mouse_tumor", RUN_ROOT / "networks" / "mouse_tumor"
    )

    orthology = download_orthology()
    ensembl_release = int(orthology["ensembl_release"].iloc[0])
    orthology_path = DATA_ROOT / "raw" / "orthology" / "ensembl_one_to_one.tsv"
    orthology_path.parent.mkdir(parents=True, exist_ok=True)
    orthology.to_csv(orthology_path, sep="\t", index=False)
    orthology.to_csv(RUN_ROOT / "orthology_one_to_one.tsv", sep="\t", index=False)

    human_network_genes = set(human_cancer_graph.nodes())
    mouse_network_genes = set(mouse_cancer_graph.nodes())
    orthology_used = validate_one_to_one_mappings(orthology)
    orthology_used = orthology_used[
        orthology["human_ensembl_id"].isin(human_network_genes)
        & orthology["mouse_ensembl_id"].isin(mouse_network_genes)
    ]
    human_to_mouse = dict(zip(orthology_used["human_ensembl_id"], orthology_used["mouse_ensembl_id"]))
    mapped_human_edges = {
        tuple(sorted((human_to_mouse[left], human_to_mouse[right])))
        for left, right in human_cancer_graph.edges()
        if left in human_to_mouse and right in human_to_mouse and human_to_mouse[left] != human_to_mouse[right]
    }
    mouse_edges = {tuple(sorted((left, right))) for left, right in mouse_cancer_graph.edges()}
    shared_edges = mapped_human_edges & mouse_edges
    union_edges = mapped_human_edges | mouse_edges
    alignment = {
        "scope": "exploratory tumor-network alignment; not differential drift",
        "n_one_to_one_orthologs_in_networks": len(orthology_used),
        "n_human_edges_mapped_to_mouse_ids": len(mapped_human_edges),
        "n_mouse_edges": len(mouse_edges),
        "n_shared_edges": len(shared_edges),
        "edge_jaccard": len(shared_edges) / len(union_edges) if union_edges else 0.0,
    }
    save_json(RUN_ROOT / "cross_species_alignment.json", alignment)

    pathway_status = "skipped_no_significant_degs"
    significant_genes = deg.index[deg["significant"]].astype(str).tolist()
    human_symbol_map = dict(zip(orthology["human_ensembl_id"], orthology["human_symbol"]))
    from app.bio.pathways import PathwayAnalyzer
    symbols = PathwayAnalyzer.symbols_from_ensembl(significant_genes, human_symbol_map)
    pd.DataFrame([
        {"ensembl_gene_id": gene_id, "gene_symbol_display": human_symbol_map[gene_id], "mapping_source": "Ensembl BioMart one-to-one orthology table"}
        for gene_id in significant_genes if human_symbol_map.get(gene_id)
    ]).to_csv(RUN_ROOT / "human_deg_symbol_display_mapping.tsv", sep="\t", index=False)
    if len(symbols) >= 5:
        try:
            pathway_results = PathwayAnalyzer(species="human", fdr_threshold=0.05).run_ora(
                symbols, "GO_Biological_Process_2023", list(set(human_symbol_map.values()) - {""})
            )
            pathway_results.to_csv(RUN_ROOT / "human_pathways.tsv", sep="\t", index=False)
            pathway_status = "completed" if "error" not in pathway_results.columns else "failed"
        except Exception as exc:
            pathway_status = f"failed: {exc}"

    ml_status = "blocked_no_balanced_labels"
    ml_summary: dict = {}
    if len(healthy_samples) >= 5 and len(cancer_samples) >= 5:
        y = pd.Series([0] * len(healthy_samples) + [1] * len(cancer_samples), index=healthy_samples + cancer_samples)
        groups = human_metadata.set_index("sample_id").loc[y.index, "patient_id"]
        features = human_expr.loc[human_expr.var(axis=1).nlargest(500).index].T.loc[y.index]
        try:
            engine = MLEngine(
                model_type="logistic_regression",
                experiment_type="expression_only",
                random_seed=RANDOM_SEED,
                cv_folds=min(5, len(healthy_samples), len(cancer_samples)),
                feature_selection_k=50,
                class_weight="balanced",
                model_save_dir=str(RUN_ROOT / "models"),
            )
            splitter = StratifiedGroupKFold(
                n_splits=engine.cv_folds,
                shuffle=True,
                random_state=RANDOM_SEED,
            )
            fold_metrics = []
            for fold_index, (train_indices, test_indices) in enumerate(splitter.split(features, y, groups), start=1):
                fold_pipeline = engine._build_pipeline()
                X_train, X_test = features.iloc[train_indices], features.iloc[test_indices]
                y_train, y_test = y.iloc[train_indices], y.iloc[test_indices]
                fold_pipeline.fit(X_train, y_train)
                predictions = fold_pipeline.predict(X_test)
                probabilities = fold_pipeline.predict_proba(X_test)[:, 1]
                fold_metrics.append({
                    "fold": fold_index,
                    "n_train": len(train_indices),
                    "n_test": len(test_indices),
                    "auroc": float(roc_auc_score(y_test, probabilities)) if y_test.nunique() == 2 else None,
                    "auprc": float(average_precision_score(y_test, probabilities)) if y_test.nunique() == 2 else None,
                    "accuracy": float(accuracy_score(y_test, predictions)),
                    "f1": float(f1_score(y_test, predictions, zero_division=0)),
                    "test_patients": sorted(set(groups.iloc[test_indices])),
                })
            final_pipeline = engine._build_pipeline()
            final_pipeline.fit(features, y)
            model_path = RUN_ROOT / "models" / f"{RUN_ID}_human_expression_grouped_cv.joblib"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(final_pipeline, model_path)
            auroc_values = [row["auroc"] for row in fold_metrics if row["auroc"] is not None]
            auprc_values = [row["auprc"] for row in fold_metrics if row["auprc"] is not None]
            ml_summary = {
                "status": "exploratory_patient_grouped_internal_cv_only",
                "n_samples": len(y),
                "n_patients": int(groups.nunique()),
                "cv_scheme": "StratifiedGroupKFold; patient IDs kept within a single fold",
                "mean_auroc": float(np.mean(auroc_values)) if auroc_values else None,
                "mean_auprc": float(np.mean(auprc_values)) if auprc_values else None,
                "folds": fold_metrics,
                "model_path": str(model_path),
                "external_validation": "not performed; no independent cohort",
                "caveat": "Small exploratory cohort; metrics are not evidence of clinical performance.",
            }
            save_json(RUN_ROOT / "ml_grouped_cv.json", ml_summary)
            ml_status = "exploratory_patient_grouped_internal_cv_only"
        except Exception as exc:
            ml_status = f"failed: {exc}"

    network_summary = {
        "human_healthy": human_healthy_stats,
        "human_cancer": human_cancer_stats,
        "mouse_tumor": mouse_cancer_stats,
        "module_counts": {
            "human_healthy": int(human_healthy_nodes["module"].nunique()) if "module" in human_healthy_nodes else 0,
            "human_cancer": int(human_cancer_nodes["module"].nunique()) if "module" in human_cancer_nodes else 0,
            "mouse_tumor": int(mouse_cancer_nodes["module"].nunique()) if "module" in mouse_cancer_nodes else 0,
        },
        "interpretation": "Exploratory correlations; small per-state sample counts limit edge stability.",
    }
    save_json(RUN_ROOT / "network_summary.json", network_summary)

    significant_count = int(deg["significant"].sum())
    result_provenance = [
        {"result": "human_deg.tsv", "accessions": ["TCGA-BRCA"]},
        {"result": "human_deg.parquet", "accessions": ["TCGA-BRCA"]},
        {"result": "human_pathways.tsv", "accessions": ["TCGA-BRCA", "GO_Biological_Process_2023"]},
        {"result": "networks/human_healthy/", "accessions": ["TCGA-BRCA"]},
        {"result": "networks/human_cancer/", "accessions": ["TCGA-BRCA"]},
        {"result": "networks/mouse_tumor/", "accessions": ["GSE155577"]},
        {"result": "orthology_one_to_one.tsv", "accessions": [f"Ensembl Compara release {ensembl_release}"]},
        {"result": "cross_species_alignment.json", "accessions": ["TCGA-BRCA", "GSE155577", f"Ensembl Compara release {ensembl_release}"]},
        {"result": "ml_grouped_cv.json", "accessions": ["TCGA-BRCA"]},
        {"result": "report.html", "accessions": ["TCGA-BRCA", "GSE155577", "Ensembl Compara"]},
    ]
    run_summary = {
        "run_id": RUN_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "sources": {
            "human": {"repository": "GDC/TCGA", "accession": "TCGA-BRCA", "healthy_samples": len(healthy_samples), "cancer_samples": len(cancer_samples), "genes_after_qc": int(human_expr.shape[0])},
            "mouse": {"repository": "NCBI GEO", "accession": "GSE155577", "samples": len(mouse_samples), "healthy_samples": 0, "cancer_samples": len(mouse_samples), "excluded_cell_line_samples": int((~in_vivo_mouse).sum()), "genes_after_qc": int(mouse_expr.shape[0]), "excluded_unmapped_gene_ids": excluded_mouse_gene_ids, "values": "study-provided normalized expression; passed through"},
        },
        "stages": {
            "preprocessing": "completed",
            "human_deg": {"status": "completed", "significant_genes": significant_count, "method": "Welch t-test on log2(CPM+1); BH FDR"},
            "coexpression_networks": "completed",
            "module_detection": "completed",
            "orthology_mapping": {"status": "completed", "one_to_one_pairs": len(orthology), "ensembl_release": ensembl_release, "mapping_type": "ortholog_one2one"},
            "cross_species_network_alignment": alignment,
            "pathway_enrichment": pathway_status,
            "network_drift": "blocked: no mouse healthy mammary control cohort",
            "gene_loss_risk": "blocked: requires valid cross-species healthy/disease drift and suitable covariates",
            "ml_validation": ml_status,
            "external_validation": "blocked: no independent held-out cohort available",
        },
        "provenance": {
            "human_raw_expression": str(RAW_ROOT / "gdc" / "tcga_brca_real_expression.tsv.gz"),
            "human_metadata": str(RAW_ROOT / "gdc" / "tcga_brca_real_metadata.tsv"),
            "mouse_raw_expression": str(RAW_ROOT / "geo" / "GSE155577_expression.tsv.gz"),
            "mouse_metadata": str(RAW_ROOT / "geo" / "GSE155577_metadata.tsv"),
            "preprocessing_logs": {"human": human_log.to_text(), "mouse": mouse_log.to_text()},
            "network_parameters": {"correlation": "spearman", "threshold": 0.7, "fdr": 0.05, "top_n_genes": NETWORK_TOP_N},
            "primary_gene_identifier": "Ensembl Gene ID",
            "orthology_source": {"database": "Ensembl Compara/BioMart", "release": ensembl_release, "mapping_type": "ortholog_one2one"},
            "excluded_unmapped_gene_ids": {"human": excluded_human_gene_ids, "mouse": excluded_mouse_gene_ids},
            "gene_symbol_use": "Display/enrichment labels only, via explicit Ensembl BioMart identifier mapping.",
        },
        "ml": ml_summary,
        "result_provenance": result_provenance,
    }
    save_json(RUN_ROOT / "run_manifest.json", run_summary)
    save_json(RUN_ROOT / "result_provenance.json", {"run_id": RUN_ID, "results": result_provenance})
    report_rows = [f"<li><strong>{html.escape(name)}</strong>: {html.escape(str(state))}</li>" for name, state in run_summary["stages"].items()]
    (RUN_ROOT / "report.html").write_text(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>PathDrift real-data run</title></head>"
        f"<body><h1>PathDrift real-data run {html.escape(RUN_ID)}</h1><p>TCGA-BRCA: {len(healthy_samples)} normal, {len(cancer_samples)} tumor samples. "
        f"GSE155577: {len(mouse_samples)} tumor-derived samples; no healthy mouse controls.</p><ul>{''.join(report_rows)}</ul>"
        "<p>Network and internal ML results are exploratory. External validation and cross-species drift were not established.</p></body></html>",
        encoding="utf-8",
    )
    print(json.dumps({"run_id": RUN_ID, "run_dir": str(RUN_ROOT), "human_deg_significant": significant_count, "network_summary": network_summary, "stages": run_summary["stages"]}, indent=2, default=str))


if __name__ == "__main__":
    main()