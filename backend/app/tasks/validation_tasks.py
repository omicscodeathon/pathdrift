"""Background task for reproducible, saved scientific validation reports."""
import json
import os
import traceback

import networkx as nx
import pandas as pd
import structlog
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    BackgroundJob,
    DriftAnalysis,
    GeneNetwork,
    JobStatusEnum,
    MLExperiment,
    ModelMetric,
    OrthologyMapping,
    PathwayResult,
    SpeciesEnum,
)
from app.tasks.analysis_tasks import _update_job, get_sync_db
from app.tasks.celery_app import celery_app
from app.bio.validation import degree_preserving_network_test, node_label_permutation_test

logger = structlog.get_logger(__name__)


def _load_graph(path: str) -> nx.Graph:
    if not path or not os.path.isfile(path):
        raise ValueError("A saved network edge file is missing")
    edges = pd.read_parquet(path)
    if not {"gene1", "gene2"}.issubset(edges.columns):
        raise ValueError("A saved network edge file has an unexpected structure")
    graph = nx.Graph()
    for row in edges.itertuples(index=False):
        attributes = {}
        if "weight" in edges.columns and pd.notna(row.weight):
            attributes["weight"] = float(row.weight)
        graph.add_edge(str(row.gene1), str(row.gene2), **attributes)
    return graph


def _biological_evidence(db: Session, drift: DriftAnalysis) -> dict:
    pathway_results = (
        db.query(PathwayResult)
        .filter(
            PathwayResult.analysis_id == drift.analysis_id,
            PathwayResult.species == drift.species,
            PathwayResult.source == "drift",
            PathwayResult.status == JobStatusEnum.COMPLETED,
        )
        .order_by(PathwayResult.created_at.desc())
        .all()
    )
    evidence = []
    curated_term_gene_symbols = []
    for pathway in pathway_results:
        if not pathway.results_file_path or not os.path.isfile(pathway.results_file_path):
            continue
        frame = pd.read_parquet(pathway.results_file_path)
        if frame.empty:
            continue
        padj_column = next((column for column in ("padj", "Adjusted P-value", "adjusted_pvalue") if column in frame), None)
        term_column = next((column for column in ("term", "Term") if column in frame), None)
        if not term_column:
            continue
        if "significant" in frame:
            significant = frame[frame["significant"].fillna(False).astype(bool)]
        elif padj_column:
            significant = frame[pd.to_numeric(frame[padj_column], errors="coerce") <= pathway.fdr_threshold]
        else:
            significant = frame.iloc[0:0]
        if padj_column:
            significant = significant.assign(_padj=pd.to_numeric(significant[padj_column], errors="coerce"))
            significant = significant.sort_values("_padj", na_position="last")
        for row in significant.to_dict(orient="records"):
            genes = row.get("genes", row.get("Genes"))
            if isinstance(genes, str):
                genes = [gene.strip() for gene in genes.replace(";", ",").split(",") if gene.strip()]
            if isinstance(genes, list):
                curated_term_gene_symbols.append((str(row.get(term_column, "")), set(map(str, genes))))
        top_terms = []
        for row in significant.head(10).to_dict(orient="records"):
            term = row.get(term_column)
            if not term:
                continue
            genes = row.get("genes", row.get("Genes"))
            if isinstance(genes, str):
                genes = [gene.strip() for gene in genes.replace(";", ",").split(",") if gene.strip()]
            top_terms.append({
                "term": str(term),
                "adjusted_pvalue": float(row["_padj"]) if padj_column and pd.notna(row.get("_padj")) else None,
                "genes": genes if isinstance(genes, list) else [],
            })
        evidence.append({
            "pathway_result_id": pathway.id,
            "gene_set": pathway.gene_set,
            "source": pathway.source,
            "significant_term_count": int(len(significant)),
            "top_terms": top_terms,
        })

    all_symbols = {symbol for _, symbols in curated_term_gene_symbols for symbol in symbols}
    symbol_to_genes = {}
    if all_symbols:
        if drift.species == SpeciesEnum.HUMAN:
            mappings = db.query(OrthologyMapping.human_ensembl_id, OrthologyMapping.human_symbol).filter(
                OrthologyMapping.human_symbol.in_(all_symbols)
            ).all()
        else:
            mappings = db.query(OrthologyMapping.mouse_ensembl_id, OrthologyMapping.mouse_symbol).filter(
                OrthologyMapping.mouse_symbol.in_(all_symbols)
            ).all()
        for gene_id, symbol in mappings:
            symbol_to_genes.setdefault(str(symbol), set()).add(str(gene_id))

    term_gene_ids = [
        (term, {gene_id for symbol in symbols for gene_id in symbol_to_genes.get(symbol, set())})
        for term, symbols in curated_term_gene_symbols
    ]
    relationship_preservation = {
        "available": False,
        "method": "co-membership of conserved co-expression edges in significant curated pathway gene sets",
        "relationship_type": "pathway co-membership; not a physical protein interaction",
        "conserved_edges_assessed": 0,
        "pathway_supported_conserved_edges": 0,
        "fraction_supported": None,
        "examples": [],
        "reason": "No mapped significant drift-pathway genes and conserved drift edges are available.",
    }
    if term_gene_ids and drift.edge_drift_file_path and os.path.isfile(drift.edge_drift_file_path):
        edge_frame = pd.read_parquet(drift.edge_drift_file_path)
        if {"gene1", "gene2", "type"}.issubset(edge_frame.columns):
            conserved_edges = edge_frame[edge_frame["type"] == "conserved"]
            supported_edges = []
            for row in conserved_edges.itertuples(index=False):
                gene1, gene2 = str(row.gene1), str(row.gene2)
                matching_terms = [term for term, genes in term_gene_ids if gene1 in genes and gene2 in genes]
                if matching_terms:
                    supported_edges.append({"gene1": gene1, "gene2": gene2, "pathways": matching_terms[:3]})
            relationship_preservation = {
                "available": True,
                "method": "co-membership of conserved co-expression edges in significant curated pathway gene sets",
                "relationship_type": "pathway co-membership; not a physical protein interaction",
                "conserved_edges_assessed": int(len(conserved_edges)),
                "pathway_supported_conserved_edges": len(supported_edges),
                "fraction_supported": len(supported_edges) / len(conserved_edges) if len(conserved_edges) else 0.0,
                "examples": supported_edges[:10],
                "reason": None,
            }

    return {
        "available": bool(evidence),
        "method": "over-representation against the recorded curated pathway library",
        "evidence_independent": False,
        "limitation": "Pathway evidence uses results from this analysis and is biological support, not independent validation.",
        "pathway_results": evidence,
        "relationship_preservation": relationship_preservation,
        "reason": None if evidence else "No completed pathway results for this analysis and species.",
    }


