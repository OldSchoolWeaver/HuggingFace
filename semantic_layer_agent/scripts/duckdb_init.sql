INSTALL postgres; LOAD postgres;
ATTACH 'host=localhost port=5433 dbname=voltway user=analyst password=analyst'
    AS voltway (TYPE postgres, READ_ONLY);

CREATE SCHEMA files;
CREATE VIEW files.energy_prices AS
    SELECT * FROM read_csv('docker/duckdb/data/energy_prices.csv', header = true);