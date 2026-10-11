"""
Celery Tasks: Bioinformatics analysis pipeline tasks.

All tasks:
  - Update BackgroundJob status in database
  - Log progress
  - Handle errors gracefully
  - Save results to disk (Parquet) and record file paths in DB
"""
import os
import re
import traceback
import pandas as pd
from datetime import datetime, timezone
from celery import Task
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import structlog

from app.tasks.celery_app import celery_app
from app.core.config import settings
from app.models import (
    BackgroundJob, PreprocessingJob, DEGResult, GeneNetwork, DriftAnalysis,
    CrossSpeciesAnalysis, PathwayResult, JobStatusEnum, SpeciesEnum, DiseaseStateEnum,
)

logger = structlog.get_logger(__name__)


def get_sync_db() -> Session:
    """Synchronous session for Celery tasks (psycopg2)."""
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _update_job(db: Session, job_id: str, status: str, progress: int = 0, msg: str = "", error: str = ""):
    job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
    if job:
        job.status = status
        job.progress = progress
        job.progress_message = msg
        if status == JobStatusEnum.RUNNING and not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        if status in (JobStatusEnum.COMPLETED, JobStatusEnum.FAILED):
            job.completed_at = datetime.now(timezone.utc)
        if error:
            job.error_message = error
        db.commit()


# ── Preprocessing Task ────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.analysis_tasks.run_preprocessing")
def run_preprocessing(self, job_id: str, preprocessing_job_id: str):
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 5, "Loading dataset")

        pp_job = db.query(PreprocessingJob).filter(PreprocessingJob.id == preprocessing_job_id).first()
        if not pp_job:
            raise ValueError(f"PreprocessingJob {preprocessing_job_id} not found")

        from app.models import Dataset
        dataset = db.query(Dataset).filter(Dataset.id == pp_job.dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {pp_job.dataset_id} not found")

        # Load expression matrix
        _update_job(db, job_id, JobStatusEnum.RUNNING, 15, "Loading expression matrix")
        expr_df = _load_expression(dataset.expression_file_path)

        # Load metadata
        metadata_df = None
        if dataset.metadata_file_path and os.path.exists(dataset.metadata_file_path):
            sep = "\t" if dataset.metadata_file_path.endswith((".tsv", ".txt")) else ","
            metadata_df = pd.read_csv(dataset.metadata_file_path, sep=sep)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 30, "Running preprocessing pipeline")

        from app.bio.preprocessing import PreprocessingPipeline
        pipeline = PreprocessingPipeline(
            normalization_method=pp_job.normalization_method.value,
            low_expr_threshold=pp_job.low_expr_threshold,
            low_expr_min_samples=pp_job.low_expr_min_samples,
            min_gene_variance=pp_job.min_gene_variance,
            remove_duplicates=pp_job.remove_duplicates,
            impute_missing=pp_job.impute_missing,
            batch_correct=pp_job.batch_correct,
            batch_correction_method=pp_job.batch_correction_method,
            outlier_detection=pp_job.outlier_detection,
        )

        species_str = dataset.species.value if hasattr(dataset.species, "value") else str(dataset.species)
        cleaned_df, log = pipeline.run(expr_df, metadata_df, dataset.id, species_str)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 80, "Saving results")

        # Save preprocessed matrix as parquet
        output_dir = os.path.join(settings.UPLOAD_DIR, dataset.id, "preprocessed")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{preprocessing_job_id}.parquet")
        cleaned_df.to_parquet(output_path)

        from app.services.data_acquisition.dataset_manager import mirror_to_frontend_visible_store
        mirror_to_frontend_visible_store(output_path)
        if dataset.metadata_file_path and os.path.exists(dataset.metadata_file_path):
            mirror_to_frontend_visible_store(dataset.metadata_file_path)

        # Update job record
        pp_job.n_genes_before = log.n_genes_before
        pp_job.n_genes_after = log.n_genes_after
        pp_job.n_samples_before = log.n_samples_before
        pp_job.n_samples_after = log.n_samples_after
        pp_job.outlier_samples = log.outlier_samples
        pp_job.processing_log = log.to_text()
        pp_job.output_file_path = output_path
        pp_job.status = JobStatusEnum.COMPLETED
        db.commit()

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100, "Preprocessing complete")
        return {"status": "completed", "output_path": output_path}

    except Exception as e:
        err_msg = str(e)
        tb = traceback.format_exc()
        logger.error("preprocessing_task_failed", error=err_msg, job_id=job_id)
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", err_msg)
        # Update preprocessing job status
        pp_job = db.query(PreprocessingJob).filter(PreprocessingJob.id == preprocessing_job_id).first()
        if pp_job:
            pp_job.status = JobStatusEnum.FAILED
            pp_job.processing_log = f"FAILED: {err_msg}\n\n{tb}"
            db.commit()
        raise
    finally:
        db.close()


# ── DEG Task ──────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.analysis_tasks.run_deg")
def run_deg(self, job_id: str, deg_result_id: str):
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 5, "Loading data")

        deg_result = db.query(DEGResult).filter(DEGResult.id == deg_result_id).first()
        if not deg_result:
            raise ValueError(f"DEGResult {deg_result_id} not found")

        expr_df, metadata_df = _load_analysis_data(db, deg_result.dataset_id, deg_result.preprocessing_job_id)
        healthy_samples, disease_samples = _split_samples_by_state(metadata_df, expr_df)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 40, "Running DEG analysis")

        from app.bio.deg import DEGAnalyzer
        analyzer = DEGAnalyzer(
            method=deg_result.method,
            fdr_threshold=deg_result.fdr_threshold,
            lfc_threshold=deg_result.lfc_threshold,
        )
        results_df = analyzer.run(expr_df, healthy_samples, disease_samples)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 85, "Saving results")

        output_dir = os.path.join(settings.UPLOAD_DIR, deg_result.dataset_id, "deg")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{deg_result_id}.parquet")
        results_df.to_parquet(output_path)

        n_sig = int(results_df["significant"].sum())
        deg_result.n_deg_total = n_sig
        deg_result.n_deg_up = int((results_df["direction"] == "up").sum())
        deg_result.n_deg_down = int((results_df["direction"] == "down").sum())
        deg_result.results_file_path = output_path
        deg_result.status = JobStatusEnum.COMPLETED
        db.commit()

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100, f"DEG analysis complete: {n_sig} significant genes")
        return {"status": "completed", "n_deg": n_sig}

    except Exception as e:
        logger.error("deg_task_failed", error=str(e))
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", str(e))
        deg_r = db.query(DEGResult).filter(DEGResult.id == deg_result_id).first()
        if deg_r:
            deg_r.status = JobStatusEnum.FAILED
            db.commit()
        raise
    finally:
        db.close()


# ── Network Construction Task ──────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.analysis_tasks.run_network_construction")
def run_network_construction(self, job_id: str, network_id: str):
    import networkx as nx
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 5, "Loading data")

        network = db.query(GeneNetwork).filter(GeneNetwork.id == network_id).first()
        if not network:
            raise ValueError(f"GeneNetwork {network_id} not found")

        expr_df, metadata_df = _load_network_analysis_data(db, network)
        # Select samples for this network's state
        state_val = network.disease_state.value if hasattr(network.disease_state, "value") else str(network.disease_state)
        sample_ids = _get_samples_for_state(metadata_df, state_val)
        sample_ids = [s for s in sample_ids if s in expr_df.columns]

        if len(sample_ids) < 5:
            raise ValueError(
                f"Insufficient samples ({len(sample_ids)}) for state '{state_val}'. "
                "Minimum 5 required for network construction."
            )

        _update_job(db, job_id, JobStatusEnum.RUNNING, 20, f"Building network for {state_val} ({len(sample_ids)} samples)")

        from app.bio.network import NetworkConstructor, compute_network_statistics
        constructor = NetworkConstructor(
            correlation_method=network.correlation_method.value,
            correlation_threshold=network.correlation_threshold,
            fdr_threshold=network.fdr_threshold,
            top_n_genes=network.top_n_genes,
            min_gene_variance=network.min_gene_variance,
        )

        G, node_features = constructor.build(expr_df, sample_ids)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 80, "Saving network")

        output_dir = os.path.join(settings.UPLOAD_DIR, network.dataset_id, "networks", network_id)
        os.makedirs(output_dir, exist_ok=True)

        # Save adjacency as edgelist
        adj_path = os.path.join(output_dir, "adjacency.parquet")
        edge_rows = [
            {"gene1": u, "gene2": v, "weight": d["weight"], "correlation": d.get("correlation", d["weight"])}
            for u, v, d in G.edges(data=True)
        ]
        pd.DataFrame(edge_rows).to_parquet(adj_path)

        # Save node features
        node_path = os.path.join(output_dir, "node_features.parquet")
        node_features.reset_index().to_parquet(node_path)

        stats = compute_network_statistics(G)
        network.n_nodes = stats["n_nodes"]
        network.n_edges = stats["n_edges"]
        network.density = stats["density"]
        network.avg_clustering_coefficient = stats["avg_clustering"]
        network.avg_degree = stats["avg_degree"]
        network.adjacency_file_path = adj_path
        network.node_features_file_path = node_path
        network.status = JobStatusEnum.COMPLETED
        db.commit()

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100,
                    f"Network built: {stats['n_nodes']} nodes, {stats['n_edges']} edges")
        return {"status": "completed", "n_nodes": stats["n_nodes"], "n_edges": stats["n_edges"]}

    except Exception as e:
        logger.error("network_task_failed", error=str(e))
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", str(e))
        net = db.query(GeneNetwork).filter(GeneNetwork.id == network_id).first()
        if net:
            net.status = JobStatusEnum.FAILED
            db.commit()
        raise
    finally:
        db.close()


