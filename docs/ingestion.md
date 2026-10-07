# Ingestion

Data lands in the lakehouse through dlt, whose pipelines live in `ingest/`.
This document describes the architectural choices made for dlt and how to run
it. How dlt itself works is @docs/guides/dlt.md.

## Run

From the repo root, a pipeline is a module with the environment as its first
argument:

```bash
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace \
  localhost/the-broke-lakehouse python -m ingest.pipelines.<name> <environment>
```

The environment is required and never defaulted, as everywhere else: which
lakehouse gets written to belongs in the command.

## How it reaches the lakehouse: `destination()`

dlt has no config file here. The pipeline is handed a destination object built by
`destination(environment)` in `utils/lakehouse.py`, from the same six Infisical
values `attach()` uses (@docs/data-storage.md).

It does two things:

**1. Runs `attach()` once and closes it.** dlt issues its own `ATTACH`, so it
never passes through `attach()`. The throwaway connection is how the
`data_inlining_row_limit = 0` guard still applies to the one client that writes
bulk data. Cost: one extra Neon round trip per run. It also means a wrong
password or an unreachable Neon fails here, with `attach()`'s error, which
never contains the password, before dlt has printed anything.

**2. Builds dlt's `ducklake` destination** with explicit credentials:

| Field | Value | Why |
|---|---|---|
| `ducklake_name` | `lake` | the alias every client uses; DuckLake views store it in their SQL |
| `metadata_schema` | `public` | where `attach()` created the catalog |
| `catalog` | `DUCKLAKE_CATALOG_URI`, verbatim | the same unpooled Neon string |
| `bucket_url` | `s3://<bucket>/<prefix>/` via `_path()` | one spelling of the data path, trailing slash included |
| `endpoint_url` | `AWS_ENDPOINT_URL_S3`, **with** scheme | dlt wants the URL; only DuckDB wants the bare host |
| `s3_url_style` | `vhost` | as `attach()`, confirmed on Tigris only |

**dlt is the one client that can print the password.** `attach()` and dbt keep
the catalog in a postgres secret, whose password DuckDB never echoes. dlt takes
the URI verbatim, so a connect failure *inside* dlt, after step 1 passed, can
put it in dlt's error output.

## What lands in `raw`

Every pipeline writes the `raw` dataset (`dataset_name="raw"`) and nothing else
(@docs/conventions.md). One run of `<source>` leaves:

| Table | Written by | Holds |
|---|---|---|
| `<table>__<source>` × 8 | the source's resources | the data, as generated |
| `_dlt_loads` | dlt | one row per load package, with its status |
| `_dlt_version` | dlt | every version of the inferred schema |
| `_dlt_pipeline_state` | dlt | the pipeline state, incremental cursors included |

The table names come from each resource's `name=`, which is where
`<table>__<source>` is enforced; dlt would otherwise name the table after the
function.

In the bucket: `s3://<bucket>/<environment>/raw/<table>__tpch/ducklake-<uuid>.parquet`.

## State lives in the destination

Containers run with `--rm`, and Prefect's serverless runs start from nothing,
so `~/.dlt/pipelines/<name>` never survives between runs. dlt restores it from
`raw._dlt_pipeline_state` at the start of each run. The destination is the
state's source of truth, which also removes the guide's stale-state trap:
`python -m utils.lakehouse reset` drops `_dlt_pipeline_state` with everything
else, so the next run starts clean.

The trap still applies to a long-lived shell inside one container. After a reset
from elsewhere, delete `~/.dlt/pipelines/<name>` there too.
