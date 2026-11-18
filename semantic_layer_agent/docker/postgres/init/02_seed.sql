-- Voltway EV fleet: dummy data, generated in SQL so the container needs no extra files.
-- setseed makes random() repeatable, so every fresh database gets the same data.
SELECT setseed(0.42);

INSERT INTO fleet.depots VALUES
    (1, 'Lisboa Parque das Nacoes', 'Lisboa',  'Lisboa',  '2022-03-01'),
    (2, 'Porto Matosinhos',         'Porto',   'Norte',   '2022-06-15'),
    (3, 'Coimbra Eiras',            'Coimbra', 'Centro',  '2023-02-01'),
    (4, 'Faro Aeroporto',           'Faro',    'Algarve', '2023-09-01');

-- Six models, with battery, range, price and real-world consumption (kWh/100 km) used below
CREATE TEMP TABLE models (m int, make text, model text, battery numeric, range_km int, price numeric, kwh_per_100km numeric);
INSERT INTO models VALUES
    (0, 'Tesla',      'Model Y Long Range',   75.0, 533, 49990, 16.5),
    (1, 'Volkswagen', 'ID.4 Pro',             77.0, 520, 46990, 18.0),
    (2, 'Renault',    'Megane E-Tech',        60.0, 450, 41990, 16.0),
    (3, 'Peugeot',    'e-208',                51.0, 400, 33990, 15.0),
    (4, 'Kia',        'EV6',                  77.4, 528, 50990, 17.5),
    (5, 'Ford',       'Mustang Mach-E',       72.0, 440, 52990, 19.0);

INSERT INTO fleet.vehicles
SELECT v,
       upper(left(md.make, 3)) || lpad((7700000 + v * 7919)::text, 14, '0'),
       md.make, md.model,
       2023 + (v % 3),
       md.battery, md.range_km,
       ((v - 1) % 4) + 1,
       CASE WHEN v IN (7, 23) THEN 'in_maintenance' WHEN v = 40 THEN 'retired' ELSE 'active' END,
       DATE '2023-01-15' + v * 20,
       md.price - (v % 5) * 500
FROM generate_series(1, 40) v
JOIN models md ON md.m = v % 6;

CREATE TEMP TABLE first_names (i int, n text);
INSERT INTO first_names SELECT row_number() OVER () - 1, n FROM unnest(ARRAY[
    'Ana','Joao','Maria','Pedro','Ines','Tiago','Beatriz','Rui','Sofia','Miguel','Catarina','Andre','Marta',
    'Ricardo','Joana','Nuno','Rita','Bruno','Carla','Diogo','Helena','Filipe','Patricia','Goncalo','Teresa']) n;
CREATE TEMP TABLE last_names (i int, n text);
INSERT INTO last_names SELECT row_number() OVER () - 1, n FROM unnest(ARRAY[
    'Silva','Santos','Ferreira','Pereira','Oliveira','Costa','Rodrigues','Martins','Jesus','Sousa',
    'Fernandes','Goncalves','Gomes','Lopes','Marques','Alves','Almeida','Ribeiro','Pinto','Carvalho']) n;

INSERT INTO fleet.drivers
SELECT d,
       f.n || ' ' || l.n,
       lower(f.n) || '.' || lower(l.n) || d || '@voltway.example',
       ((d - 1) % 4) + 1,
       DATE '2022-04-01' + d * 23,
       (ARRAY['Lisboa','Norte','Centro','Algarve'])[((d - 1) % 4) + 1]
FROM generate_series(1, 50) d
JOIN first_names f ON f.i = d % 25
JOIN last_names  l ON l.i = (d * 7) % 20;

-- Trips: Jan-Oct 2026, by the 39 vehicles still in service. Each trip's driver works at the vehicle's depot.
-- The CTE holds volatile random() calls, so Postgres computes it once (it never inlines volatile CTEs).
INSERT INTO fleet.trips
WITH r AS (
    SELECT g, random() rv, random() rd, random() rday, random() rhour, random() rdist, random() reff,
           random() rspeed, random() rpurpose
    FROM generate_series(1, 6000) g
), t AS (
    SELECT r.*, 1 + floor(rv * 39)::int AS vehicle_id,
           TIMESTAMP '2026-01-01' + floor(rday * 304)::int * INTERVAL '1 day'
                                  + (7 + rhour * 11) * INTERVAL '1 hour' AS started_at,
           round((5 + power(rdist, 1.5) * 180)::numeric, 1) AS distance_km
    FROM r
)
SELECT t.g,
       t.vehicle_id,
       v.depot_id + 4 * floor(t.rd * 12)::int,
       t.started_at,
       t.started_at + (t.distance_km / (35 + t.rspeed * 30)) * INTERVAL '1 hour',
       t.distance_km,
       round((t.distance_km * md.kwh_per_100km / 100 * (0.9 + t.reff * 0.25)
             * CASE WHEN extract(month FROM t.started_at) IN (1, 2, 12) THEN 1.12 ELSE 1 END)::numeric, 2),
       CASE WHEN t.rpurpose < 0.60 THEN 'client_visit' WHEN t.rpurpose < 0.80 THEN 'delivery'
            WHEN t.rpurpose < 0.95 THEN 'depot_transfer' ELSE 'training' END
