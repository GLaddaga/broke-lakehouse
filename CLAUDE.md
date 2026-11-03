# The Broke Lakehouse

Cheap, reproducible lakehouse stack: dlt → dbt / DuckDB + DuckLake → Tigris, orchestrated by Prefect.

## Current state

**Nothing is built yet.** The repo contains this file and `docs/`. Everything below describes the target — do not assume any file, table, schema or deployment named here exists. Check before referencing.

See @docs/roadmap.md for the build order and the known risks.

## Stack

- **dlt** — ingestion. Writes to Tigris via the `ducklake` destination (not plain `filesystem`).
- **Tigris (S3-compatible)** — object storage for DuckLake's Parquet data files.
- **Neon (Postgres)** — DuckLake catalog (schemas, snapshots, file stats). Load-bearing for every query, not just orchestration.
- **dbt** — transformation, via `dbt-duckdb` adapter attached to the DuckLake catalog.
- **Infisical** — all secrets (Tigris keys, Neon conn string, Prefect API key). Nothing hardcoded, nothing committed.
- **Prefect Cloud (free/Hobby tier, serverless work pool)** — orchestrator. One flow: `run_dlt` → `run_dbt`. Scheduled via Prefect deployment, not cron in code.
- **Podman** — local development environment. No venv.

## Project Structure

Target layout. A data platform monorepo with three components sharing one set of dependencies:

```
the-broke-lakehouse/
├── requirements.txt            # shared dependencies for ingest, transform, and orchestrate
├── Containerfile               # local dev environment; installs from requirements.txt
│
├── ingest/                     # dlt project — extracts raw data into the warehouse
│   ├── sources/                # source definitions (API, DB connectors, etc.)
│   ├── pipelines/              # dlt pipeline definitions
│   └── dlt.config.toml
│
├── transform/                  # dbt project — models raw data into staging/marts
│   ├── models/
│   │   ├── staging/
│   │   └── marts/
│   ├── dbt_project.yml
│   └── profiles.yml
│
├── orchestrate/                # Prefect project — schedules and chains the above
│   ├── flows/
│   │   ├── ingest_flow.py      # wraps the dlt pipeline as a Prefect flow
│   │   ├── transform_flow.py   # wraps dbt run as a Prefect flow
│   │   └── pipeline_flow.py    # top-level flow chaining ingest -> transform
│   └── prefect.yaml            # deployment config (work pool, schedule, build/pull steps)
│
├── docs/
└── README.md
```

## Conventions

**Environment**
- One `requirements.txt` at the repo root for all three projects — one environment for the whole platform.
- Local development runs in a Podman container that mounts the repo. No venv, no host-level installs.
- The Containerfile installs from `requirements.txt` and pins nothing of its own. Prefect's managed work pool installs from that same file at run time and cannot take a custom image, so `requirements.txt` is the only place dependencies are declared — anything pinned solely in the Containerfile drifts from what actually runs in the cloud.

**Naming**
- dlt loads into a `raw` dataset. Nothing else writes there.
- Staging models: `stg_<source>__<entity>`. Marts: `fct_<entity>` / `dim_<entity>`.
- One DuckLake catalog, one schema per layer.

**Materializations**
- Staging: views. They are thin renames and casts; materializing them buys nothing and costs storage plus write requests.
- Marts: tables.
- Incremental only where a full rebuild has become genuinely slow or expensive. Not by default — incremental models cost more to reason about than they usually save at this size.

**Dev/prod isolation**
- Separate dlt dataset and dbt target for local work, against the *same* Neon catalog. This keeps local runs from stomping scheduled ones without violating the one-Postgres rule.

**No dbt tests**
- Deliberately skipped to save compute. Every test is another query against the Neon-backed catalog, and this project optimizes for cost.
- Do not add a `schema.yml` full of `not_null` / `unique` as a "helpful" improvement. Correctness gets checked by hand when a model is written.

**Data flow**
- `orchestrate/` calls into `ingest/` and `transform/` directly — same environment, so imports or CLI calls both work.
- Data passes between stages via the warehouse only. No in-memory handoff between dlt and dbt.
- Deployments are defined per-flow in `prefect.yaml` (`ingest-only`, `transform-only`, `full-pipeline`) so each can be scheduled or triggered independently.

## Working with Claude

- **Default to suggestion and review.** Propose the change in chat; don't write files unless asked. I do the development.
- **When asked to write, write the minimum that works.** The `ponytail` plugin is enabled — that is the house style here, not an occasional mode.
- Prefer amending what exists over adding a layer on top of it.
- Flag over-engineering in review even when the code is correct.
- Don't assert that something works without having run it. This stack has several integration points that are plausible on paper and unproven in practice — see the risks in the roadmap.

## Hard rules

- I do the development. Claude supports with suggestions and code reviews.
- dlt writes only to raw tables. dbt reads raw, writes staging/marts, all within the same DuckLake catalog.
- No secret hardcoded or in a committed file. Everything pulled from Infisical at runtime.
  - **One sanctioned exception:** the Infisical machine identity (Universal Auth client ID/secret) lives in a Prefect Secret block, because the serverless worker needs a credential in order to fetch credentials. The flow uses it to pull everything else from Infisical at run time. Nothing else is allowed to live outside Infisical.
- No always-on process, no laptop-as-scheduler. Prefect's serverless work pool runs the flow on schedule; nothing runs in between.
- Don't add a second Postgres for anything else. One Neon instance, one DuckLake catalog, one schema per concern if needed.
