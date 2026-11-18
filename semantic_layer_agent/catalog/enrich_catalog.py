"""Adds business context to the DataHub catalogue, after the Postgres ingestion has created the datasets.

  - Postgres tables: rich descriptions (grain, keys, joins, how to query), column descriptions,
    tags, glossary terms and an owner
  - the energy_prices file that only DuckDB can query, as its own dataset
  - each Cube cube as a dataset with its measures and dimensions, and lineage to its Postgres table,
    so the catalogue shows which governed metrics exist and where they come from

Run from the project folder:  uv run python catalog/enrich_catalog.py
"""

import os
from pathlib import Path

import yaml
from datahub.sdk import CorpUserUrn, DataHubClient, Dataset, DatasetUrn, GlossaryTermUrn, TagUrn
from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT / ".env")
load_dotenv(PROJECT.parent / ".env")

GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
GMS_TOKEN = os.getenv("DATAHUB_GMS_TOKEN") or None
CUBE_MODEL_DIR = PROJECT / "cube" / "model"
OWNER = CorpUserUrn("datahub")

TERM = {name: GlossaryTermUrn(f"fleet.{name}") for name in
        ("energy_efficiency", "charging_cost_per_kwh", "public_charging_share", "fleet_size", "downtime", "depot_tariff")}
PERSONAL_DATA = GlossaryTermUrn("classification.personal_data")

HOW_TO_QUERY = (
    "\n\n**How to query**\n"
    "- SQL (DuckDB, federated with files): `voltway.fleet.{table}`\n"
    "- SQL (Postgres): `fleet.{table}`\n"
    "- Semantic layer (Cube): {cube}\n"
)

