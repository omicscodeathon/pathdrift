"""
GEO Import Service — imports expression datasets from NCBI GEO.
Uses GEOparse library to download series matrix files.
"""
import os
import uuid
import time
import httpx
import structlog
from sqlalchemy.orm import Session
from app.models import Dataset, BackgroundJob, JobStatusEnum, SpeciesEnum, DataTypeEnum

logger = structlog.get_logger(__name__)

GEO_BASE_URL = "https://ftp.ncbi.nlm.nih.gov/geo/series"


class GEOImportService:
    def __init__(self, db, current_user, settings):
        self.db = db
        self.user = current_user
        self.settings = settings

    async def initiate_import(self, project_id: str, accession: str, species: SpeciesEnum, tissue: str = None):
        """
        Initiate a GEO import job.
        The actual download happens asynchronously via a Celery task.
        """
        dataset = Dataset(
            project_id=project_id,
            owner_id=self.user.id,
            name=f"GEO: {accession}",
            species=species,
            tissue=tissue,
            source="GEO",
            accession=accession,
            data_type=DataTypeEnum.UNKNOWN,
        )
        self.db.add(dataset)
        await self.db.flush()

        bg_job = BackgroundJob(
            analysis_id=None,
            task_name="import_from_geo",
        )
        self.db.add(bg_job)
        await self.db.flush()
        await self.db.refresh(bg_job)

        from app.tasks.import_tasks import import_geo_task
        task = import_geo_task.apply_async(
            args=[bg_job.id, dataset.id, accession, self.settings.UPLOAD_DIR,
                  self.settings.NCBI_EMAIL, self.settings.NCBI_API_KEY],
            queue="default",
        )
        bg_job.celery_task_id = task.id
        await self.db.flush()
        return bg_job
