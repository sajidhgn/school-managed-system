-- Database bootstrap: extensions and the restricted application role.
--
-- WHY THIS FILE EXISTS
--   Row-Level Security is only a real boundary if the application connects as a
--   role that CANNOT bypass it. PostgreSQL grants two silent exemptions:
--     1. Superusers bypass RLS entirely.
--     2. Table OWNERS bypass RLS unless the table is set to FORCE.
--   So an app connecting as `postgres` has every policy silently disabled. This
--   script creates `sms_app` -- a login role that owns nothing, cannot create
--   anything, and has no BYPASSRLS attribute.
--
-- WHEN THIS RUNS
--   Automatically on first boot of the docker-compose `db` service.
--   For your local pgAdmin-managed PostgreSQL, run it once by hand as a superuser:
--       psql -U postgres -d school_manage_db -f scripts/init-db.sql

-- --------------------------------------------------------------------------
-- Extensions
-- --------------------------------------------------------------------------

-- gen_random_uuid() for server-side UUID primary key defaults.
-- Built into PostgreSQL 13+, but pgcrypto is required for other crypto helpers.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Trigram indexes, which power the Global Search omnibar (fuzzy student/teacher
-- name matching). Without pg_trgm, `ILIKE '%ahmed%'` cannot use an index and
-- degrades to a full table scan on every keystroke.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Accent-insensitive search ("Zoë" matches "Zoe").
CREATE EXTENSION IF NOT EXISTS unaccent;

-- --------------------------------------------------------------------------
-- Application role
-- --------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sms_app') THEN
        -- CHANGE THIS PASSWORD outside local development.
        CREATE ROLE sms_app WITH LOGIN PASSWORD 'sms_app_password'
            NOSUPERUSER      -- superusers bypass RLS
            NOCREATEDB
            NOCREATEROLE
            NOBYPASSRLS      -- explicit, even though it is the default
            INHERIT;
    END IF;
END
$$;

-- Connect + read the schema, but NOT create objects in it. DDL belongs to Alembic,
-- which connects as the owner. The application can only ever run DML.
GRANT CONNECT ON DATABASE school_manage_db TO sms_app;
GRANT USAGE ON SCHEMA public TO sms_app;
REVOKE CREATE ON SCHEMA public FROM sms_app;

-- Future tables created by migrations automatically grant DML to sms_app, so a
-- new module cannot ship a table the app is unable to read. Note that RLS
-- policies still gate *which rows* those grants expose -- the grant is table-level
-- permission, the policy is row-level filtering. Both are required.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sms_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sms_app;
