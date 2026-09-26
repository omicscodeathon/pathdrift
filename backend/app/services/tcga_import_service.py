"""
TCGA Import Service — imports expression data from TCGA via GDC API.
"""
import structlog
from app.models import Dataset, BackgroundJob, JobStatusEnum, SpeciesEnum, DataTypeEnum

logger = structlog.get_logger(__name__)


class TCGAImportService:
    def __init__(self, db, current_user, settings):
        self.db = db
        self.user = current_user
        self.settings = settings

    async def initiate_import(self, project_id: str, project_code: str, tissue: str = None):
        """
        Initiate a TCGA import job via GDC API.
        """
        dataset = Dataset(
            project_id=project_id,
            owner_id=self.user.id,
            name=f"TCGA: {project_code}",
            species=SpeciesEnum.HUMAN,
            tissue=tissue or "breast",
            source="TCGA",
            accession=project_code,
            data_type=DataTypeEnum.RAW_COUNTS,
        )
        self.db.add(dataset)
        await self.db.flush()

        bg_job = BackgroundJob(analysis_id=None, task_name="import_from_tcga")
        self.db.add(bg_job)
        await self.db.flush()
        await self.db.refresh(bg_job)

        from app.tasks.import_tasks import import_tcga_task
        task = import_tcga_task.apply_async(
            args=[bg_job.id, dataset.id, project_code, self.settings.UPLOAD_DIR,
                  self.settings.GDC_API_URL],
            queue="default",
        )
        bg_job.celery_task_id = task.id
        await self.db.flush()
        return bg_job
