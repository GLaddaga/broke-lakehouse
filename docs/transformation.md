# Transformation

dbt, in `transform/`, through `dbt-duckdb` attached to the DuckLake catalog.

## Run

```bash
podman run --env-file .env.runner --rm -v $(pwd):/workspace -w /workspace/transform \
  localhost/broke-lakehouse dbt run --target prod
```

There is no default target, on purpose: the command has to say which lakehouse
it builds into.

## How it attaches

Credentials and the attach are split up:

- `broke_lakehouse/dbt_plugin.py` is a dbt-duckdb plugin. It calls `credentials()` from
  `broke_lakehouse/client.py`, which creates the DuckDB secrets from Infisical using
  the same code `attach()` uses. Before that, it runs one `attach()` to check
  the `data_inlining_row_limit = 0` guard, which also stops the run early if
  Neon or the credentials are wrong.
- `profiles.yml` holds only `ATTACH 'ducklake:lake' AS lake`. `ducklake:lake`
  refers to a secret, so the file has no credentials in it.

This relies on dbt-duckdb running plugins before `attach:` entries. If an
upgrade ever reversed that order, the run fails with *Secret "lake" was not
found* before anything is written. `dbt-duckdb` is pinned, so one `dbt run`
after a bump is the whole check.

To add an environment, copy the `prod:` output and change its name and
`environment:`.

## Schemas

Each layer is a folder under `models/` that builds into `lake.<layer>`.
`macros/generate_schema_name.sql` drops dbt's default `main_` prefix, because
names are identical in every environment (@docs/conventions.md).

## What a table build leaves behind

dbt builds `<table>__dbt_tmp` and renames it. A rename does not move files, so
they stay under `.../<schema>/<table>__dbt_tmp/`. Each run rewrites the whole
table, and the old files remain until maintenance removes them.

## Maintenance

```bash
podman run --env-file .env.runner --rm -v $(pwd):/workspace -w /workspace/transform \
  localhost/broke-lakehouse dbt run-operation maintain_ducklake --target prod \
  --args '{retention: 7 days}'
```

It merges small files, expires snapshots older than `retention`, and deletes
unreferenced and orphaned files, across the whole lakehouse, `raw` included.
`retention` is required: it sets how far back time travel reaches afterwards.

## Threads

`threads: 1`, because each DuckDB thread holds a Neon connection
(@docs/data-storage.md). If you raise it, watch for `all 8 connections in use`.

## When it breaks

| Symptom | Cause |
|---|---|
| *does not have a target named 'default'* | `--target` missing |
| *Unable to import module 'broke_lakehouse.dbt_plugin'* | image built before the package moved to `broke_lakehouse/`: rebuild |
| *Inconsistency detected between 'path' and 'database'* | `attach:` alias no longer matches `database` |
| *Secret "lake" was not found* | `plugins:` entry removed, or plugin order changed in an upgrade |
| `DROP … CASCADE` not supported | the `attach:` path lost its `ducklake:` prefix |
