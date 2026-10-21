# The Broke Lakehouse

## Manifesto
Cheap, reproducible lakehouse stack: dlt → dbt / DuckDB + DuckLake → S3-compatible object storage, orchestrated with an
open-source tool (e.g. Prefect, Airflow). Full story @docs/manifesto.md.

## Current state
@docs/roadmap.md for the build status, order and known risks.

## Stack

- **dlt** — ingestion. Writes to object storage via the `ducklake` destination.
- **S3-compatible object storage** — DuckLake's Parquet data files. Any provider that speaks S3 with static access keys; Tigris today, R2 or plain S3 by changing values in Infisical, not code.
- **Neon (Postgres)** — DuckLake catalog (schemas, snapshots, file stats).
- **dbt** — transformation, via `dbt-duckdb` adapter attached to the DuckLake catalog.
- **Infisical** — the data credentials (object-storage keys, Neon conn string).
- **Prefect Cloud (free/Hobby tier, serverless work pool)** — orchestrator.
- **Podman** — local development environment.

## Project Structure

Target layout. A data platform monorepo with three components sharing one set of dependencies:

```
the-broke-lakehouse/
├── requirements.txt            # shared dependencies for ingest, transform, and orchestrate
├── Containerfile               # local dev environment; installs from requirements.txt
├── .env.example                # Infisical bootstrap credential: names, no values
├── utils/                    # shared support code for all three components
│   └── secrets/                # one module per secret manager, same get_secrets()
│
├── ingest/                     # dlt project — extracts raw data into the warehouse
│   ├── sources/                # source definitions (API, DB connectors, etc.)
│   └── pipelines/              # dlt pipeline definitions
│
├── transform/                  # dbt project — models raw into bronze/silver/gold
│   ├── models/
│   ├── dbt_project.yml
│   └── profiles.yml
│
├── orchestrate/                # Prefect project — schedules and chains the above
│   ├── flows/
│   └── prefect.yaml            # deployment config (work pool, schedule, build/pull steps)
│
├── docs/
└── README.md
```

## Conventions
@docs/conventions.md for the layers, naming, environment and data-flow rules.

## DevOps
<!-- TBD -->

## Development Rules
- Claude defaults to suggestion and review, proposes changes in chat and does not write files unless asked. The human does the development.
- Prefer amending what exists over adding a layer on top of it.
- Flag over-engineering in review even when the code is correct.
- No secret hardcoded or in a committed file. Everything pulled from Infisical at runtime. The Infisical machine identity (Universal Auth client ID/secret, plus the project ID) — in Prefect a Secret block, locally a gitignored `.env` injected by `podman --env-file`. `.env.example` carries the structure with no values.
- No always-on process, no laptop-as-scheduler. Prefect's serverless work pool runs the flow on schedule; nothing runs in between.
