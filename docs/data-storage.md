# Data storage

DuckLake splits a lakehouse in two: Parquet files in S3-compatible object
storage (Tigris for now) and the catalog in Postgres (Neon). Only `prod` exists for now.

## Decisions

**Permanent** — changing these means starting from scratch:

| Decision | Value | Why |
|---|---|---|
| Bucket name | `<lakehouse name>` | part of the data path, which the catalog records on first attach |
| Data path | `s3://<lakehouse name>/prod/` | same |
| Neon region | closest to you | a Neon project cannot be moved |
| Catalog owner | `<lakehouse name>_runner` owns `ducklake_catalog` | see [Gotchas](#gotchas) |

**Reversible:**

| Decision | Value | Why |
|---|---|---|
| Neon projects | one | environments are branches, not projects |
| Neon default branch | renamed `prod` | one word names the branch, the Infisical slug and the bucket prefix |
| Metadata schema | `public` | branches already isolate |
| Buckets | one, prefix per environment | prefix-scoped keys isolate as well as separate buckets |
| Connection pooling | off | Neon's pooler drops the prepared statements DuckDB uses |
| Data inlining | `data_inlining_row_limit = 0` | every write is Parquet, never rows in Neon: a small file on Tigris costs far less than a row in Neon, and dlt writes in batches anyway. Stored in the catalog, so it applies to every client |
| S3 secret | `PROVIDER config`, `URL_STYLE 'vhost'`, `REGION` from config | non-AWS stores issue static keys only, so there is no credential chain. vhost is confirmed on Tigris only; try `path` if another provider gives a DNS-looking bucket-not-found |

DuckLake writes files at `<data path>/<schema>/<table>/ducklake-<uuid>.parquet`
and that shape is fixed, so the layer hierarchy lives in schema and table names
(@docs/conventions.md).

## Setup: Neon

1. Create a project in the region closest to you.
2. Rename the default branch to `prod`.
3. *Roles* → add `<lakehouse name>_runner`. Copy the password.
4. *Databases* → add `ducklake_catalog`, **owner `<lakehouse name>_runner`**.
5. Delete the empty `neondb` database (keep the `neondb_owner` role).
6. *Connect* → database `ducklake_catalog`, that role, **pooling off**. This is `DUCKLAKE_CATALOG_URI`.
7. Check, in the SQL editor on `ducklake_catalog`:
   ```sql
   select has_schema_privilege('<lakehouse name>_runner', 'public', 'CREATE');
   ```
   Must be true, otherwise step 4 had the wrong owner.

## Setup: Tigris

1. Create bucket `<lakehouse name>`: location **Global**, tier **Standard**.
2. *Access Keys* → new key, **Editor**, scoped to that bucket. The secret is shown once.
3. Endpoint: `https://t3.storage.dev`. (`fly.storage.tigris.dev` is an alias; don't mix the two.)

## Values for Infisical

All six go in the `prod` environment, at the root path (@docs/secrets.md):

| Variable | Value |
|---|---|
| `DUCKLAKE_CATALOG_URI` | the unpooled Neon string |
| `DUCKLAKE_DATA_PATH` | `s3://<lakehouse name>/prod/` |
| `AWS_ACCESS_KEY_ID` | Tigris key ID |
| `AWS_SECRET_ACCESS_KEY` | Tigris secret |
| `AWS_ENDPOINT_URL_S3` | `https://t3.storage.dev` |
| `AWS_REGION` | `auto` |

## Lifecycle commands

All are `python -m broke_lakehouse.ops <command> <environment>` in the container:

```bash
podman run --env-file .env --rm -it -v $(pwd):/workspace localhost/the-broke-lakehouse \
  python -m broke_lakehouse.ops <command> <environment>
```

| Command | Does |
|---|---|
| `survey` | read-only listing of catalog tables and bucket objects |
| `initialise` | creates the catalog; refuses if one exists. `--force` purges first |
| `reset` | drops every table, view and schema and deletes their files; keeps the catalog |
| `purge` | destroys catalog and files, bypassing DuckLake. Asks for confirmation, so it needs `-it` |

New environment: `survey` → `purge` if anything was found → run
`tests/test_ducklake.py` (needs an empty lakehouse, skips otherwise) → `initialise`.

```bash
podman run --env-file .env --rm -v $(pwd):/workspace \
  localhost/the-broke-lakehouse python -m pytest tests/ -v --lakehouse-env <environment>
```

## Gotchas

**The connecting role must own the catalog database.** Postgres 15+ only lets
the database owner create tables in `public`. The wrong role fails with
`permission denied for schema public` while creating `ducklake_metadata`: this
looks like a DuckLake bug, but it's a Neon ownership problem.

**Connect errors can print the password.** DuckDB echoes the connection string
in connect errors. A postgres secret's password is never echoed, which is why
`attach()` uses one. `_pg()` redacts before re-raising; dlt does not
(@docs/ingestion.md).

**One Postgres connection per DuckDB thread, never released.** Many threads can
hit `all 8 connections in use`. Keep threads low.

## More environments (not built yet)

An environment is a Neon branch plus a bucket prefix, named with the same word
as its Infisical slug.

- **Prefix-scoped keys.** Tigris takes AWS-style IAM policies at
  `https://iam.storage.dev`, attached to the key itself (`--user-name` is the
  `tid_…` key ID). With an `s3:prefix` condition, a listing without a matching
  `Prefix=` is denied. That is intended.
- **Zero-copy clones.** The catalog stores file paths relative to one `data_path`
  row, so a Neon branch plus a Tigris bucket fork clones the whole lakehouse by
  rewriting that row. The bucket needs snapshots enabled first, and the branch
  must be taken *before* the fork.
- **Provisioning** belongs in OpenTofu (client-side state encryption, so the
  state can live on Tigris), using Neon's branch API and boto3 against Tigris.
