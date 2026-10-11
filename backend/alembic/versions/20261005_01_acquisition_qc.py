"""Add durable acquisition runs and sample QC."""
from alembic import op


revision = "20261005_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_version VARCHAR(100)")
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS retrieval_url VARCHAR(1024)")
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS download_date TIMESTAMPTZ")
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS checksum VARCHAR(64)")
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS processing_steps JSONB")
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS provenance JSONB")
    op.execute("""
        CREATE TABLE IF NOT EXISTS analysis_runs (
            id VARCHAR(36) PRIMARY KEY,
            project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
            stage VARCHAR(32) NOT NULL DEFAULT 'PENDING',
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            qc_summary JSONB,
            run_dir VARCHAR(1024),
            manifest_path VARCHAR(1024),
            provenance_path VARCHAR(1024),
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS analysis_run_datasets (
            id VARCHAR(36) PRIMARY KEY,
            run_id VARCHAR(36) NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
            dataset_id VARCHAR(36) NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
            provenance JSONB,
            CONSTRAINT uq_analysis_run_dataset UNIQUE (run_id, dataset_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS sample_qc (
            id VARCHAR(36) PRIMARY KEY,
            run_id VARCHAR(36) NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
            dataset_id VARCHAR(36) NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
            sample_id VARCHAR(255) NOT NULL,
            library_size DOUBLE PRECISION,
            detected_genes INTEGER,
            missing_fraction DOUBLE PRECISION,
            zero_fraction DOUBLE PRECISION,
            mean_expression DOUBLE PRECISION,
            median_expression DOUBLE PRECISION,
            outlier_score DOUBLE PRECISION,
            is_outlier BOOLEAN NOT NULL DEFAULT false,
            excluded BOOLEAN NOT NULL DEFAULT false,
            exclusion_reason TEXT,
            pca_coordinates JSONB NOT NULL DEFAULT '{}'::jsonb,
            cluster INTEGER,
            batch_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            sample_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_sample_qc_run_dataset_sample UNIQUE (run_id, dataset_id, sample_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_runs_project_id ON analysis_runs(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_runs_status ON analysis_runs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_run_datasets_run_id ON analysis_run_datasets(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_analysis_run_datasets_dataset_id ON analysis_run_datasets(dataset_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sample_qc_run_id ON sample_qc(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sample_qc_dataset_id ON sample_qc(dataset_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sample_qc")
    op.execute("DROP TABLE IF EXISTS analysis_run_datasets")
    op.execute("DROP TABLE IF EXISTS analysis_runs")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS provenance")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS processing_steps")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS checksum")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS download_date")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS retrieval_url")
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS source_version")