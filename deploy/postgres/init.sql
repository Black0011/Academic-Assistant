-- Database initialisation — Alembic owns the real schema.
-- Only extensions and roles go here.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- CREATE EXTENSION IF NOT EXISTS vector;  -- enable if you want pgvector
