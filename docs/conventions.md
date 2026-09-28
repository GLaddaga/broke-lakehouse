# Conventions

How data is laid out and named, and the rules every component follows.

## Environment

- One `requirements.txt` at the repo root for `orchestrate/`, `ingest/` and `transform/`.
- Local development runs only in a Podman container that mounts the repo.
- The Containerfile installs from `requirements.txt` and pins nothing of its own. Prefect's managed work pool installs from that same file at run time and cannot take a custom image, so `requirements.txt` is the only place dependencies are declared — anything pinned solely in the Containerfile drifts from what actually runs in the cloud.

## Layers

One schema per layer, one word each: `archive`, `raw`, `bronze`, `silver`, `gold`.

| Schema | Written by | What it holds |
|---|---|---|
| `archive` | nothing yet | verbatim source payloads, for sources that cannot be re-read |
| `raw` | dlt | the payload as it arrived, one table per source table |
| `raw_staging` | dlt, automatically, for `merge` only | dlt's merge staging — not a designed layer |
| `bronze` / `silver` / `gold` | dbt | flattening, typing, modelling |

**`raw` is append-only by default.** `append` is the cheapest disposition there
is: the load adds Parquet files and nothing else. It never reads the target,
never rewrites a file, and does not need staging dataset. It also suits a persistent 
landing layer on its own terms: history accumulates instead of being overwritten, 
and a file once written is never touched again.

**Idempotency with `append` comes from the extraction, not from the write.** A
resource with an incremental cursor fetches only what is new, so a second run
has nothing to append.

**`merge` is the exception, for sources that can only be asked "what is true
now".** DuckLake expresses the upsert as delete plus insert, so data files 
get rewritten and delete files accumulate, and dlt stages the whole incoming 
load in `raw_staging` first.

**`replace` is for generated fixtures only**, data that is
regenerated whole each run and has no cursor. Each run rewrites the table.

**`raw_staging` is not ours, it is dlt-managed.**

**`archive` gets its own bucket**, not a prefix inside the lakehouse bucket.

**Schemas exist only once something writes to them.**

## Naming

**Tables are `<table>__<source>`.**

**No child tables in `raw`.** dlt resources set `max_table_nesting=0`, so lists
and dicts stay whole as JSON columns. Flattening is `bronze`'s job.

**Names are identical in every environment.** Isolation lives in the Neon branch
and the bucket prefix, never in a name, so a clone of production behaves exactly
like production. @docs/data-storage.md

**Pin the type when a source is inconsistent.** This avoids column splitting.

## Materializations

**`bronze` is `table`.** Built once per run, read as Parquet by everything
downstream, rather than a view that re-reads `raw` on every query. The cost is a
full rewrite per run and old files left for the cleanup job.

**`silver` and `gold` are `table` too**, for the same reason: `gold` is what gets
queried most, and a view there would re-run the joins over `silver` on every
read. The first model to outgrow a full rebuild becomes `incremental`.
@docs/transformation.md

## No data quality tests

Deliberately skipped to save compute. Can be reconsidered at a later stage.

## Secrets

A thin Python wrapper retrieves secrets from Infisical using the SDK.
@docs/secrets.md

## Data flow

- `orchestrate/` calls into `ingest/` and `transform/` directly — same environment, so imports or CLI calls both work.
- Data passes between stages via the warehouse only.
- dlt writes only `raw`. dbt reads `raw` and writes `bronze`, `silver` and `gold`, all within the same DuckLake catalog.
