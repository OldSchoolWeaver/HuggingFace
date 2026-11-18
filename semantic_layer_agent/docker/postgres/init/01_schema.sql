-- Voltway EV fleet: schema. Runs once, when the Postgres volume is first created.
CREATE SCHEMA IF NOT EXISTS fleet;
COMMENT ON SCHEMA fleet IS 'Operational data for the Voltway electric sales fleet in Portugal.';

CREATE TABLE fleet.depots (
    depot_id    integer PRIMARY KEY,
    name        text    NOT NULL,
    city        text    NOT NULL,
    region      text    NOT NULL,
    opened_on   date    NOT NULL
);

CREATE TABLE fleet.vehicles (
    vehicle_id         integer PRIMARY KEY,
    vin                text    NOT NULL UNIQUE,
    make               text    NOT NULL,
    model              text    NOT NULL,
    model_year         integer NOT NULL,
    battery_kwh        numeric(5,1) NOT NULL,
    wltp_range_km      integer NOT NULL,
    depot_id           integer NOT NULL REFERENCES fleet.depots,
    status             text    NOT NULL CHECK (status IN ('active', 'in_maintenance', 'retired')),
    acquired_on        date    NOT NULL,
    purchase_price_eur numeric(10,2) NOT NULL
);

CREATE TABLE fleet.drivers (
    driver_id     integer PRIMARY KEY,
    full_name     text    NOT NULL,
    email         text    NOT NULL UNIQUE,
    depot_id      integer NOT NULL REFERENCES fleet.depots,
    hired_on      date    NOT NULL,
    sales_region  text    NOT NULL
);

CREATE TABLE fleet.trips (
    trip_id          integer PRIMARY KEY,
    vehicle_id       integer NOT NULL REFERENCES fleet.vehicles,
    driver_id        integer NOT NULL REFERENCES fleet.drivers,
    started_at       timestamp NOT NULL,
    ended_at         timestamp NOT NULL,
    distance_km      numeric(7,1) NOT NULL,
    energy_used_kwh  numeric(7,2) NOT NULL,
    purpose          text NOT NULL CHECK (purpose IN ('client_visit', 'delivery', 'depot_transfer', 'training'))
);

CREATE TABLE fleet.charging_sessions (
    session_id    integer PRIMARY KEY,
    vehicle_id    integer NOT NULL REFERENCES fleet.vehicles,
    network       text    NOT NULL,
    charger_type  text    NOT NULL CHECK (charger_type IN ('AC', 'DC')),
    started_at    timestamp NOT NULL,
    ended_at      timestamp NOT NULL,
    energy_kwh    numeric(7,2) NOT NULL,
    cost_eur      numeric(8,2) NOT NULL
);

CREATE TABLE fleet.maintenance_events (
    event_id        integer PRIMARY KEY,
    vehicle_id      integer NOT NULL REFERENCES fleet.vehicles,
    event_date      date    NOT NULL,
    category        text    NOT NULL CHECK (category IN ('tyres', 'brakes', 'software_update', 'battery_check', 'bodywork', 'scheduled_service')),
    cost_eur        numeric(8,2) NOT NULL,
    downtime_hours  numeric(5,1) NOT NULL
);

CREATE INDEX ON fleet.trips (vehicle_id, started_at);
CREATE INDEX ON fleet.trips (driver_id);
CREATE INDEX ON fleet.charging_sessions (vehicle_id, started_at);
CREATE INDEX ON fleet.maintenance_events (vehicle_id);

-- Table and column comments: DataHub ingests these as the starting descriptions.
COMMENT ON TABLE fleet.depots IS 'Fleet depots where vehicles are based and charged overnight.';
COMMENT ON TABLE fleet.vehicles IS 'One row per electric vehicle in the fleet, with its specs and home depot.';
COMMENT ON TABLE fleet.drivers IS 'Sales staff who drive fleet vehicles. Contains personal data.';
COMMENT ON TABLE fleet.trips IS 'One row per trip: distance driven and battery energy used.';
COMMENT ON TABLE fleet.charging_sessions IS 'One row per charging session: energy delivered and what it cost.';
COMMENT ON TABLE fleet.maintenance_events IS 'Maintenance and repair events, with cost and time off the road.';

COMMENT ON COLUMN fleet.vehicles.battery_kwh IS 'Usable battery capacity in kWh.';
COMMENT ON COLUMN fleet.vehicles.wltp_range_km IS 'Official WLTP range in km.';
COMMENT ON COLUMN fleet.vehicles.status IS 'active, in_maintenance or retired.';
COMMENT ON COLUMN fleet.drivers.email IS 'Work email address (personal data).';
COMMENT ON COLUMN fleet.trips.energy_used_kwh IS 'Battery energy consumed during the trip, in kWh.';
COMMENT ON COLUMN fleet.charging_sessions.network IS 'Charging operator, or Depot for the company''s own chargers.';
COMMENT ON COLUMN fleet.charging_sessions.cost_eur IS 'Amount paid for the session in EUR, including VAT.';
COMMENT ON COLUMN fleet.maintenance_events.downtime_hours IS 'Hours the vehicle was unavailable because of this event.';