# Per Postgres table: description, tags, terms, and per column: description, terms, tags
TABLES = {
    "depots": {
        "description": "Fleet depots where vehicles are based and charged overnight. **Grain:** one row per depot. "
                       "**Key:** `depot_id`. Vehicles and drivers belong to one depot (`depot_id`).",
        "tags": ["dimension"], "cube": "cube `depots`",
        "columns": {
            "depot_id": ("Depot identifier.", [], []),
            "name": ("Depot name.", [], []),
            "city": ("City of the depot.", [], []),
            "region": ("Sales region served: Lisboa, Norte, Centro or Algarve.", [], []),
            "opened_on": ("Date the depot opened.", [], []),
        },
    },
    "vehicles": {
        "description": "Electric vehicles in the fleet. **Grain:** one row per vehicle. **Key:** `vehicle_id`. "
                       "Joins: `depot_id` -> depots. Fleet size counts only `status = 'active'` vehicles.",
        "tags": ["dimension"], "terms": ["fleet_size"], "cube": "cube `vehicles` (e.g. `vehicles.active_count`)",
        "columns": {
            "vehicle_id": ("Vehicle identifier.", [], []),
            "vin": ("Vehicle identification number.", [], []),
            "make": ("Manufacturer, e.g. Tesla, Volkswagen.", [], []),
            "model": ("Model name, e.g. ID.4 Pro.", [], []),
            "model_year": ("Model year.", [], []),
            "battery_kwh": ("Usable battery capacity in kWh.", [], []),
            "wltp_range_km": ("Official WLTP range in km (real-world range is lower, especially in winter).", [], []),
            "depot_id": ("Home depot of the vehicle. Joins to depots.depot_id.", [], []),
            "status": ("active, in_maintenance or retired. Only active vehicles count towards fleet size.", ["fleet_size"], []),
            "acquired_on": ("Date the vehicle joined the fleet.", [], []),
            "purchase_price_eur": ("Purchase price in EUR.", [], []),
        },
    },
    "drivers": {
        "description": "Sales staff who drive fleet vehicles. **Grain:** one row per driver. **Key:** `driver_id`. "
                       "Joins: `depot_id` -> depots. **Contains personal data** (name, email): aggregate by depot or "
                       "region in answers, and never show emails unless explicitly required.",
        "tags": ["dimension", "pii"], "terms": [], "cube": "cube `drivers` (email deliberately not exposed)",
        "columns": {
            "driver_id": ("Driver identifier.", [], []),
            "full_name": ("Driver's full name. Personal data.", [], ["pii"]),
            "email": ("Work email address. Personal data.", [], ["pii"]),
            "depot_id": ("Depot the driver works from. Joins to depots.depot_id.", [], []),
            "hired_on": ("Hiring date.", [], []),
            "sales_region": ("Sales region the driver covers.", [], []),
        },
    },
    "trips": {
        "description": "Trips driven by fleet vehicles in 2026. **Grain:** one row per trip. **Key:** `trip_id`. "
                       "Joins: `vehicle_id` -> vehicles, `driver_id` -> drivers. Energy efficiency (kWh/100 km) is "
                       "100 x SUM(energy_used_kwh) / SUM(distance_km), not an average of per-trip values.",
        "tags": ["fact"], "terms": ["energy_efficiency"], "cube": "cube `trips` (e.g. `trips.energy_per_100km`)",
        "columns": {
            "trip_id": ("Trip identifier.", [], []),
            "vehicle_id": ("Vehicle used. Joins to vehicles.vehicle_id.", [], []),
            "driver_id": ("Driver. Joins to drivers.driver_id.", [], []),
            "started_at": ("Trip start (local time, no time zone).", [], []),
            "ended_at": ("Trip end (local time, no time zone).", [], []),
            "distance_km": ("Distance driven in km.", ["energy_efficiency"], []),
            "energy_used_kwh": ("Battery energy consumed during the trip, in kWh.", ["energy_efficiency"], []),
            "purpose": ("client_visit, delivery, depot_transfer or training.", [], []),
        },
    },
    "charging_sessions": {
        "description": "Charging sessions in 2026. **Grain:** one row per session. **Key:** `session_id`. "
                       "Joins: `vehicle_id` -> vehicles. `network = 'Depot'` (AC) is the company's own chargers, paid "
                       "at the daily depot tariff (see files.energy_prices); the others are public DC networks.",
        "tags": ["fact"], "terms": ["charging_cost_per_kwh", "public_charging_share"],
        "cube": "cube `charging_sessions` (e.g. `charging_sessions.cost_per_kwh`, `charging_sessions.public_charging_share`)",
        "columns": {
            "session_id": ("Charging session identifier.", [], []),
            "vehicle_id": ("Vehicle charged. Joins to vehicles.vehicle_id.", [], []),
            "network": ("Charging operator: Depot, Galp Electric, EDP Comercial, Powerdot or Ionity.", ["public_charging_share"], []),
            "charger_type": ("AC (depot) or DC (public fast charging).", ["public_charging_share"], []),
            "started_at": ("Session start (local time).", [], []),
            "ended_at": ("Session end (local time).", [], []),
            "energy_kwh": ("Energy delivered in kWh.", ["charging_cost_per_kwh"], []),
            "cost_eur": ("Amount paid in EUR, including VAT.", ["charging_cost_per_kwh"], []),
        },
    },
    "maintenance_events": {
        "description": "Maintenance and repairs in 2026. **Grain:** one row per event. **Key:** `event_id`. "
                       "Joins: `vehicle_id` -> vehicles.",
        "tags": ["fact"], "terms": ["downtime"], "cube": "cube `maintenance_events`",
        "columns": {
            "event_id": ("Maintenance event identifier.", [], []),
            "vehicle_id": ("Vehicle serviced. Joins to vehicles.vehicle_id.", [], []),
            "event_date": ("Date of the event.", [], []),
            "category": ("tyres, brakes, software_update, battery_check, bodywork or scheduled_service.", [], []),
            "cost_eur": ("Cost in EUR.", [], []),
            "downtime_hours": ("Hours the vehicle was off the road.", ["downtime"], []),
        },
    },
}


def postgres_urn(table: str) -> DatasetUrn:
    return DatasetUrn(platform="postgres", name=f"voltway.fleet.{table}")


