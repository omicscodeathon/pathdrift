"""Analysis management routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import Analysis, Project, User
from app.schemas.schemas import AnalysisCreate, AnalysisOut

router = APIRouter()


@router.post("/", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
async def create_analysis(
    payload: AnalysisCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, payload.project_id)
    if project is None or project.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    analysis = Analysis(
        project_id=project.id,
        name=payload.name,
        description=payload.description,
        random_seed=payload.random_seed,
    )
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)
    return analysis


@router.get("/project/{project_id}", response_model=list[AnalysisOut])
async def list_analyses_for_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Analysis)
        .where(Analysis.project_id == project_id, Analysis.project.has(owner_id=current_user.id))
        .order_by(Analysis.created_at.desc())
    )
    return result.scalars().all()


@router.get("/", response_model=list[AnalysisOut])
async def list_analyses(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Analysis)
        .join(Project, Analysis.project_id == Project.id)
        .where(Project.owner_id == current_user.id)
        .order_by(Analysis.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(
    analysis_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.project.has(owner_id=current_user.id),
        )
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis
