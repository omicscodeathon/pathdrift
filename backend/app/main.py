"""
PathDrift FastAPI Application Entry Point
"""
import sys
import asyncio

# asyncpg requires SelectorEventLoop on Windows (ProactorEventLoop default causes 500s)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
import structlog

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.base import engine, Base
from app.api.routes import (
    auth,
    users,
    projects,
    analyses,
    datasets,
    preprocessing,
    deg,
    networks,
    drift,
    orthology,
    cross_species,
    ml,
    validation,
    pathways,
    reports,
    jobs,
    data_import,
    phase4,
    data_acquisition,
    gene_loss,
    ppi,
    runs,
    phase3,
    phase5,
    phase6,
)

configure_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("pathdrift_starting", environment=settings.ENVIRONMENT)
    # Tables are created via Alembic migrations; do not auto-create in production.
    # For development convenience, optionally create them here.
    if settings.ENVIRONMENT == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    logger.info("pathdrift_shutdown")
    await engine.dispose()


app = FastAPI(
    title="PathDrift",
    description=(
        "Cross-Species Gene Network Drift Detection "
        "for Early Breast Cancer State Prediction"
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── Security middleware ────────────────────────────────────────────────────────
if settings.ENVIRONMENT == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# ── Static files ───────────────────────────────────────────────────────────────
import os

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.REPORT_DIR, exist_ok=True)
os.makedirs(settings.LOG_DIR, exist_ok=True)

# ── API routes ─────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth.router,         prefix=f"{API_PREFIX}/auth",          tags=["Authentication"])
app.include_router(users.router,        prefix=f"{API_PREFIX}/users",         tags=["Users"])
app.include_router(projects.router,     prefix=f"{API_PREFIX}/projects",      tags=["Projects"])
app.include_router(analyses.router,     prefix=f"{API_PREFIX}/analyses",      tags=["Analyses"])
app.include_router(datasets.router,     prefix=f"{API_PREFIX}/datasets",      tags=["Datasets"])
app.include_router(data_acquisition.router, prefix=f"{API_PREFIX}/data-acquisition", tags=["Data Acquisition"])
app.include_router(data_import.router,  prefix=f"{API_PREFIX}/import",        tags=["Data Import"])
app.include_router(preprocessing.router,prefix=f"{API_PREFIX}/preprocessing", tags=["Preprocessing"])
app.include_router(deg.router,          prefix=f"{API_PREFIX}/deg",           tags=["DEG Analysis"])
app.include_router(networks.router,     prefix=f"{API_PREFIX}/networks",      tags=["Networks"])
app.include_router(drift.router,        prefix=f"{API_PREFIX}/drift",         tags=["Network Drift"])
app.include_router(orthology.router,    prefix=f"{API_PREFIX}/orthology",     tags=["Orthology"])
app.include_router(cross_species.router,prefix=f"{API_PREFIX}/cross-species", tags=["Cross-Species"])
app.include_router(ml.router,           prefix=f"{API_PREFIX}/ml",            tags=["Machine Learning"])
app.include_router(validation.router,   prefix=f"{API_PREFIX}/validation",    tags=["Validation"])
app.include_router(pathways.router,     prefix=f"{API_PREFIX}/pathways",      tags=["Pathway Analysis"])
app.include_router(reports.router,      prefix=f"{API_PREFIX}/reports",       tags=["Reports"])
app.include_router(jobs.router,         prefix=f"{API_PREFIX}/jobs",          tags=["Job Management"])
app.include_router(gene_loss.router,    prefix=f"{API_PREFIX}/gene-loss",     tags=["Gene Loss"])
app.include_router(ppi.router,          prefix=f"{API_PREFIX}/ppi",           tags=["PPI Network"])
app.include_router(runs.router,         prefix="/api/runs",                   tags=["Acquisition Runs"])
app.include_router(runs.router,         prefix=f"{API_PREFIX}/runs",           tags=["Acquisition Runs"])
app.include_router(phase3.router,       prefix="/api/runs",                   tags=["Phase 3 Analysis"])
app.include_router(phase3.router,       prefix=f"{API_PREFIX}/runs",           tags=["Phase 3 Analysis"])
app.include_router(phase4.router,       prefix="/api/runs",                   tags=["Phase 4 Analysis"])
app.include_router(phase4.router,       prefix=f"{API_PREFIX}/runs",           tags=["Phase 4 Analysis"])
app.include_router(phase5.router,       prefix="/api/runs",                   tags=["Phase 5 Analysis"])
app.include_router(phase5.router,       prefix=f"{API_PREFIX}/runs",           tags=["Phase 5 Analysis"])
app.include_router(phase6.router,      prefix="/api/runs",                    tags=["Phase 6 Machine Learning"])
app.include_router(phase6.router,      prefix=f"{API_PREFIX}/runs",           tags=["Phase 6 Machine Learning"])


@app.get("/api/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
    }