def enrich_postgres_tables(client: DataHubClient) -> None:
    for table, meta in TABLES.items():
        try:
            dataset = client.entities.get(postgres_urn(table))
        except Exception as error:  # noqa: BLE001
            raise SystemExit(f"{postgres_urn(table)} isn't in DataHub yet: run the Postgres ingestion first ({error})")
        dataset.set_description(meta["description"] + HOW_TO_QUERY.format(table=table, cube=meta["cube"]))
        for tag in meta["tags"]:
            dataset.add_tag(TagUrn(tag))
        for term in meta.get("terms", []):
            dataset.add_term(TERM[term])
        if "pii" in meta["tags"]:
            dataset.add_term(PERSONAL_DATA)
        dataset.add_owner(OWNER)
        dataset.set_custom_properties({"duckdb_table": f"voltway.fleet.{table}", "semantic_layer": meta["cube"]})
        for column, (description, terms, tags) in meta["columns"].items():
            field = dataset[column]
            field.set_description(description)
            for term in terms:
                field.add_term(TERM[term])
            for tag in tags:
                field.add_tag(TagUrn(tag))
                if tag == "pii":
                    field.add_term(PERSONAL_DATA)
        client.entities.update(dataset)
        print(f"✅ postgres  voltway.fleet.{table}")


def register_energy_prices(client: DataHubClient) -> None:
    dataset = Dataset(
        platform="duckdb",
        name="memory.files.energy_prices",
        display_name="energy_prices",
        description="Daily depot electricity tariff and grid CO2 intensity for Portugal, 1 Jan - 31 Oct 2026. "
                    "**Grain:** one row per day. A CSV file, queryable **only through DuckDB** as `files.energy_prices`; "
                    "join on `day` = `started_at::DATE` to the Postgres tables attached as `voltway.fleet.*`.",
        schema=[
            ("day", "DATE", "Calendar day."),
            ("depot_tariff_eur_per_kwh", "DECIMAL(6,4)", "Price paid per kWh at depot chargers that day, EUR."),
            ("grid_co2_g_per_kwh", "INTEGER", "Average CO2 intensity of the Portuguese grid that day, g/kWh."),
        ],
        tags=[TagUrn("reference-data")],
        terms=[TERM["depot_tariff"]],
        owners=[OWNER],
        custom_properties={"duckdb_table": "files.energy_prices", "file": "docker/duckdb/data/energy_prices.csv"},
    )
    client.entities.upsert(dataset)
    print("✅ duckdb    files.energy_prices")


def register_cubes(client: DataHubClient) -> None:
    for path in sorted(CUBE_MODEL_DIR.glob("*.yml")):
        for cube in yaml.safe_load(path.read_text())["cubes"]:
            name = cube["name"]
            fields = [(f"{name}.{m['name']}", f"measure: {m['type']}", m.get("description", "").strip())
                      for m in cube.get("measures", [])]
            fields += [(f"{name}.{d['name']}", f"dimension: {d['type']}", d.get("description", "").strip())
                       for d in cube.get("dimensions", [])]
            dataset = Dataset(
                platform="cube",
                name=name,
                description=f"{cube.get('description', '').strip()}\n\nCube semantic-layer model with governed metrics "
                            f"(measures) and dimensions. Query it with the Cube tools, e.g. "
                            f"`{{\"measures\": [\"{fields[0][0]}\"]}}`. Defined in `cube/model/{path.name}`.",
                subtype="Semantic Model",
                schema=fields,
                tags=[TagUrn("semantic-layer")],
                owners=[OWNER],
                upstreams=[postgres_urn(cube["sql_table"].split(".")[-1])],
                custom_properties={"cube": name, "model_file": f"cube/model/{path.name}"},
            )
            client.entities.upsert(dataset)
            print(f"✅ cube      {name} ({len(fields)} members)")


def main() -> None:
    client = DataHubClient(server=GMS_URL, token=GMS_TOKEN)
    enrich_postgres_tables(client)
    register_energy_prices(client)
    register_cubes(client)
    print(f"\nDone. Browse it at http://localhost:{os.getenv('DATAHUB_MAPPED_FRONTEND_PORT', '9002')}")


if __name__ == "__main__":
    main()
