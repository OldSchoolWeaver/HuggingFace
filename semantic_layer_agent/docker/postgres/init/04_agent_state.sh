#!/bin/bash
# The agent's own state: a separate database (agent_state) where LangGraph saves conversations (checkpoints).
# Its role, agent_app, owns that database and nothing else: it can't read or change the fleet data.
#
# Runs on the first start of Postgres, like the other init scripts. It's also safe to run again, and
# scripts/setup.sh does, so an existing installation gets the database without being reset.
# (No 'set -u' here: the Postgres entrypoint may source this file instead of running it.)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_app') THEN
    CREATE ROLE agent_app LOGIN PASSWORD '${AGENT_DB_PASSWORD:-agent}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE agent_state OWNER agent_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'agent_state')\gexec
REVOKE CONNECT ON DATABASE agent_state FROM PUBLIC;
SQL
