"""
Data import routes: NCBI GEO, TCGA/GDC integration.
Respects API rate limits and terms of service.
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User
from app.schemas.schemas import GEOImportRequest, TCGAImportRequest

router = APIRouter()


@router.post("/geo", status_code=status.HTTP_202_ACCEPTED)
async def import_from_geo(
    request: GEOImportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Import a dataset from NCBI GEO using the accession number (e.g. GSE12345).
    Uses GEOparse + NCBI Entrez API.
    Rate-limited; respects NCBI guidelines.
    """
    from app.services.geo_import_service import GEOImportService
    from app.core.config import settings

    if not settings.NCBI_EMAIL:
        raise HTTPException(
            status_code=400,
            detail="NCBI_EMAIL must be configured in .env before importing from GEO. "
                   "This is required by NCBI's API terms of service.",
        )

    svc = GEOImportService(db, current_user, settings)
    job = await svc.initiate_import(
        project_id=request.project_id,
        accession=request.accession,
        species=request.species,
        tissue=request.tissue,
    )
    return {"job_id": job.id, "message": f"GEO import of {request.accession} queued"}


@router.post("/tcga", status_code=status.HTTP_202_ACCEPTED)
async def import_from_tcga(
    request: TCGAImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Import expression data from TCGA via GDC API.
    Uses the GDC Data Portal REST API (no key required, rate-limited).
    """
    from app.services.tcga_import_service import TCGAImportService
    from app.core.config import settings

    svc = TCGAImportService(db, current_user, settings)
    job = await svc.initiate_import(
        project_id=request.project_id,
        project_code=request.project_code,
        tissue=request.tissue,
    )
    return {"job_id": job.id, "message": f"TCGA import of {request.project_code} queued"}
