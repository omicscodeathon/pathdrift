"""Network construction routes."""
import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select
import pandas as pd
from pydantic import BaseModel

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import (
    Analysis, BackgroundJob, Dataset, DriftAnalysis, GeneNetwork, PreprocessingJob,
    JobStatusEnum, OrthologyMapping, Project, SpeciesEnum, User,
)
from app.schemas.schemas import NetworkConfig, NetworkOut, JobOut

router = APIRouter()


class ModuleEnrichmentRequest(BaseModel):
    gene_set: str


@router.post("/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def build_network(
    config: NetworkConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Analysis)
        .join(Project, Analysis.project_id == Project.id)
        .where(Analysis.id == config.analysis_id, Project.owner_id == current_user.id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    dataset_result = await db.execute(
        select(Dataset).where(
            Dataset.id == config.dataset_id,
            Dataset.project_id == analysis.project_id,
            Dataset.owner_id == current_user.id,
        )
    )
    dataset = dataset_result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found or not part of this project")
    if dataset.species != config.species:
        raise HTTPException(status_code=400, detail="Network species must match the selected dataset")

    if config.preprocessing_job_id:
        preprocessing_result = await db.execute(
            select(PreprocessingJob).where(
                PreprocessingJob.id == config.preprocessing_job_id,
                PreprocessingJob.analysis_id == config.analysis_id,
                PreprocessingJob.dataset_id == config.dataset_id,
                PreprocessingJob.status == JobStatusEnum.COMPLETED,
            )
        )
        if preprocessing_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=400,
                detail="Preprocessing job must be completed and belong to the selected analysis and dataset",
            )

    network = GeneNetwork(
        analysis_id=config.analysis_id,
        dataset_id=config.dataset_id,
        preprocessing_job_id=config.preprocessing_job_id,
        name=config.name,
        species=config.species,
        disease_state=config.disease_state,
        correlation_method=config.correlation_method,
        correlation_threshold=config.correlation_threshold,
        fdr_threshold=config.fdr_threshold,
        top_n_genes=config.top_n_genes,
        min_gene_variance=config.min_gene_variance,
    )
    db.add(network)
    await db.flush()

    bg_job = BackgroundJob(analysis_id=config.analysis_id, task_name="run_network_construction")
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)

    from app.tasks.analysis_tasks import run_network_construction
    task = run_network_construction.apply_async(args=[bg_job.id, network.id], queue="analysis")
    bg_job.celery_task_id = task.id
    bg_job.result_ref = network.id
    await db.flush()
    return bg_job


@router.get("/project/{project_id}")
async def list_project_networks(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project_result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(GeneNetwork)
        .join(Analysis, Analysis.id == GeneNetwork.analysis_id)
        .where(Analysis.project_id == project_id)
        .order_by(GeneNetwork.created_at.desc())
    )
    networks = result.scalars().all()
    summaries = []
    for network in networks:
        module_count = None
        path = network.node_features_file_path
        if path and os.path.isfile(path):
            try:
                features = await asyncio.to_thread(pd.read_parquet, path)
                if "module" in features.columns:
                    module_count = int(features["module"].dropna().nunique())
            except (OSError, ValueError, ImportError):
                module_count = None
        summaries.append({
            "id": network.id,
            "analysis_id": network.analysis_id,
            "dataset_id": network.dataset_id,
            "name": network.name,
            "species": network.species.value,
            "disease_state": network.disease_state.value,
            "network_type": "co-expression",
            "correlation_method": network.correlation_method.value,
            "correlation_threshold": network.correlation_threshold,
            "n_nodes": network.n_nodes,
            "n_edges": network.n_edges,
            "module_count": module_count,
            "density": network.density,
            "avg_degree": network.avg_degree,
            "status": network.status.value,
            "created_at": network.created_at,
        })
    return summaries


