"""Report generation routes."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, Analysis
from app.schemas.schemas import ReportConfig

router = APIRouter()


@router.post("/generate")
async def generate_report(
    config: ReportConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue report generation for an analysis."""
    result = await db.execute(select(Analysis).where(Analysis.id == config.analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    from app.tasks.celery_app import celery_app
    from app.models import BackgroundJob
    bg_job = BackgroundJob(analysis_id=config.analysis_id, task_name="generate_report")
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)

    # Import lazily to avoid circular imports
    from app.tasks.report_tasks import generate_report_task
    task = generate_report_task.apply_async(
        args=[bg_job.id, config.analysis_id, config.include_sections, config.format],
        queue="default",
    )
    bg_job.celery_task_id = task.id
    bg_job.result_ref = config.analysis_id
    await db.flush()
    return {"job_id": bg_job.id}


@router.get("/{analysis_id}/download")
async def download_report(
    analysis_id: str,
    format: str = "pdf",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import os
    from app.core.config import settings
    report_path = os.path.join(settings.REPORT_DIR, analysis_id, f"report.{format}")
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Report not yet generated")
    return FileResponse(
        report_path,
        media_type="application/pdf" if format == "pdf" else "text/html",
        filename=f"pathdrift_report_{analysis_id}.{format}",
    )
