# The Broke Lakehouse

Cheap, reproducible lakehouse stack: dlt → dbt / DuckDB + DuckLake → Tigris, orchestrated by Prefect.

## Current state

@docs/roadmap.md for the build status, order and known risks.

## Stack

- **dlt** — ingestion. Writes to Tigris via the `ducklake` destination (not plain `filesystem`).
- **Tigris (S3-compatible)** — object storage for DuckLake's Parquet data files.
- **Neon (Postgres)** — DuckLake catalog (schemas, snapshots, file stats). Load-bearing for every query, not just orchestration.
- **dbt** — transformation, via `dbt-duckdb` adapter attached to the DuckLake catalog.
- **Infisical** — the data credentials (Tigris keys, Neon conn string). Nothing hardcoded, nothing committed. The bootstrap credential rides in a gitignored `.env`.
- **Prefect Cloud (free/Hobby tier, serverless work pool)** — orchestrator. One flow: `run_dlt` → `run_dbt`. Scheduled via Prefect deployment, not cron in code.
- **Podman** — local development environment. No venv.

## Project Structure

Target layout. A data platform monorepo with three components sharing one set of dependencies:

```
the-broke-lakehouse/
├── requirements.txt            # shared dependencies for ingest, transform, and orchestrate
├── Containerfile               # local dev environment; installs from requirements.txt
├── .env.example                # Infisical bootstrap credential: names, no values
├── helpers/                    # shared support code for all three components
│   └── infisical_env.py        # pulls secrets from Infisical into the environment
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

**Secrets**
- `infisical_env.load()` copies every secret in the Infisical project into `os.environ`. Import it in a flow; use `python -m helpers.infisical_env <cmd>` to wrap a CLI like `dbt run`.
- It lives in `helpers/` rather than in one component because all three need it. Imports resolve from the repo root, which is the container's workdir.
- `setdefault`, not `update` — an already-exported variable wins, so a single secret can be overridden locally without touching Infisical.
- `.env` carries the three `INFISICAL_*` bootstrap variables and nothing else.
- The env-var contract lives in @docs/secrets.md. That file is the list of names; adding a secret means adding it there.

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
  - **The sanctioned exception is a class, not an item:** a credential needed to *reach* the layer that serves credentials cannot come from that layer. Two qualify. The Infisical machine identity (Universal Auth client ID/secret, plus the project ID) — in Prefect a Secret block, locally a gitignored `.env` injected by `podman --env-file`.
  - `.env.example` carries the names and no values.
- No always-on process, no laptop-as-scheduler. Prefect's serverless work pool runs the flow on schedule; nothing runs in between.
- Don't add a second Postgres for anything else. One Neon instance, one DuckLake catalog, one schema per concern if needed.