async def _get_owned_network(network_id: str, current_user: User, db: AsyncSession) -> GeneNetwork:
    result = await db.execute(
        select(GeneNetwork)
        .join(Analysis, Analysis.id == GeneNetwork.analysis_id)
        .join(Project, Project.id == Analysis.project_id)
        .where(GeneNetwork.id == network_id, Project.owner_id == current_user.id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.get("/{network_id}", response_model=NetworkOut)
async def get_network(
    network_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_owned_network(network_id, current_user, db)


@router.get("/{network_id}/edges")
async def get_network_edges(
    network_id: str,
    limit: int = 1000,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    network = await _get_owned_network(network_id, current_user, db)
    if not network.adjacency_file_path or not os.path.isfile(network.adjacency_file_path):
        raise HTTPException(status_code=404, detail="Network edges not available")
    edges_df = await asyncio.to_thread(pd.read_parquet, network.adjacency_file_path)
    if "weight" in edges_df.columns:
        edges_df = edges_df.sort_values("weight", ascending=False)
    return edges_df.head(limit).to_dict(orient="records")


@router.get("/{network_id}/nodes")
async def get_network_nodes(
    network_id: str,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    network = await _get_owned_network(network_id, current_user, db)
    if not network.node_features_file_path or not os.path.isfile(network.node_features_file_path):
        raise HTTPException(status_code=404, detail="Node features not available")
    nodes_df = await asyncio.to_thread(pd.read_parquet, network.node_features_file_path)
    if "degree" in nodes_df.columns:
        nodes_df = nodes_df.sort_values("degree", ascending=False)
    return nodes_df.head(max(1, min(limit, 2000))).to_dict(orient="records")


@router.get("/{network_id}/genes/{gene_id}")
async def get_network_gene_details(
    network_id: str,
    gene_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    network = await _get_owned_network(network_id, current_user, db)
    if not network.node_features_file_path or not os.path.isfile(network.node_features_file_path):
        raise HTTPException(status_code=404, detail="Network node features not available")
    if not network.adjacency_file_path or not os.path.isfile(network.adjacency_file_path):
        raise HTTPException(status_code=404, detail="Network edges not available")

    dataset_result = await db.execute(
        select(Dataset).where(Dataset.id == network.dataset_id, Dataset.owner_id == current_user.id)
    )
    dataset = dataset_result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Network dataset not found")

    nodes_df, edges_df = await asyncio.gather(
        asyncio.to_thread(pd.read_parquet, network.node_features_file_path),
        asyncio.to_thread(pd.read_parquet, network.adjacency_file_path),
    )
    if "gene_id" not in nodes_df.columns:
        nodes_df = nodes_df.reset_index()
    selected_rows = nodes_df[nodes_df["gene_id"].astype(str) == gene_id]
    if selected_rows.empty:
        raise HTTPException(status_code=404, detail="Gene not found in this network")
    node = selected_rows.iloc[0]
    degree = int(node.get("degree", 0) or 0)
    max_degree = int(pd.to_numeric(nodes_df.get("degree", pd.Series(dtype=float)), errors="coerce").max() or 0)
    hub_score = degree / max_degree if max_degree else 0.0

    expression_value = None
    expression_values = {}
    if dataset.expression_file_path and os.path.isfile(dataset.expression_file_path):
        from app.services.dataset_service import DatasetService
        try:
            expression_df = await asyncio.to_thread(DatasetService._load_expression_matrix, dataset.expression_file_path)
            numeric_expression = expression_df.apply(pd.to_numeric, errors="coerce")
            expression_values = numeric_expression.mean(axis=1).dropna().to_dict()
            if gene_id in expression_values:
                expression_value = float(expression_values[gene_id])
        except (OSError, ValueError, pd.errors.ParserError):
            expression_values = {}

    orthology_query = (
        select(OrthologyMapping)
        .where(OrthologyMapping.human_ensembl_id == gene_id)
        if network.species.value == "human"
        else select(OrthologyMapping).where(OrthologyMapping.mouse_ensembl_id == gene_id)
    )
    orthology_result = await db.execute(orthology_query.limit(1))
    mapping = orthology_result.scalar_one_or_none()
    ortholog = None
    if mapping:
        ortholog = {
            "gene_id": mapping.mouse_ensembl_id if network.species.value == "human" else mapping.human_ensembl_id,
            "symbol": mapping.mouse_symbol if network.species.value == "human" else mapping.human_symbol,
        }

    drift_result = await db.execute(
        select(DriftAnalysis)
        .where(
            or_(DriftAnalysis.healthy_network_id == network_id, DriftAnalysis.disease_network_id == network_id),
            DriftAnalysis.status == JobStatusEnum.COMPLETED,
        )
        .order_by(DriftAnalysis.created_at.desc())
        .limit(1)
    )
    drift = drift_result.scalar_one_or_none()
    drift_score = None
    if drift and drift.node_drift_file_path and os.path.isfile(drift.node_drift_file_path):
        try:
            drift_df = await asyncio.to_thread(pd.read_parquet, drift.node_drift_file_path)
            if "gene_id" in drift_df.columns:
                gene_drift = drift_df[drift_df["gene_id"].astype(str) == gene_id]
                if not gene_drift.empty and "node_drift_score" in gene_drift.columns:
                    drift_score = float(gene_drift.iloc[0]["node_drift_score"])
        except (OSError, ValueError, ImportError):
            drift_score = None

    interactions = []
    if {"gene1", "gene2"}.issubset(edges_df.columns):
        interactions = list(edges_df[["gene1", "gene2"]].dropna().astype(str).itertuples(index=False, name=None))
    gene_loss_risk = None
    if expression_value is not None and "gene_id" in nodes_df.columns:
        from app.bio.gene_loss import GeneLossRiskModel
        genes = nodes_df["gene_id"].astype(str).tolist()
        model = GeneLossRiskModel().fit(genes, expression_values, interactions)
        score = model.predict_risk([gene_id], expression_values, interactions).get(gene_id)
        if score:
            gene_loss_risk = float(score["probability"])

    return {
        "gene_id": gene_id,
        "expression_mean": expression_value,
        "degree": degree,
        "module": None if pd.isna(node.get("module")) else str(node.get("module")),
        "hub_score": hub_score,
        "ppi_degree": None,
        "ortholog": ortholog,
        "drift_score": drift_score,
        "gene_loss_risk": gene_loss_risk,
        "gene_loss_basis": "expression and co-expression network" if gene_loss_risk is not None else None,
    }


@router.get("/{network_id}/modules")
async def list_network_modules(
    network_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    network = await _get_owned_network(network_id, current_user, db)
    if network.status != JobStatusEnum.COMPLETED or not network.node_features_file_path:
        raise HTTPException(status_code=409, detail="Completed network module assignments are not available")
    if not os.path.isfile(network.node_features_file_path):
        raise HTTPException(status_code=404, detail="Network node features not found")

    try:
        features = await asyncio.to_thread(pd.read_parquet, network.node_features_file_path)
    except (OSError, ValueError, ImportError) as error:
        raise HTTPException(status_code=422, detail="Unable to read network module assignments") from error
    if "gene_id" not in features.columns or "module" not in features.columns:
        raise HTTPException(status_code=422, detail="This network does not contain module assignments")

    features = features.copy()
    features["module"] = features["module"].fillna("M0").astype(str)
    features["degree"] = pd.to_numeric(features.get("degree", 0), errors="coerce").fillna(0)
    module_groups = {
        module_id: group.sort_values("degree", ascending=False)
        for module_id, group in features.groupby("module", sort=False)
    }
    gene_ids = features["gene_id"].dropna().astype(str).unique().tolist()
    if network.species == SpeciesEnum.HUMAN:
        mapping_query = select(OrthologyMapping.human_ensembl_id, OrthologyMapping.human_symbol).where(
            OrthologyMapping.human_ensembl_id.in_(gene_ids),
            OrthologyMapping.human_symbol.is_not(None),
        )
    else:
        mapping_query = select(OrthologyMapping.mouse_ensembl_id, OrthologyMapping.mouse_symbol).where(
            OrthologyMapping.mouse_ensembl_id.in_(gene_ids),
            OrthologyMapping.mouse_symbol.is_not(None),
        )
    symbol_result = await db.execute(mapping_query)
    symbols = {str(gene_id): symbol for gene_id, symbol in symbol_result.all()}

    modules = []
    for module_id, group in module_groups.items():
        hub_genes = []
        for _, row in group.head(10).iterrows():
            gene_id = str(row["gene_id"])
            hub_genes.append({
                "gene_id": gene_id,
                "symbol": symbols.get(gene_id),
                "degree": int(row["degree"]),
            })
        modules.append({
            "module_id": module_id,
            "size": int(len(group)),
            "hub_genes": hub_genes,
        })
    modules.sort(key=lambda module: (-module["size"], module["module_id"]))
    return {"network_id": network_id, "module_count": len(modules), "modules": modules}


@router.post("/{network_id}/modules/{module_id}/enrichment")
async def enrich_network_module(
    network_id: str,
    module_id: str,
    payload: ModuleEnrichmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    network = await _get_owned_network(network_id, current_user, db)
    if network.status != JobStatusEnum.COMPLETED or not network.node_features_file_path:
        raise HTTPException(status_code=409, detail="Completed network module assignments are not available")
    if not os.path.isfile(network.node_features_file_path):
        raise HTTPException(status_code=404, detail="Network node features not found")

    from app.bio.pathways import GENE_SETS_HUMAN, GENE_SETS_MOUSE
    available_gene_sets = GENE_SETS_HUMAN if network.species == SpeciesEnum.HUMAN else GENE_SETS_MOUSE
    if payload.gene_set not in available_gene_sets:
        raise HTTPException(status_code=400, detail="Gene set is not supported for this species")

    try:
        features = await asyncio.to_thread(pd.read_parquet, network.node_features_file_path)
    except (OSError, ValueError, ImportError) as error:
        raise HTTPException(status_code=422, detail="Unable to read network module assignments") from error
    if "gene_id" not in features.columns or "module" not in features.columns:
        raise HTTPException(status_code=422, detail="This network does not contain module assignments")
    module_features = features[features["module"].fillna("M0").astype(str) == module_id]
    gene_ids = module_features["gene_id"].dropna().astype(str).unique().tolist()
    if not gene_ids:
        raise HTTPException(status_code=404, detail="Module not found in this network")

    if network.species == SpeciesEnum.HUMAN:
        mapping_query = select(OrthologyMapping.human_ensembl_id, OrthologyMapping.human_symbol).where(
            OrthologyMapping.human_ensembl_id.in_(gene_ids),
            OrthologyMapping.human_symbol.is_not(None),
        )
    else:
        mapping_query = select(OrthologyMapping.mouse_ensembl_id, OrthologyMapping.mouse_symbol).where(
            OrthologyMapping.mouse_ensembl_id.in_(gene_ids),
            OrthologyMapping.mouse_symbol.is_not(None),
        )
    symbol_result = await db.execute(mapping_query)
    symbol_map = {str(gene_id): str(symbol) for gene_id, symbol in symbol_result.all() if symbol}
    mapped_symbols = list(dict.fromkeys(symbol_map[gene_id] for gene_id in gene_ids if gene_id in symbol_map))
    if not mapped_symbols:
        return {
            "network_id": network_id,
            "module_id": module_id,
            "gene_set": payload.gene_set,
            "total_genes": len(gene_ids),
            "mapped_genes": 0,
            "results": [],
            "message": "No module genes have mapped symbols in the orthology annotation table.",
        }

    result_frame = await asyncio.to_thread(
        _run_module_enrichment,
        mapped_symbols,
        payload.gene_set,
        network.species.value,
    )
    if "error" in result_frame.columns:
        return {
            "network_id": network_id,
            "module_id": module_id,
            "gene_set": payload.gene_set,
            "total_genes": len(gene_ids),
            "mapped_genes": len(mapped_symbols),
            "results": [],
            "message": str(result_frame["error"].iloc[0]),
        }

    enrichment_rows = []
    for _, row in result_frame.head(20).iterrows():
        term = row.get("term")
        if term is None or pd.isna(term):
            continue
        adjusted_pvalue = row.get("padj")
        enrichment_rows.append({
            "term": str(term),
            "overlap": None if pd.isna(row.get("overlap")) else str(row.get("overlap")),
            "adjusted_pvalue": None if adjusted_pvalue is None or pd.isna(adjusted_pvalue) else float(adjusted_pvalue),
            "odds_ratio": None if pd.isna(row.get("odds_ratio")) else float(row.get("odds_ratio")),
            "genes": None if pd.isna(row.get("genes")) else str(row.get("genes")),
            "significant": bool(row.get("significant", False)),
        })
    return {
        "network_id": network_id,
        "module_id": module_id,
        "gene_set": payload.gene_set,
        "total_genes": len(gene_ids),
        "mapped_genes": len(mapped_symbols),
        "results": enrichment_rows,
        "message": None if enrichment_rows else "No enrichment terms were returned for this module.",
    }


def _run_module_enrichment(gene_symbols: list[str], gene_set: str, species: str) -> pd.DataFrame:
    from app.bio.pathways import PathwayAnalyzer

    return PathwayAnalyzer(species=species, fdr_threshold=0.05).run_ora(gene_symbols, gene_set)
