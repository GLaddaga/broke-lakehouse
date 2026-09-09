# Roadmap

Build order from empty repo to a scheduled pipeline. Each milestone lists what "done" means and which doc it produces.

**Current position: milestone 1 under rework.**

## 0 — Skeleton

Directory tree from CLAUDE.md, `requirements.txt`, `Containerfile`, `.gitignore`, first commit.

Development happens in a Podman container. The container mounts the repo and carries the whole environment — Python deps, the dlt/dbt/Prefect CLIs, and the DuckDB extensions.

Done when: `podman build` produces an image, and a shell in that container can run `dlt --version` and `dbt --version` against the mounted repo.

Note the asymmetry to keep in mind from here on: the container defines the *local* environment, but Prefect's managed work pool installs from `requirements.txt` at run time and does not take a custom image. `requirements.txt` stays the single source of truth for dependencies, and the Containerfile installs from it rather than pinning anything of its own — otherwise local and serverless drift apart silently.

## 1 — Secrets

Secrets are fetched through a thin Python wrapper of the Infisical SDK (`utils/secrets/infisical.py`). The module does not work as the CLI, just creates functions that will be used in Python.

Done when: `utils/secrets/infisical.py` is unit tested via `pytest` in `test/secrets` folder on mock secrets in `Development` Infisical environment.

Produces: `docs/secrets.md`.

## 2 — Catalog + storage spike

Neon project, Tigris bucket, and a throwaway script proving DuckDB can attach the DuckLake catalog on Neon with the data path on Tigris, then write and read back one Parquet file.

Done when: a table written in one process is readable from a second, fresh process — which proves the catalog, not just local state.

Produces: `docs/architecture.md`.

This is the foundation spike. Nothing downstream is worth attempting until it passes.

## 3 — First dlt pipeline

One source landing in the `raw` dataset via the `ducklake` destination.

Done when: `raw` contains the loaded table and a second run is idempotent (no duplicate rows under the chosen write disposition).

## 4 — dbt attached

`dbt-duckdb` attached to the same DuckLake catalog, building one staging model from a `raw` table.

Done when: `dbt run` builds the model and the output is queryable from a plain DuckDB session against the same catalog.

No tests — see the conventions in CLAUDE.md.

## 5 — Prefect flows

`ingest_flow` and `transform_flow` wrapping milestones 3 and 4, plus `pipeline_flow` chaining them. Run locally, reporting to Prefect Cloud.

Done when: `pipeline_flow` completes locally end to end and the run appears in Prefect Cloud.

## 6 — Serverless deployment

Managed work pool, machine-identity bootstrap for secrets, deployments and schedules.

Done when: a scheduled run completes on Prefect's infrastructure with nothing running locally.

Produces: `docs/operations.md`.

## 7 — Maintenance

Snapshot expiry, old-file cleanup, first look at actual spend across Neon, Tigris and Prefect.

Done when: there is a scheduled cleanup and a number for what the stack costs per month.

Produces: `docs/gotchas.md`, once there is real operational experience to write down.

---

## Known risks

Verified during planning (2026-08-23). Each is attached to the milestone where it will bite.

**Milestone 4 is the riskiest step in this plan.** `dbt-duckdb`'s documented DuckLake support (`is_ducklake: true`) is MotherDuck-specific. Attaching a *self-hosted* DuckLake — Neon catalog, Tigris data path — has to go through the generic `attach:` / `extensions:` / `secrets:` mechanism and is not a documented path. Treat it as a spike, not a config task, and budget accordingly.
→ [dbt-duckdb README](https://github.com/duckdb/dbt-duckdb/blob/master/README.md)

**dlt's own dbt runner does not support the DuckLake destination.** This constrains only dlt's built-in dbt helper, not `dbt-duckdb` invoked separately — which is the design here. Noted so nobody reaches for the helper and concludes the stack is broken.
→ [dlt DuckLake destination](https://dlthub.com/docs/dlt-ecosystem/destinations/ducklake)

**Prefect Cloud's free tier allows 1 concurrent flow run per workspace** across managed pools (5 pools maximum). The planned `ingest-only` / `transform-only` / `full-pipeline` deployments therefore cannot overlap — stagger the schedules in milestone 6.
→ [Prefect managed infrastructure](https://docs.prefect.io/3.0/deploy/infrastructure-examples/managed)

**Neon free-tier compute autosuspends.** The catalog is load-bearing for every query, so the first query after idle pays a cold start. Relevant to flow timeouts in milestone 6.

**Tigris is a single global endpoint with access-key pairs only** — no STS, no session tokens. This shapes how DuckDB's S3 secret is configured in milestone 2.
→ [Tigris dlt guide](https://www.tigrisdata.com/docs/guides/dlt/)
