"""Project management routes."""
import asyncio
import os

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import (
    Analysis, CrossSpeciesAnalysis, Dataset, DEGResult, JobStatusEnum,
    OrthologyMapping, PathwayResult, Project, Sample, SpeciesEnum, User,
)
from app.schemas.schemas import ProjectCreate, ProjectOut

router = APIRouter()


@router.post("/", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = Project(
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
        research_question=payload.research_question,
        is_public=payload.is_public,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


@router.get("/", response_model=list[ProjectOut])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(Project.owner_id == current_user.id)
        .order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/dashboard-summary")
async def get_dashboard_summary(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project_result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    dataset_result = await db.execute(select(Dataset).where(Dataset.project_id == project_id))
    datasets = dataset_result.scalars().all()
    sample_result = await db.execute(
        select(Sample.dataset_id, func.count(Sample.id))
        .join(Dataset, Dataset.id == Sample.dataset_id)
        .where(Dataset.project_id == project_id)
        .group_by(Sample.dataset_id)
    )
    sample_counts = dict(sample_result.all())
    sample_totals = {SpeciesEnum.HUMAN: 0, SpeciesEnum.MOUSE: 0}
    for dataset in datasets:
        sample_totals[dataset.species] += (
            dataset.n_samples if dataset.n_samples is not None else sample_counts.get(dataset.id, 0)
        )

    deg_result = await db.execute(
        select(DEGResult, Dataset.species, Dataset.id)
        .join(Dataset, Dataset.id == DEGResult.dataset_id)
        .join(Analysis, Analysis.id == DEGResult.analysis_id)
        .where(
            Analysis.project_id == project_id,
            DEGResult.status == JobStatusEnum.COMPLETED,
            DEGResult.n_deg_total.is_not(None),
        )
        .order_by(DEGResult.created_at.desc())
    )
    latest_deg_by_dataset = {}
    for result, species, dataset_id in deg_result.all():
        latest_deg_by_dataset.setdefault(dataset_id, (species, result.n_deg_total))
    deg_totals = {SpeciesEnum.HUMAN: 0, SpeciesEnum.MOUSE: 0}
    for species, total in latest_deg_by_dataset.values():
        deg_totals[species] += total or 0
    deg_species_present = {species for species, _ in latest_deg_by_dataset.values()}

    cross_species_result = await db.execute(
        select(CrossSpeciesAnalysis)
        .join(Analysis, Analysis.id == CrossSpeciesAnalysis.analysis_id)
        .where(
            Analysis.project_id == project_id,
            CrossSpeciesAnalysis.status == JobStatusEnum.COMPLETED,
        )
        .order_by(CrossSpeciesAnalysis.created_at.desc())
        .limit(1)
    )
    cross_species = cross_species_result.scalar_one_or_none()

    pathway_result = await db.execute(
        select(PathwayResult)
        .join(Analysis, Analysis.id == PathwayResult.analysis_id)
        .where(
            Analysis.project_id == project_id,
            PathwayResult.status == JobStatusEnum.COMPLETED,
        )
        .order_by(PathwayResult.created_at.desc())
        .limit(1)
    )
    latest_pathway = pathway_result.scalar_one_or_none()
    top_pathways = []
    if latest_pathway and latest_pathway.results_file_path and os.path.isfile(latest_pathway.results_file_path):
        try:
            pathway_frame = await asyncio.to_thread(pd.read_parquet, latest_pathway.results_file_path)
            if "significant" in pathway_frame.columns:
                pathway_frame = pathway_frame[pathway_frame["significant"]]
            if "padj" in pathway_frame.columns:
                pathway_frame = pathway_frame.sort_values("padj")
            for _, row in pathway_frame.head(5).iterrows():
                term = row.get("term")
                if term is None or pd.isna(term):
                    continue
                adjusted_pvalue = row.get("padj")
                top_pathways.append({
                    "term": str(term),
                    "adjusted_pvalue": None if adjusted_pvalue is None or pd.isna(adjusted_pvalue) else float(adjusted_pvalue),
                })
        except (OSError, ValueError, ImportError):
            top_pathways = []

    orthology_result = await db.execute(select(func.count()).select_from(OrthologyMapping))
    conservation = cross_species.conservation_score if cross_species else None
    drifted_genes = None
    if cross_species:
        drifted_genes = sum(value or 0 for value in (
            cross_species.n_conserved_drift,
            cross_species.n_human_specific,
            cross_species.n_mouse_specific,
            cross_species.n_divergent,
        ))

    return {
        "human_samples": sample_totals[SpeciesEnum.HUMAN],
        "mouse_samples": sample_totals[SpeciesEnum.MOUSE],
        "orthologs": orthology_result.scalar_one(),
        "human_degs": deg_totals[SpeciesEnum.HUMAN] if SpeciesEnum.HUMAN in deg_species_present else None,
        "mouse_degs": deg_totals[SpeciesEnum.MOUSE] if SpeciesEnum.MOUSE in deg_species_present else None,
        "drifted_genes": drifted_genes,
        "conservation_score": conservation,
        "top_pathways": top_pathways,
        "cross_species_analysis_id": cross_species.id if cross_species else None,
    }


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)
    await db.flush()
