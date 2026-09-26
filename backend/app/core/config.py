"""
Application configuration via environment variables (Pydantic Settings).
All secrets are loaded from environment; never hard-coded.
"""
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str          # asyncpg URL
    DATABASE_URL_SYNC: str     # psycopg2 URL (Alembic, Celery)

    # ── Redis / Celery ────────────────────────────────────────────────────────
    REDIS_URL: str
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def set_broker(cls, v, info):
        return v or info.data.get("REDIS_URL", "").replace("/0", "/0")

    @field_validator("CELERY_RESULT_BACKEND", mode="before")
    @classmethod
    def set_result_backend(cls, v, info):
        return v or info.data.get("REDIS_URL", "").replace("/0", "/1")

    # ── File storage ─────────────────────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    REPORT_DIR: str = "./reports"
    LOG_DIR: str = "./logs"
    MAX_UPLOAD_SIZE_MB: int = 500

    # ── CORS / hosts ─────────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    ALLOWED_HOSTS: List[str] = ["localhost", "127.0.0.1"]

    # ── External APIs ─────────────────────────────────────────────────────────
    NCBI_API_KEY: Optional[str] = None
    NCBI_EMAIL: Optional[str] = None
    GDC_API_URL: str = "https://api.gdc.cancer.gov"
    GTEX_PORTAL_URL: str = "https://gtexportal.org/api/v2"
    ENSEMBL_REST_URL: str = "https://rest.ensembl.org"

    # ── Analysis limits ───────────────────────────────────────────────────────
    MAX_NETWORK_GENES: int = 5000
    MAX_ML_FEATURES: int = 10000
    DEFAULT_RANDOM_SEED: int = 42


settings = Settings()
