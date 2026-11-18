#!/usr/bin/env bash
# Brings up the whole Voltway data ecosystem (one Compose project: Postgres, DuckDB, Cube, the MCP servers and
# DataHub) and fills the catalogue. Safe to run again.
#   ./scripts/setup.sh            everything
#   ./scripts/setup.sh catalog    only re-run the catalogue steps (stack already running)
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f docker/docker-compose.yml --env-file .env)

[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example (change the passwords if you like)"; }

# Add any setting a newer version of this project needs to an existing .env, without touching the others
ensure_env() {
  grep -q "^$1=" .env || { printf '%s=%s\n' "$1" "$2" >> .env; echo "Added $1 to .env"; }
}
ensure_env COMPOSE_PROFILES quickstart                 # turns on DataHub's services (they're in this profile)
ensure_env DATAHUB_VERSION v1.7.0
ensure_env DATAHUB_MAPPED_GMS_PORT 8080
ensure_env DATAHUB_MAPPED_FRONTEND_PORT 9002
ensure_env UI_INGESTION_DEFAULT_CLI_VERSION 1.7.0.20
# DataHub signs its access tokens with these; generated once per machine and kept in .env
ensure_env DATAHUB_TOKEN_SERVICE_SIGNING_KEY "$(openssl rand -hex 32)"
ensure_env DATAHUB_TOKEN_SERVICE_SALT "$(openssl rand -hex 32)"

set -a; . ./.env; set +a

# Remove every network named datahub_network, by id: an interrupted run can leave one behind (or two with the same
# name), and containers then fail with "network datahub_network not found".
remove_stale_networks() {
  for id in $(docker network ls -q --filter name='^datahub_network$'); do
    docker network rm "$id" >/dev/null 2>&1 || true
  done
}

docker info >/dev/null 2>&1 || { echo "❌ Docker isn't running: start Docker Desktop first."; exit 1; }
version="$(docker compose version --short | sed 's/^v//')"
major="${version%%.*}"; rest="${version#*.}"; minor="${rest%%.*}"
if [ "$major" -lt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -lt 20 ]; }; then
  echo "❌ Docker Compose $version is too old: 2.20 or newer is needed (update Docker Desktop)."; exit 1
fi

if [ "${1:-}" != "catalog" ]; then
  # DataHub used to be started by `datahub docker quickstart` as a separate Compose project ("datahub"), which
  # owns the datahub_network network and the datahub_* volumes. Remove that setup so this project can create them
  # as its own. DataHub's catalogue is rebuilt by steps 3-4 below, so nothing is lost.
  owner() { docker "$1" inspect "$2" --format '{{index .Labels "com.docker.compose.project"}}' 2>/dev/null || true; }
  old_setup=""
  [ -n "$(docker ps -aq --filter label=com.docker.compose.project=datahub)" ] && old_setup=yes
  for vol in datahub_mysqldata datahub_osdata datahub_broker; do
    o="$(owner volume "$vol")"; [ -n "$o" ] && [ "$o" != "voltway" ] && old_setup=yes
  done
  o="$(owner network datahub_network)"; [ -n "$o" ] && [ "$o" != "voltway" ] && old_setup=yes
  if [ -n "$old_setup" ]; then
    echo "━━ Removing the old separate DataHub setup (its catalogue is rebuilt below; Postgres data is kept)"
    "${COMPOSE[@]}" down --remove-orphans
    docker compose -p datahub down --remove-orphans --volumes
    docker volume rm datahub_mysqldata datahub_osdata datahub_broker >/dev/null 2>&1 || true
    remove_stale_networks
  fi

  echo "━━ 1/4 Starting every service (the first start downloads a few GB and takes several minutes)"
  if ! "${COMPOSE[@]}" up -d --build; then
    # Containers left over from an interrupted run can point at a network that no longer exists:
    # recreate them (volumes, and so all data, are kept) and try once more.
    echo "━━ Retrying with fresh containers and network (data is kept)"
    "${COMPOSE[@]}" down --remove-orphans
    remove_stale_networks
    "${COMPOSE[@]}" up -d --build
  fi
fi

echo "━━ 2/4 Waiting until every service answers"
uv run python scripts/check_stack.py --wait 900
# The agent_state database (saved conversations) is created on Postgres's first start. Run its script again so an
# installation that predates it gets it too; the script skips whatever already exists.
"${COMPOSE[@]}" exec -T postgres bash /docker-entrypoint-initdb.d/04_agent_state.sh >/dev/null
echo "   agent_state database ready (saved conversations)"

echo "━━ 3/4 Catalogue: business glossary, then Postgres tables, columns and profiles"
uv run datahub ingest -c catalog/glossary_recipe.yml
uv run datahub ingest -c catalog/postgres_recipe.yml

echo "━━ 4/4 Catalogue: descriptions, tags, glossary terms, the energy_prices file and the Cube models"
uv run python catalog/enrich_catalog.py

"${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
cat <<MSG

✅ Ready
   DataHub     http://localhost:${DATAHUB_MAPPED_FRONTEND_PORT:-9002}   (user datahub / datahub)
   Cube        http://localhost:${CUBE_PORT:-4001}   (Playground)
   Postgres    localhost:${POSTGRES_PORT:-5432}  db voltway, user analyst (read-only)
               localhost:${POSTGRES_PORT:-5432}  db agent_state, user agent_app (the agent's saved conversations)
   Agent app   uv run python app.py
   Services    docker compose -f docker/docker-compose.yml --env-file .env ps
MSG