# ── Drift Detection Task ───────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.analysis_tasks.run_drift_detection")
def run_drift_detection(self, job_id: str, drift_analysis_id: str):
    import networkx as nx
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 5, "Loading networks")

        drift = db.query(DriftAnalysis).filter(DriftAnalysis.id == drift_analysis_id).first()
        if not drift:
            raise ValueError(f"DriftAnalysis {drift_analysis_id} not found")

        h_net = db.query(GeneNetwork).filter(GeneNetwork.id == drift.healthy_network_id).first()
        d_net = db.query(GeneNetwork).filter(GeneNetwork.id == drift.disease_network_id).first()

        if not h_net or not d_net:
            raise ValueError("One or both networks not found")
        if h_net.status != JobStatusEnum.COMPLETED or d_net.status != JobStatusEnum.COMPLETED:
            raise ValueError("Both networks must be in COMPLETED state before drift analysis")

        # Load graphs from saved edge files
        H = _load_network_from_file(h_net.adjacency_file_path)
        D = _load_network_from_file(d_net.adjacency_file_path)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 30, "Computing network drift")

        from app.bio.drift import DriftDetector
        detector = DriftDetector()
        results = detector.compute(H, D)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 80, "Saving drift results")

        output_dir = os.path.join(settings.UPLOAD_DIR, "drift", drift_analysis_id)
        os.makedirs(output_dir, exist_ok=True)

        edge_path = os.path.join(output_dir, "edge_drift.parquet")
        node_path = os.path.join(output_dir, "node_drift.parquet")
        module_path = os.path.join(output_dir, "module_drift.parquet")

        results["edge_drift"].to_parquet(edge_path)
        results["node_drift"].to_parquet(node_path)
        results["module_drift"].to_parquet(module_path)

        gstats = results["global_stats"]
        drift.n_conserved_edges = gstats["n_conserved"]
        drift.n_gained_edges = gstats["n_gained"]
        drift.n_lost_edges = gstats["n_lost"]
        drift.global_drift_score = gstats["global_drift_score"]
        drift.node_drift_file_path = node_path
        drift.edge_drift_file_path = edge_path
        drift.module_drift_file_path = module_path
        drift.status = JobStatusEnum.COMPLETED
        db.commit()

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100,
                    f"Drift analysis complete. Score: {gstats['global_drift_score']:.4f}")
        return {"status": "completed", "global_drift_score": gstats["global_drift_score"]}

    except Exception as e:
        logger.error("drift_task_failed", error=str(e))
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", str(e))
        d = db.query(DriftAnalysis).filter(DriftAnalysis.id == drift_analysis_id).first()
        if d:
            d.status = JobStatusEnum.FAILED
            db.commit()
        raise
    finally:
        db.close()


