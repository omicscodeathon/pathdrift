"""Cross-species comparison routes."""
import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pandas as pd

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import (
    Analysis, BackgroundJob, CrossSpeciesAnalysis, DriftAnalysis,
    GeneNetwork, JobStatusEnum, OrthologyMapping, Project, SpeciesEnum, User,
)
from app.schemas.schemas import CrossSpeciesConfig, CrossSpeciesOut, JobOut

router = APIRouter()


@router.post("/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def run_cross_species(
    config: CrossSpeciesConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for drift_id in [config.human_drift_id, config.mouse_drift_id]:
        r = await db.execute(select(DriftAnalysis).where(DriftAnalysis.id == drift_id))
        drift = r.scalar_one_or_none()
        if not drift:
            raise HTTPException(status_code=404, detail=f"Drift analysis {drift_id} not found")
        if drift.status != JobStatusEnum.COMPLETED:
            raise HTTPException(status_code=400, detail=f"Drift analysis {drift_id} not completed")

    cs = CrossSpeciesAnalysis(
        analysis_id=config.analysis_id,
        human_drift_id=config.human_drift_id,
        mouse_drift_id=config.mouse_drift_id,
    )
    db.add(cs)
    await db.flush()

    bg_job = BackgroundJob(analysis_id=config.analysis_id, task_name="run_cross_species")
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)

    from app.tasks.analysis_tasks import run_cross_species as run_cs_task
    task = run_cs_task.apply_async(args=[bg_job.id, cs.id], queue="analysis")
    bg_job.celery_task_id = task.id
    bg_job.result_ref = cs.id
    await db.flush()
    return bg_job


