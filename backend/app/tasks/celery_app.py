"""
Celery Application Configuration
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "pathdrift",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.analysis_tasks",
        "app.tasks.ml_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.tasks.analysis_tasks.*": {"queue": "analysis"},
        "app.tasks.ml_tasks.*": {"queue": "ml"},
    },
    task_soft_time_limit=3600,    # 1 hour soft limit
    task_time_limit=7200,          # 2 hour hard limit
)