FROM t
JOIN fleet.vehicles v ON v.vehicle_id = t.vehicle_id
JOIN models md ON md.make = v.make AND md.model = v.model;

-- Charging: about half at the company's depot chargers (AC, cheap), the rest on public DC networks.
-- Depot sessions pay the daily depot tariff, the same formula as data/energy_prices.csv for DuckDB.
INSERT INTO fleet.charging_sessions
WITH r AS (
    SELECT g, random() rv, random() rnet, random() rday, random() rhour, random() renergy, random() rprice,
           random() rpower
    FROM generate_series(1, 3000) g
), c AS (
    SELECT r.*, 1 + floor(rv * 39)::int AS vehicle_id,
           DATE '2026-01-01' + floor(rday * 304)::int AS day,
           CASE WHEN rnet < 0.55 THEN 'Depot' WHEN rnet < 0.70 THEN 'Galp Electric' WHEN rnet < 0.82 THEN 'EDP Comercial'
                WHEN rnet < 0.92 THEN 'Powerdot' ELSE 'Ionity' END AS network,
           round((12 + renergy * 50)::numeric, 2) AS energy_kwh
    FROM r
), priced AS (
    SELECT c.*,
           CASE network WHEN 'Depot' THEN round((0.14 + 0.025 * sin(2 * pi() * extract(doy FROM day) / 182.5)
                                                 + 0.01 * ((extract(doy FROM day)::int * 37) % 7) / 7.0)::numeric, 4)
                        WHEN 'Galp Electric' THEN 0.45 WHEN 'EDP Comercial' THEN 0.42
                        WHEN 'Powerdot' THEN 0.39 ELSE 0.59 END AS eur_per_kwh,
           CASE WHEN network = 'Depot' THEN 'AC' ELSE 'DC' END AS charger_type,
           day + CASE WHEN network = 'Depot' THEN (18 + rhour * 3) ELSE (8 + rhour * 10) END * INTERVAL '1 hour' AS started_at
    FROM c
)
SELECT g, vehicle_id, network, charger_type, started_at,
       started_at + energy_kwh / CASE WHEN charger_type = 'AC' THEN 11 ELSE 50 + rpower * 100 END * INTERVAL '1 hour',
       energy_kwh,
       round((energy_kwh * eur_per_kwh * CASE WHEN network = 'Depot' THEN 1 ELSE 0.95 + rprice * 0.1 END
             + CASE WHEN network = 'Depot' THEN 0 ELSE 0.30 END)::numeric, 2)
FROM priced;

INSERT INTO fleet.maintenance_events
WITH r AS (
    SELECT g, random() rv, random() rday, random() rcat, random() rcost, random() rdown
    FROM generate_series(1, 140) g
), m AS (
    SELECT r.*, 1 + floor(rv * 40)::int AS vehicle_id,
           CASE WHEN rcat < 0.30 THEN 'scheduled_service' WHEN rcat < 0.50 THEN 'tyres' WHEN rcat < 0.65 THEN 'software_update'
                WHEN rcat < 0.80 THEN 'brakes' WHEN rcat < 0.92 THEN 'battery_check' ELSE 'bodywork' END AS category
    FROM r
)
SELECT g, vehicle_id,
       DATE '2026-01-01' + floor(rday * 304)::int,
       category,
       round(CASE category WHEN 'scheduled_service' THEN 180 + rcost * 120 WHEN 'tyres' THEN 450 + rcost * 350
                           WHEN 'software_update' THEN 0 WHEN 'brakes' THEN 250 + rcost * 300
                           WHEN 'battery_check' THEN 90 + rcost * 60 ELSE 300 + rcost * 2200 END::numeric, 2),
       round(CASE category WHEN 'software_update' THEN 0.5 + rdown WHEN 'bodywork' THEN 24 + rdown * 120
                           WHEN 'tyres' THEN 2 + rdown * 4 ELSE 3 + rdown * 10 END::numeric, 1)
FROM m;

ANALYZE;