@router.get("/project/{project_id}", response_model=list[CrossSpeciesOut])
async def list_project_cross_species_results(
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
        select(CrossSpeciesAnalysis)
        .join(Analysis, Analysis.id == CrossSpeciesAnalysis.analysis_id)
        .where(Analysis.project_id == project_id)
        .order_by(CrossSpeciesAnalysis.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{cs_id}/network-alignment")
async def get_network_alignment(
    cs_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    comparison_result = await db.execute(
        select(CrossSpeciesAnalysis)
        .join(Analysis, Analysis.id == CrossSpeciesAnalysis.analysis_id)
        .where(
            CrossSpeciesAnalysis.id == cs_id,
            Analysis.project.has(owner_id=current_user.id),
            CrossSpeciesAnalysis.status == JobStatusEnum.COMPLETED,
        )
    )
    comparison = comparison_result.scalar_one_or_none()
    if not comparison:
        raise HTTPException(status_code=404, detail="Completed cross-species comparison not found")

    drift_result = await db.execute(
        select(DriftAnalysis).where(
            DriftAnalysis.id.in_([comparison.human_drift_id, comparison.mouse_drift_id]),
            DriftAnalysis.status == JobStatusEnum.COMPLETED,
        )
    )
    drifts = {drift.id: drift for drift in drift_result.scalars().all()}
    human_drift = drifts.get(comparison.human_drift_id)
    mouse_drift = drifts.get(comparison.mouse_drift_id)
    if not human_drift or not mouse_drift:
        raise HTTPException(status_code=409, detail="Both completed species drift results are required")
    if human_drift.species != SpeciesEnum.HUMAN or mouse_drift.species != SpeciesEnum.MOUSE:
        raise HTTPException(status_code=409, detail="Comparison drift results do not match the expected species")

    network_result = await db.execute(
        select(GeneNetwork).where(GeneNetwork.id.in_([
            human_drift.disease_network_id,
            mouse_drift.disease_network_id,
        ]))
    )
    networks = {network.id: network for network in network_result.scalars().all()}
    human_network = networks.get(human_drift.disease_network_id)
    mouse_network = networks.get(mouse_drift.disease_network_id)
    if not human_network or not mouse_network:
        raise HTTPException(status_code=404, detail="Disease-state network files are unavailable")
    for network in [human_network, mouse_network]:
        if network.status != JobStatusEnum.COMPLETED or not network.adjacency_file_path or not os.path.isfile(network.adjacency_file_path):
            raise HTTPException(status_code=409, detail="Both disease-state networks must be completed with saved edges")

    mapping_result = await db.execute(
        select(
            OrthologyMapping.human_ensembl_id,
            OrthologyMapping.mouse_ensembl_id,
            OrthologyMapping.orthology_type,
        ).where(OrthologyMapping.orthology_type == "ortholog_one2one")
    )
    mapping = pd.DataFrame(
        mapping_result.all(),
        columns=["human_ensembl_id", "mouse_ensembl_id", "orthology_type"],
    )
    human_edges, mouse_edges = await asyncio.gather(
        asyncio.to_thread(pd.read_parquet, human_network.adjacency_file_path),
        asyncio.to_thread(pd.read_parquet, mouse_network.adjacency_file_path),
    )
    from app.bio.cross_species import align_network_edges
    alignment = await asyncio.to_thread(align_network_edges, human_edges, mouse_edges, mapping)

    return {
        "comparison_id": cs_id,
        "human_network_id": human_network.id,
        "mouse_network_id": mouse_network.id,
        "human_network_name": human_network.name,
        "mouse_network_name": mouse_network.name,
        "mapped_ortholog_pairs": int(alignment["mapped_ortholog_pairs"] or 0),
        "human_total_edges": int(len(human_edges)),
        "mouse_total_edges": int(len(mouse_edges)),
        "alignment": alignment,
        "human_graph": _network_preview(human_edges),
        "mouse_graph": _network_preview(mouse_edges),
    }


@router.get("/{cs_id}/genes/{gene_id}/network-drift")
async def get_cross_species_gene_drift(
    cs_id: str,
    gene_id: str,
    species: SpeciesEnum,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    comparison_result = await db.execute(
        select(CrossSpeciesAnalysis, Analysis.project_id)
        .join(Analysis, Analysis.id == CrossSpeciesAnalysis.analysis_id)
        .where(
            CrossSpeciesAnalysis.id == cs_id,
            Analysis.project.has(owner_id=current_user.id),
            CrossSpeciesAnalysis.status == JobStatusEnum.COMPLETED,
        )
    )
    comparison_row = comparison_result.one_or_none()
    if not comparison_row:
        raise HTTPException(status_code=404, detail="Completed cross-species comparison not found")
    comparison, project_id = comparison_row

    drift_result = await db.execute(
        select(DriftAnalysis)
        .join(Analysis, Analysis.id == DriftAnalysis.analysis_id)
        .where(
            DriftAnalysis.id.in_([comparison.human_drift_id, comparison.mouse_drift_id]),
            Analysis.project_id == project_id,
            DriftAnalysis.status == JobStatusEnum.COMPLETED,
        )
    )
    drifts = {drift.id: drift for drift in drift_result.scalars().all()}
    human_drift = drifts.get(comparison.human_drift_id)
    mouse_drift = drifts.get(comparison.mouse_drift_id)
    if not human_drift or not mouse_drift:
        raise HTTPException(status_code=409, detail="Both completed species drift results are required")

    if species == SpeciesEnum.HUMAN:
        mapping_query = select(
            OrthologyMapping.human_ensembl_id,
            OrthologyMapping.mouse_ensembl_id,
            OrthologyMapping.human_symbol,
            OrthologyMapping.mouse_symbol,
        ).where(
            OrthologyMapping.human_ensembl_id == gene_id,
            OrthologyMapping.orthology_type == "ortholog_one2one",
        )
    else:
        mapping_query = select(
            OrthologyMapping.human_ensembl_id,
            OrthologyMapping.mouse_ensembl_id,
            OrthologyMapping.human_symbol,
            OrthologyMapping.mouse_symbol,
        ).where(
            OrthologyMapping.mouse_ensembl_id == gene_id,
            OrthologyMapping.orthology_type == "ortholog_one2one",
        )
    mapping_result = await db.execute(mapping_query.limit(1))
    mapping = mapping_result.one_or_none()

    if species == SpeciesEnum.HUMAN:
        human_gene_id = gene_id
        mouse_gene_id = mapping.mouse_ensembl_id if mapping else None
    else:
        human_gene_id = mapping.human_ensembl_id if mapping else None
        mouse_gene_id = gene_id

    network_ids = [
        human_drift.healthy_network_id, human_drift.disease_network_id,
        mouse_drift.healthy_network_id, mouse_drift.disease_network_id,
    ]
    network_result = await db.execute(
        select(GeneNetwork)
        .join(Analysis, Analysis.id == GeneNetwork.analysis_id)
        .where(GeneNetwork.id.in_(network_ids), Analysis.project_id == project_id)
    )
    networks = {network.id: network for network in network_result.scalars().all()}

    async def get_network_edges(network_id: str) -> pd.DataFrame:
        network = networks.get(network_id)
        if not network or not network.adjacency_file_path or not os.path.isfile(network.adjacency_file_path):
            return pd.DataFrame(columns=["gene1", "gene2", "weight"])
        return await asyncio.to_thread(pd.read_parquet, network.adjacency_file_path)

    human_normal, human_cancer, mouse_normal, mouse_cancer = await asyncio.gather(
        get_network_edges(human_drift.healthy_network_id),
        get_network_edges(human_drift.disease_network_id),
        get_network_edges(mouse_drift.healthy_network_id),
        get_network_edges(mouse_drift.disease_network_id),
    )
    from app.bio.cross_species import compare_gene_edge_sets
    human_edges = compare_gene_edge_sets(human_gene_id or "", human_normal, human_cancer) if human_gene_id else None
    mouse_edges = compare_gene_edge_sets(mouse_gene_id or "", mouse_normal, mouse_cancer) if mouse_gene_id else None

    human_neighbors = set()
    mouse_neighbors = set()
    for species_edges, target in [(human_edges, human_neighbors), (mouse_edges, mouse_neighbors)]:
        if species_edges:
            for key in ["normal_edges", "cancer_edges"]:
                target.update(edge["neighbor_id"] for edge in species_edges[key])
    human_symbol_ids = human_neighbors | ({human_gene_id} if human_gene_id else set())
    mouse_symbol_ids = mouse_neighbors | ({mouse_gene_id} if mouse_gene_id else set())
    human_symbol_result = await db.execute(
        select(OrthologyMapping.human_ensembl_id, OrthologyMapping.human_symbol)
        .where(OrthologyMapping.human_ensembl_id.in_(human_symbol_ids), OrthologyMapping.human_symbol.is_not(None))
    ) if human_symbol_ids else None
    mouse_symbol_result = await db.execute(
        select(OrthologyMapping.mouse_ensembl_id, OrthologyMapping.mouse_symbol)
        .where(OrthologyMapping.mouse_ensembl_id.in_(mouse_symbol_ids), OrthologyMapping.mouse_symbol.is_not(None))
    ) if mouse_symbol_ids else None
    human_symbols = {str(item_id): symbol for item_id, symbol in human_symbol_result.all()} if human_symbol_result else {}
    mouse_symbols = {str(item_id): symbol for item_id, symbol in mouse_symbol_result.all()} if mouse_symbol_result else {}

    def decorate_species_edges(edge_data: dict | None, symbols: dict[str, str]) -> dict | None:
        if edge_data is None:
            return None
        decorated = {}
        for key, values in edge_data.items():
            decorated[key] = [
                {**edge, "symbol": symbols.get(edge["neighbor_id"])}
                for edge in values
            ] if isinstance(values, list) else values
        return decorated

    human_edges = decorate_species_edges(human_edges, human_symbols)
    mouse_edges = decorate_species_edges(mouse_edges, mouse_symbols)
    drift_types = sorted({
        drift_type
        for edge_data in [human_edges, mouse_edges]
        if edge_data
        for drift_type in edge_data["drift_types"]
        if drift_type != "No significant edge change"
    })
    if not drift_types:
        drift_types = ["No significant edge change"]

    return {
        "comparison_id": cs_id,
        "input_gene_id": gene_id,
        "input_species": species.value,
        "human": {
            "gene_id": human_gene_id,
            "symbol": human_symbols.get(human_gene_id or "") or (mapping.human_symbol if mapping else None),
            "relationships": human_edges,
            "message": None if human_gene_id else "No one-to-one human ortholog is available.",
        },
        "mouse": {
            "gene_id": mouse_gene_id,
            "symbol": mouse_symbols.get(mouse_gene_id or "") or (mapping.mouse_symbol if mapping else None),
            "relationships": mouse_edges,
            "message": None if mouse_gene_id else "No one-to-one mouse ortholog is available.",
        },
        "drift_types": drift_types,
    }


def _network_preview(edges: pd.DataFrame, limit: int = 80) -> dict:
    if not {"gene1", "gene2"}.issubset(edges.columns):
        return {"nodes": [], "edges": []}
    visible_edges = edges.sort_values("weight", ascending=False).head(limit) if "weight" in edges.columns else edges.head(limit)
    visible_gene_ids = sorted(set(visible_edges["gene1"].dropna().astype(str)) | set(visible_edges["gene2"].dropna().astype(str)))
    return {
        "nodes": [{"gene_id": gene_id} for gene_id in visible_gene_ids],
        "edges": [
            {"gene1": str(row.gene1), "gene2": str(row.gene2), "weight": float(getattr(row, "weight", 1.0))}
            for row in visible_edges.itertuples(index=False)
        ],
    }


@router.get("/{cs_id}", response_model=CrossSpeciesOut)
async def get_cross_species(
    cs_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CrossSpeciesAnalysis).where(CrossSpeciesAnalysis.id == cs_id))
    cs = result.scalar_one_or_none()
    if not cs:
        raise HTTPException(status_code=404, detail="Cross-species analysis not found")
    return cs


@router.get("/{cs_id}/genes")
async def get_conserved_genes(
    cs_id: str,
    classification: str = None,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CrossSpeciesAnalysis).where(CrossSpeciesAnalysis.id == cs_id))
    cs = result.scalar_one_or_none()
    if not cs or not cs.comparison_file_path:
        raise HTTPException(status_code=404, detail="Results not available")
    df = pd.read_parquet(cs.comparison_file_path)
    if classification:
        df = df[df["drift_classification"] == classification]
    return df.head(limit).to_dict(orient="records")