def _ml_evidence(db: Session, analysis_id: str) -> dict:
    experiments = (
        db.query(MLExperiment)
        .filter(MLExperiment.analysis_id == analysis_id, MLExperiment.status == JobStatusEnum.COMPLETED)
        .order_by(MLExperiment.created_at.desc())
        .all()
    )
    rows = []
    for experiment in experiments:
        metrics = db.query(ModelMetric).filter(ModelMetric.experiment_id == experiment.id).all()
        by_split = {}
        for metric in metrics:
            by_split[metric.split] = {
                "auroc": metric.auroc,
                "auprc": metric.auprc,
                "accuracy": metric.accuracy,
                "f1": metric.f1,
                "auroc_ci_lower": metric.auroc_ci_lower,
                "auroc_ci_upper": metric.auroc_ci_upper,
            }
        rows.append({
            "experiment_id": experiment.id,
            "name": experiment.name,
            "model_type": experiment.model_type.value,
            "experiment_type": experiment.experiment_type.value,
            "cv_folds": experiment.cv_folds,
            "cross_validation": by_split.get("cv"),
            "independent_test": by_split.get("external_val"),
            "external_dataset_configured": bool(experiment.validation_dataset_id),
            "leakage_warnings": experiment.leakage_warnings or [],
        })
    return {
        "available": bool(rows),
        "method": "saved stratified cross-validation and held-out dataset metrics from the ML pipeline",
        "experiments": rows,
        "reason": None if rows else "No completed ML experiments are saved for this analysis.",
    }


@celery_app.task(bind=True, name="app.tasks.validation_tasks.run_scientific_validation")
def run_scientific_validation(
    self,
    job_id: str,
    drift_analysis_id: str,
    permutations: int = 199,
    random_seed: int = 42,
):
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 5, "Loading completed drift and network results")
        drift = db.query(DriftAnalysis).filter(DriftAnalysis.id == drift_analysis_id).first()
        if not drift or drift.status != JobStatusEnum.COMPLETED:
            raise ValueError("A completed drift analysis is required")
        healthy = db.query(GeneNetwork).filter(GeneNetwork.id == drift.healthy_network_id).first()
        disease = db.query(GeneNetwork).filter(GeneNetwork.id == drift.disease_network_id).first()
        if not healthy or not disease:
            raise ValueError("The drift analysis network records are missing")

        healthy_graph = _load_graph(healthy.adjacency_file_path)
        disease_graph = _load_graph(disease.adjacency_file_path)
        _update_job(db, job_id, JobStatusEnum.RUNNING, 20, "Running gene-label permutation test")
        statistical = node_label_permutation_test(
            healthy_graph, disease_graph, permutations=permutations, random_seed=random_seed,
        )
        statistical["saved_global_drift_score"] = drift.global_drift_score

        _update_job(db, job_id, JobStatusEnum.RUNNING, 55, "Running degree-preserving network null model")
        network = degree_preserving_network_test(
            healthy_graph, disease_graph, permutations=min(permutations, 99), random_seed=random_seed,
        )

        _update_job(db, job_id, JobStatusEnum.RUNNING, 80, "Collecting pathway and ML evidence")
        result = {
            "drift_analysis_id": drift.id,
            "analysis_id": drift.analysis_id,
            "species": drift.species.value,
            "created_at": drift.created_at.isoformat() if drift.created_at else None,
            "biological": _biological_evidence(db, drift),
            "statistical": statistical,
            "network": {
                **network,
                "healthy_network_id": healthy.id,
                "disease_network_id": disease.id,
                "healthy_edges": healthy_graph.number_of_edges(),
                "disease_edges": disease_graph.number_of_edges(),
            },
            "machine_learning": _ml_evidence(db, drift.analysis_id),
        }

        output_dir = os.path.join(settings.REPORT_DIR, "validation")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{job_id}.json")
        temporary_path = f"{output_path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as output_file:
            json.dump(result, output_file, allow_nan=False)
        os.replace(temporary_path, output_path)

        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        if job:
            job.result_ref = output_path
            db.commit()
        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100, "Scientific validation completed")
        return {"status": "completed", "result_ref": output_path}
    except Exception as error:
        logger.error("scientific_validation_failed", error=str(error), traceback=traceback.format_exc())
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Validation failed", str(error))
        raise
    finally:
        db.close()