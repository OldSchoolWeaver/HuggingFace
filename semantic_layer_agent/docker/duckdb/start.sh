#!/bin/sh
# Writes the DuckDB init SQL (with the password from the environment), then starts the MCP server.
set -eu
cat > /tmp/init.sql <<SQL
LOAD postgres;
ATTACH 'host=${PGHOST} port=${PGPORT} dbname=${PGDATABASE} user=${PGUSER} password=${PGPASSWORD}'
    AS voltway (TYPE postgres, READ_ONLY);
CREATE SCHEMA files;
CREATE VIEW files.energy_prices AS
    SELECT * FROM read_csv('/data/energy_prices.csv', header = true,
                           columns = {'day': 'DATE', 'depot_tariff_eur_per_kwh': 'DECIMAL(6,4)', 'grid_co2_g_per_kwh': 'INTEGER'});
COMMENT ON VIEW files.energy_prices IS 'Daily depot electricity tariff (EUR/kWh) and grid CO2 intensity (g/kWh), Jan-Oct 2026.';
SQL
# In-memory DuckDB must be started with --read-write (DuckDB limitation); Postgres itself is attached
# READ_ONLY and the analyst role is read-only, so the fleet data can't be changed from here.
exec mcp-server-motherduck --transport http --host 0.0.0.0 --port 8000 \
     --read-write --init-sql /tmp/init.sql --max-rows 500 --query-timeout 60