# ── Cross-Species Task ─────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.analysis_tasks.run_cross_species")
def run_cross_species(self, job_id: str, cs_analysis_id: str):
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 5, "Loading drift results")

        cs = db.query(CrossSpeciesAnalysis).filter(CrossSpeciesAnalysis.id == cs_analysis_id).first()
        if not cs:
            raise ValueError(f"CrossSpeciesAnalysis {cs_analysis_id} not found")

        h_drift = db.query(DriftAnalysis).filter(DriftAnalysis.id == cs.human_drift_id).first()
        m_drift = db.query(DriftAnalysis).filter(DriftAnalysis.id == cs.mouse_drift_id).first()

        if not h_drift or not m_drift:
            raise ValueError("Human or mouse drift analysis not found")

        human_node_drift = pd.read_parquet(h_drift.node_drift_file_path)
        mouse_node_drift = pd.read_parquet(m_drift.node_drift_file_path)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 30, "Loading orthology mappings")

        from app.models import OrthologyMapping
        mappings = db.query(OrthologyMapping).filter(
            OrthologyMapping.orthology_type == "ortholog_one2one"
        ).all()
        if not mappings:
            raise ValueError(
                "No orthology mappings found in database. "
                "Run scripts/seed_orthology.py to populate orthology data."
            )
        mapping_df = pd.DataFrame(
            [{"human_ensembl_id": m.human_ensembl_id, "mouse_ensembl_id": m.mouse_ensembl_id,
                            "human_symbol": m.human_symbol, "mouse_symbol": m.mouse_symbol,
                              "orthology_type": m.orthology_type,
                              "ensembl_release": int(re.search(r"release\s+(\d+)", m.source_version or "", re.IGNORECASE).group(1))
                              if re.search(r"release\s+(\d+)", m.source_version or "", re.IGNORECASE) else None}
             for m in mappings]
        )

        _update_job(db, job_id, JobStatusEnum.RUNNING, 50, "Comparing drift across species")

        from app.bio.cross_species import CrossSpeciesComparator
        comparator = CrossSpeciesComparator()
        result = comparator.compare(human_node_drift, mouse_node_drift, mapping_df)

        _update_job(db, job_id, JobStatusEnum.RUNNING, 85, "Saving results")

        output_dir = os.path.join(settings.UPLOAD_DIR, "cross_species", cs_analysis_id)
        os.makedirs(output_dir, exist_ok=True)
        comparison_path = os.path.join(output_dir, "comparison.parquet")
        result["comparison_df"].to_parquet(comparison_path)

        summary = result["summary"]
        cs.n_orthologous_genes = summary["n_orthologous_genes"]
        cs.n_conserved_drift = summary["n_conserved"]
        cs.n_human_specific = summary["n_human_specific"]
        cs.n_mouse_specific = summary["n_mouse_specific"]
        cs.n_divergent = summary["n_divergent"]
        cs.conservation_score = summary["conservation_score"]
        cs.comparison_file_path = comparison_path
        cs.status = JobStatusEnum.COMPLETED
        db.commit()

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100,
                    f"Cross-species analysis done. Conservation score: {summary['conservation_score']:.3f}")
        return {"status": "completed", "conservation_score": summary["conservation_score"]}

    except Exception as e:
        logger.error("cross_species_task_failed", error=str(e))
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", str(e))
        c = db.query(CrossSpeciesAnalysis).filter(CrossSpeciesAnalysis.id == cs_analysis_id).first()
        if c:
            c.status = JobStatusEnum.FAILED
            db.commit()
        raise
    finally:
        db.close()


