#!/bin/bash
# Roles: analyst (read-only: agent, MCP servers, Cube, DuckDB) and catalog_reader (DataHub ingestion).
# (No 'set -u' here: the Postgres entrypoint may source this file instead of running it.)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE analyst LOGIN PASSWORD '${ANALYST_PASSWORD:-analyst}';
GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO analyst;
GRANT USAGE ON SCHEMA fleet TO analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA fleet TO analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA fleet GRANT SELECT ON TABLES TO analyst;
ALTER ROLE analyst SET default_transaction_read_only = on;
ALTER ROLE analyst SET statement_timeout = '30s';

-- DataHub ingestion: can read the data and profile it (profiling needs temporary tables, which a
-- read-only transaction can't create), but has no write access to the fleet schema.
CREATE ROLE catalog_reader LOGIN PASSWORD '${CATALOG_READER_PASSWORD:-catalog}';
GRANT CONNECT, TEMPORARY ON DATABASE "$POSTGRES_DB" TO catalog_reader;
GRANT USAGE ON SCHEMA fleet TO catalog_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA fleet TO catalog_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA fleet GRANT SELECT ON TABLES TO catalog_reader;
SQL
