# Roadmap

Build order from empty repo to a scheduled pipeline. Each milestone lists what "done" means and which doc it produces.

**Current position: milestone 4 done against the TPC-H load; milestone 3 (`ingest/pipelines/tpch.py`) still under review.**

## 0 — Skeleton

Directory tree from CLAUDE.md, `requirements.txt`, `Containerfile`, `.gitignore`, first commit.

Development happens in a Podman container. The container mounts the repo and carries the whole environment — Python deps, the dlt/dbt/Prefect CLIs, and the DuckDB extensions.

Done when: `podman build` produces an image, and a shell in that container can run `dlt --version` and `dbt --version` against the mounted repo.

Note the asymmetry to keep in mind from here on: the container defines the *local* environment, but Prefect's managed work pool installs from `requirements.txt` at run time and does not take a custom image. `requirements.txt` stays the single source of truth for dependencies, and the Containerfile installs from it rather than pinning anything of its own — otherwise local and serverless drift apart silently.

## 1 — Secrets

Secrets are fetched through a thin Python wrapper of the Infisical SDK (`utils/infisical.py`). The module does not work as the CLI, just creates functions that will be used in Python.

Done when: `pytest` passes an integration check that tests client connection and fetches a known mock secret from the `Production` Infisical environment.

Produces: `docs/secrets.md`.

## 2 — Catalog + storage spike

Neon project, a bucket on an S3-compatible store (Tigris for now), and a throwaway script proving DuckDB can attach the DuckLake catalog on Neon with the data path on that bucket, then write and read back one Parquet file.

Done when: a table written in one process is readable from a second, fresh process — which proves the catalog, not just local state.

Produces: `docs/data-storage.md`.

This is the foundation spike. Nothing downstream is worth attempting until it passes.

`tests/test_ducklake.py` does the round trip and tears itself
down; `utils.lakehouse initialise('prod')` then created the catalog for real, with
`data_inlining_row_limit` persisted to 0 so every later client writes Parquet
rather than rows into Neon. The test skips from here on, by design — it needs an
empty lakehouse, so its remaining job is validating each *new* environment.

## 3 — First dlt pipeline

One source landing in the `raw` dataset via the `ducklake` destination.

Done when: `raw` contains the loaded table and a second run is idempotent (no duplicate rows under the chosen write disposition).

## 4 — dbt attached

`dbt-duckdb` attached to the same DuckLake catalog, building one staging model from a `raw` table.

Done when: `dbt run` builds the model and the output is queryable from a plain DuckDB session against the same catalog.

No tests — see the conventions in CLAUDE.md.

Passed against `raw.orders__tpch` at sf 0.01: `dbt run --target prod` builds
`bronze.orders__tpch`, a second run rebuilds it, and a fresh `attach('prod')`
reads the same 15,000 rows. `utils/dbt_plugin.py` creates the secrets with
`credentials()`, the code `attach()` uses, and `profiles.yml` runs the
credential-free `ATTACH 'ducklake:lake'`. @docs/transformation.md

## 5 — Prefect flows

`ingest_flow` and `transform_flow` wrapping milestones 3 and 4, plus `pipeline_flow` chaining them. Run locally for now.

Done when: `pipeline_flow` completes locally end to end.

## 6 — Serverless deployment

Managed work pool, machine-identity bootstrap for secrets, deployments and schedules.

Done when: a scheduled run completes on Prefect's infrastructure with nothing running locally.

Produces: `docs/operations.md`.

## 7 — Maintenance

Snapshot expiry, old-file cleanup, first look at actual spend across Neon, object storage and Prefect.

Done when: there is a scheduled cleanup and a number for what the stack costs per month.

Produces: `docs/gotchas.md`, once there is real operational experience to write down.

---

## Known risks

**Prefect Cloud's free tier allows 1 concurrent flow run per workspace** across managed pools (5 pools maximum). The planned `ingest-only` / `transform-only` / `full-pipeline` deployments therefore cannot overlap — stagger the schedules in milestone 6.
→ [Prefect managed infrastructure](https://docs.prefect.io/3.0/deploy/infrastructure-examples/managed)

**Neon free-tier compute autosuspends.** The catalog is load-bearing for every query, so the first query after idle pays a cold start. Relevant to flow timeouts in milestone 6.

**The non-AWS S3 stores offer access-key pairs only** — no STS, no session tokens. This shapes how DuckDB's S3 secret is configured in milestone 2: a plain `TYPE S3` secret with `key_id` / `secret` / `endpoint` / `region`, no credential-chain provider. Tigris is one global endpoint and R2 is per-account, but both take `region=auto` and neither needs its own DuckDB secret type, so the difference between them is three values. Answered in milestone 2 for Tigris: `URL_STYLE 'vhost'` with `REGION 'auto'` and the endpoint as a bare host, confirmed by a passing round trip. R2 and AWS S3 are unverified, and AWS S3 is the odd one out anyway, with a real region and no endpoint override.
→ [Tigris dlt guide](https://www.tigrisdata.com/docs/guides/dlt/) · [R2 S3 API](https://developers.cloudflare.com/r2/api/s3/api/)
