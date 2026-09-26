-- PathDrift PostgreSQL initialization
-- This file is run automatically by Docker when the container first starts.
-- The database and user are already created by POSTGRES_USER/POSTGRES_DB env vars.

-- Enable extensions that may be useful
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for text search on gene symbols

-- Log that init ran
DO $$
BEGIN
    RAISE NOTICE 'PathDrift database initialized at %', NOW();
END;
$$;
