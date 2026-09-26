"""Network construction routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pandas as pd

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, GeneNetwork, BackgroundJob, Analysis, JobStatusEnum
from app.schemas.schemas import NetworkConfig, NetworkOut, JobOut

router = APIRouter()


@router.post("/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def build_network(
    config: NetworkConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Analysis).where(Analysis.id == config.analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    network = GeneNetwork(
        analysis_id=config.analysis_id,
        dataset_id=config.dataset_id,
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


@router.get("/{network_id}", response_model=NetworkOut)
async def get_network(
    network_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(GeneNetwork).where(GeneNetwork.id == network_id))
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.get("/{network_id}/edges")
async def get_network_edges(
    network_id: str,
    limit: int = 1000,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(GeneNetwork).where(GeneNetwork.id == network_id))
    network = result.scalar_one_or_none()
    if not network or not network.adjacency_file_path:
        raise HTTPException(status_code=404, detail="Network edges not available")
    edges_df = pd.read_parquet(network.adjacency_file_path)
    return edges_df.head(limit).to_dict(orient="records")


@router.get("/{network_id}/nodes")
async def get_network_nodes(
    network_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(GeneNetwork).where(GeneNetwork.id == network_id))
    network = result.scalar_one_or_none()
    if not network or not network.node_features_file_path:
        raise HTTPException(status_code=404, detail="Node features not available")
    nodes_df = pd.read_parquet(network.node_features_file_path)
    return nodes_df.to_dict(orient="records")
