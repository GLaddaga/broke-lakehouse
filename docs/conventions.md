# Conventions

## Environment

- `requirements.txt` is the only place dependencies are declared, for all three
  components. The Containerfile installs from it, and so does Prefect's
  managed pool.
- Local development happens only inside the Podman container.

## Layers

One schema per layer: `archive`, `raw`, `bronze`, `silver`, `gold`. A schema
exists only once something writes to it.

| Schema | Written by | Holds |
|---|---|---|
| `archive` | nothing yet | verbatim payloads from sources that can't be re-read; gets its own bucket |
| `raw` | dlt | data as it arrived, one table per source table |
| `raw_staging` | dlt, for `merge` only | dlt-managed, not a designed layer |
| `bronze` / `silver` / `gold` | dbt | flattening, typing, modelling |

**Write dispositions in `raw`:**

- **`append`** is the default. It's the cheapest: it adds files and never reads
  or rewrites anything, and history accumulates. Idempotency comes from an
  incremental cursor in the extraction, not from the write.
- **`merge`** is for sources that can only answer "what is true now". DuckLake
  does it as delete + insert, which rewrites files and stages the whole load in
  `raw_staging`.
- **`replace`** is for sources that are regenerated
  whole on every run.

## Naming

- Tables are `<table>__<source>`.
- No child tables in `raw`: `max_table_nesting=0` keeps nested data as JSON.
  Flattening happens in `bronze`.
- Pin column types when a source is inconsistent, so dlt doesn't split the column.
- Names are identical in every environment. Isolation comes from the Neon
  branch and the bucket prefix, so a clone of prod behaves like prod
  (@docs/data-storage.md).
- **The attach alias is `lake`, fixed per project.** DuckLake views store the
  alias in their SQL, so every client must use the same one, and renaming it
  breaks existing views. It's set in `LAKE` in `utils/lakehouse.py` (for
  `attach()` and dlt) and in `profiles.yml` (for dbt).

## Materializations

Every layer is `table`, so everything downstream reads Parquet instead of
re-running views. The cost is a full rewrite per run, with old files left for
maintenance. A model that outgrows full rebuilds becomes `incremental`.

## No data quality tests

Skipped to save compute, for now.

## Data flow

- `orchestrate/` calls `ingest/` and `transform/` directly (same environment).
- Stages pass data only through the warehouse.
- dlt writes only `raw`. dbt reads `raw` and writes `bronze`, `silver` and `gold`.
