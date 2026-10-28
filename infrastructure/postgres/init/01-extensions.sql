-- Extensions required by docs/DATABASE_SCHEMA.md.
-- The postgis extension is created automatically by the base image.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;