# ── Pathway Task ───────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.analysis_tasks.run_pathway_analysis")
def run_pathway_analysis(self, job_id: str, pathway_result_id: str, gene_list: list, background_genes: list):
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 10, "Running pathway enrichment")

        pw = db.query(PathwayResult).filter(PathwayResult.id == pathway_result_id).first()
        if not pw:
            raise ValueError(f"PathwayResult {pathway_result_id} not found")

        from app.bio.pathways import PathwayAnalyzer
        species_val = pw.species.value if hasattr(pw.species, "value") else str(pw.species)
        analyzer = PathwayAnalyzer(species=species_val, fdr_threshold=pw.fdr_threshold)
        results_df = analyzer.run_ora(gene_list, pw.gene_set, background_genes or None)

        output_dir = os.path.join(settings.UPLOAD_DIR, "pathways", pathway_result_id)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.parquet")
        results_df.to_parquet(output_path)

        n_sig = int(results_df["significant"].sum()) if "significant" in results_df.columns else 0
        pw.n_significant = n_sig
        pw.results_file_path = output_path
        pw.status = JobStatusEnum.COMPLETED
        db.commit()

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100, f"Pathway analysis done: {n_sig} significant pathways")
        return {"status": "completed", "n_significant": n_sig}

    except Exception as e:
        logger.error("pathway_task_failed", error=str(e))
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", str(e))
        p = db.query(PathwayResult).filter(PathwayResult.id == pathway_result_id).first()
        if p:
            p.status = JobStatusEnum.FAILED
            db.commit()
        raise
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_expression(file_path: str) -> pd.DataFrame:
    if file_path.endswith(".parquet"):
        return pd.read_parquet(file_path)
    sep = "\t" if file_path.endswith((".tsv", ".txt", ".tsv.gz", ".txt.gz")) else ","
    comp = "gzip" if ".gz" in file_path else None
    return pd.read_csv(file_path, sep=sep, index_col=0, compression=comp, low_memory=False)


def _load_analysis_data(db: Session, dataset_id: str, preprocessing_job_id: str):
    from app.models import Dataset, PreprocessingJob
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()

    if preprocessing_job_id:
        pp = db.query(PreprocessingJob).filter(PreprocessingJob.id == preprocessing_job_id).first()
        if pp and pp.output_file_path and os.path.exists(pp.output_file_path):
            expr_df = pd.read_parquet(pp.output_file_path)
        else:
            expr_df = _load_expression(dataset.expression_file_path)
    else:
        expr_df = _load_expression(dataset.expression_file_path)

    metadata_df = None
    if dataset.metadata_file_path and os.path.exists(dataset.metadata_file_path):
        sep = "\t" if dataset.metadata_file_path.endswith((".tsv", ".txt")) else ","
        metadata_df = pd.read_csv(dataset.metadata_file_path, sep=sep)

    return expr_df, metadata_df


def _load_network_analysis_data(db: Session, network: GeneNetwork):
    return _load_analysis_data(
        db,
        network.dataset_id,
        network.preprocessing_job_id,
    )


def _split_samples_by_state(metadata_df, expr_df):
    if metadata_df is None:
        raise ValueError("Metadata required to identify healthy vs disease samples")
    meta = metadata_df.copy()
    meta.columns = meta.columns.str.lower()
    meta["sample_id"] = meta["sample_id"].astype(str)
    meta["disease_state_lower"] = meta["disease_state"].str.lower()

    healthy = meta[
        meta["disease_state_lower"].isin(["healthy", "normal", "control"])
    ]["sample_id"].tolist()
    disease = meta[
        ~meta["disease_state_lower"].isin(["healthy", "normal", "control"])
    ]["sample_id"].tolist()

    healthy = [s for s in healthy if s in expr_df.columns]
    disease = [s for s in disease if s in expr_df.columns]

    if not healthy:
        raise ValueError("No healthy/normal samples found in metadata")
    if not disease:
        raise ValueError("No cancer/disease samples found in metadata")

    return healthy, disease


def _get_samples_for_state(metadata_df, state_val: str) -> list:
    if metadata_df is None:
        return []
    meta = metadata_df.copy()
    meta.columns = meta.columns.str.lower()
    meta["sample_id"] = meta["sample_id"].astype(str)
    state_map = {
        "healthy": ["healthy", "normal", "control"],
        "cancer": ["cancer", "tumor", "disease", "breast cancer"],
        "early_cancer": ["stage i", "stage_i", "early"],
    }
    aliases = state_map.get(state_val, [state_val.lower()])
    return meta[meta["disease_state"].str.lower().isin(aliases)]["sample_id"].tolist()


def _load_network_from_file(file_path: str):
    import networkx as nx
    edges_df = pd.read_parquet(file_path)
    G = nx.Graph()
    for _, row in edges_df.iterrows():
        G.add_edge(row["gene1"], row["gene2"], weight=row["weight"], correlation=row.get("correlation", row["weight"]))
    return G
