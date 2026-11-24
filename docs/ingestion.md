# Ingestion

dlt pipelines live in `ingest/pipelines/`. Each one is a module that takes the
environment as its first argument:

```bash
podman run --env-file .env.runner --rm -v $(pwd):/workspace -w /workspace \
  localhost/broke-lakehouse python -m ingest.pipelines.<name> <environment>
```

## How it reaches the lakehouse

There is no dlt config file. `destination(environment)` in `broke_lakehouse/ops.py`
builds dlt's `ducklake` destination from the same Infisical values `attach()`
uses, with `ducklake_name="lake"` (the shared alias). It first runs one
`attach()` to check the inlining guard, which also makes bad credentials fail
early, without printing the password.

**dlt can print the password.** It takes the catalog URI verbatim, so a connect
failure inside dlt shows it in the error. Prefect logs a failed task's traceback,
so every `pipeline.run` goes inside `with redacted(environment):`, which strips it
(`tests/test_redaction.py`).

## What lands in `raw`

Pipelines write only `raw` (@docs/conventions.md). Each resource sets
`name="<table>__<source>"`; dlt adds `_dlt_loads`, `_dlt_version` and
`_dlt_pipeline_state`.

## State lives in the destination

Containers and Prefect runs start from nothing each time, so dlt restores its
state from `raw._dlt_pipeline_state` on every run. `broke_lakehouse.ops reset` drops
that table along with everything else. In a long-lived shell, also delete
`~/.dlt/pipelines/<name>` after a reset.
