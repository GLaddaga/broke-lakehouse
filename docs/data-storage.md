# Data storage

This document contains information about the project data storage and its underlying infrastructure, their setup and the choices that came with it.
it is a working document as features will be added over time (e.g. branching to multiple environments). 

## Overview
DuckLake requires storage for data and metadata. Here data will be stored in an S3-compatible cloud storage and metadata on Postgres.
Tigris was chosen as the S3-compatible cloud storage, and Neon as the transactional database to store the metadata.
In simple terms: Tigris holds the Parquet files while Neon holds the DuckLake catalog.

## Environments
Only `prod` environment exists for now, but the door is being kept open for future branching. [When the
second environment arrives](#when-the-second-environment-arrives).

## Setup choices

### Permanent, changes mean setting up things from scratch

| Decision | Value | Why |
|---|---|---|
| Tigris bucket name | `<lakehouse name>` | frozen inside `DUCKLAKE_DATA_PATH`, which the catalog records on first attach |
| Data path | `s3://<lakehouse name>/prod/` | recorded on the first successful attach |
| Neon region | closest to you | a project cannot be moved |
| Database owner | `<lakehouse name>_runner` owns `ducklake_catalog` | see [Things that will bite](#things-that-will-bite) |

### Reversible

| Decision | Value | Reasoning |
|---|---|---|
| Neon projects | one | a branch is not a second Postgres, so environments do not need more projects |
| Neon default branch | renamed to `prod` | one word names the branch, the Infisical slug and the Tigris prefix |
| Catalog database | `ducklake_catalog` | so the connection string names the thing it actually is |
| Metadata schema | default (`public`) | branches give the isolation; no need to also split by schema |
| Tigris buckets | one, prefix per environment | prefix-scoped IAM keys isolate as tightly as separate buckets would |
| Connection pooling | off | see [Things that will bite](#things-that-will-bite) |

One consequence worth stating early: dlt datasets and dbt schemas keep the
same names in every environment. Isolation lives in the branch and the prefix, 
and identical names are what will later let a clone of production behave exactly like production.

## Infrastructure setup

## Setting up Neon in the UI

**1. Project.** Create one, in the region closest to you. The region cannot be
changed afterwards.

**2. Rename the default branch to `prod`.** Branches → the default branch →
*Rename*. Cosmetic, but it means one word names the Neon branch, the Infisical
environment and the Tigris prefix.

**3. Role, before the database.** Branch selector → *Roles* → *Add role* →
`<lakehouse name>_runner`. Copy the password.

**4. Database, owned by that role.** Branch selector → *Databases* → *Add
database* → name `ducklake_catalog`, **owner `<lakehouse name>_runner`**.

**5. Delete the default database.** Same *Databases* page, delete the empty
`neondb`. Leave the `neondb_owner` *role* alone; Neon uses it for branch
defaults.

**6. Connection string.** *Connect* → Database `ducklake_catalog`, Role
`<lakehouse name>_runner`, **Connection pooling off**. This is
`DUCKLAKE_CATALOG_URI`.

**7. Check the ownership took.** *SQL Editor*, database `ducklake_catalog`:

```sql
select has_schema_privilege('<lakehouse name>_runner', 'public', 'CREATE') as can_create,
       (select count(*) from pg_database where datname = 'neondb') as neondb_left;
```

`can_create` must be true. If it is false, step 4 was done with the wrong owner
and the failure will arrive later as `permission denied for schema public` while
DuckLake creates `ducklake_metadata`.

## Setting up Tigris in the UI

**1. Bucket.** Dashboard → *Create Bucket* (`storage.new` opens the form
directly). Name it `<lakehouse name>`. The name cannot be changed later and
ends up inside `DUCKLAKE_DATA_PATH`, which the catalog records permanently on
first attach. Location type **Global**, storage tier **Standard**.

**2. Access key.** *Access Keys* → *Create New Access Key* → permission
**Editor** (read/write), scoped to **that one bucket**. On create you get the
Access Key ID, the Secret Access Key, the endpoint and the region at once. The
secret is shown once and cannot be recovered — a lost secret means deleting the
key and issuing a new one.

**3. Endpoint.** `https://t3.storage.dev`.
`https://fly.storage.tigris.dev` is the same service under another name; pick
one and never mix them between variables.

## The values this produces

All six go into Infisical, in the `prod` environment, at the root path — which
is where `utils/infisical.py` reads from.

| Variable | Value |
|---|---|
| `DUCKLAKE_CATALOG_URI` | the whole unpooled Neon string from Neon step 6 |
| `DUCKLAKE_DATA_PATH` | `s3://<lakehouse name>/prod/` |
| `AWS_ACCESS_KEY_ID` | Tigris access key ID |
| `AWS_SECRET_ACCESS_KEY` | Tigris secret |
| `AWS_ENDPOINT_URL_S3` | `https://t3.storage.dev` |
| `AWS_REGION` | `auto` |

## Catalog setup

### Ingredients

Two statements per client. dlt's `ducklake` destination and dbt's `profiles.yml`
must produce the same pair. `attach()` in `utils/lakehouse.py` is the reference implementation.

```sql
CREATE OR REPLACE SECRET storage (
    TYPE s3, PROVIDER config,
    KEY_ID     '…',   -- AWS_ACCESS_KEY_ID
    SECRET     '…',   -- AWS_SECRET_ACCESS_KEY
    ENDPOINT   '…',   -- AWS_ENDPOINT_URL_S3, scheme stripped
    REGION     '…',   -- AWS_REGION
    URL_STYLE  'vhost'
);

ATTACH 'ducklake:postgres:<DUCKLAKE_CATALOG_URI>' AS lake
       (DATA_PATH '<DUCKLAKE_DATA_PATH>');
```

`DUCKLAKE_CATALOG_URI` is passed through verbatim: everything after
`ducklake:postgres:` goes to the `postgres` extension, which takes either a
libpq keyword string or a `postgresql://…` URI, so Neon's own string is used
unedited, query parameters and all.

### Whys

**`ENDPOINT` without the scheme.** `AWS_ENDPOINT_URL_S3` is stored with
`https://` because that is what the AWS SDK and dlt expect. DuckDB wants the
bare host. The caller strips it — one `urlparse`, no second variable.

**`REGION` from `AWS_REGION`, `PROVIDER config`.** These stores issue long-lived
key pairs only — no STS, no session tokens — so a credential chain has nothing to
discover and the values are passed directly. Region is config rather than a
constant because it is the one value that differs in kind between providers:
`auto` for Tigris and R2, which have no region to choose, a real region for AWS
S3.

**`URL_STYLE 'vhost'`.** Confirmed against Tigris only. R2 and AWS S3 both accept
vhost addressing too, so this is expected to carry over, but neither has been
run. If a move ever fails with a bucket-not-found that looks like a DNS error,
this is the line to try `path` on.

**An unpooled Neon connection.** Neon's `-pooler` host runs PgBouncer in
transaction mode, which discards session-level prepared statements. DuckDB's
postgres extension uses them.

### About data inlining

DuckLake can store a write as rows in the catalog database instead of as a
Parquet file in object storage. It exists to keep tiny writes from littering the
bucket with tiny files.

Limit is set to 0 for now as initially the goal is to save on the serverless Postgres instance,
could be reconsidered as our infrastructure budget grows. Setting lives in the catalog,
not in the attaches as it has to be global.

Tradeoff: with no inlining, many small writes produce many small Parquet
files. That is the problem the setting exists to avoid, and it becomes the
compaction job's problem instead. It is the right trade here because dlt writes
in batches rather than row at a time, and because a small file on Tigris costs
far less than a row in Neon.

## Test with first roundtrip

```bash
podman run --env-file .env --rm -v $(pwd):/workspace \
  localhost/the-broke-lakehouse python -m pytest tests/ -v --lakehouse-env prod
```

`tests/test_ducklake.py` creates the catalog exactly as `initialise()` will
create the real one, writes one row, reads it back from a separate interpreter,
and asserts it travelled as Parquet in the bucket and not as inlined rows in
Neon — then drops the table, expires the snapshots, deletes the files and removes
the `ducklake_*` catalog tables.

It runs only against an empty `public` schema and an empty prefix, and skips
otherwise, naming what it found. The teardown drops the catalog itself, so
anything already there would be something it is about to destroy.

What it leaves behind: an empty catalog. (?)

### Starting for real

#### Initialising

```bash
podman run --env-file .env --rm -v $(pwd):/workspace localhost/the-broke-lakehouse \
  python -m utils.lakehouse initialise <environment>
```

Immediately afterwards, Neon holds the `ducklake_*` tables with three or four
rows in `ducklake_metadata` (`version`, `created_by`, `data_path`, and the
`data_inlining_row_limit` of 0) and one snapshot; the bucket still holds nothing,
because creating a catalog writes no data files. The first object appears with
the first write.

### Cleaning up

Two ways back, depending on whether the catalog itself is trusted.

**`reset` empties the lakehouse and keeps it.** Every table and view is dropped,
every schema but `main`, and their files deleted. The
catalog and its options stay exactly as `initialise` made them, so it is ready
to write straight away.

```bash
podman run --env-file .env --rm -it -v $(pwd):/workspace localhost/the-broke-lakehouse \
  python -m utils.lakehouse reset <environment>
```

**`purge` destroys the lakehouse, catalog and all** — for when the catalog is the
problem, not its contents. It goes *around* DuckLake: Postgres `DROP` on the
`ducklake_*` tables, S3 deletes on every object under the prefix. Afterwards the
lakehouse does not exist and `initialise` is next — or both in one command:

```bash
podman run --env-file .env --rm -it -v $(pwd):/workspace localhost/the-broke-lakehouse \
  python -m utils.lakehouse initialise <environment> --force
```

`--force` checks the prefix first, so a misconfigured `DATA_PATH` refuses before
anything is purged; then it runs `purge` with its listing and typed confirmation,
and initialises. On an already-empty lakehouse it just initialises.

`initialise()` refuses a lakehouse that already exists, so a half-created catalog
— a failed run, a wrong `DATA_PATH` — has to be removed before it can be
recreated. `purge()` does that: every `ducklake_*` table in Neon, every object
under the prefix, and it returns what it removed.

```bash
podman run --env-file .env --rm -it -v $(pwd):/workspace localhost/the-broke-lakehouse \
  python -m utils.lakehouse purge <environment>
```

It lists what it found and then asks, so it needs a terminal — `-it`, where every
other command here runs fine without one. Without it the prompt fails with a
plain message rather than an `EOFError`, and nothing is removed.

`survey` is the read-only half, for looking without harming anything — the same
listing `purge` shows before it asks:

```bash
podman run --env-file .env --rm -v $(pwd):/workspace localhost/the-broke-lakehouse \
  python -m utils.lakehouse survey <environment>
```

For a new environment the whole sequence is: survey, purge if the survey found
anything, run the test, then initialise. The test has to come first because it
needs a clean slate, and initialise last because after it nothing is clean again.

## Potential issues

**The connecting role must own the catalog database.** Postgres 15+ leaves
`public` owned by `pg_database_owner`, so only members of the database owner can
create tables in it. Connecting as the wrong role gives `permission denied for
schema public` while creating `ducklake_metadata` — which reads like a DuckLake
bug and is a Neon ownership question.

**Connection failures print the password.** DuckDB echoes the full connection
string, credential in cleartext, in its connect-error message. 
`utils/lakehouse.py` redacts it before re-raising; anything else that attaches 
has to do the same.

**One Postgres connection per DuckDB thread, never released.** DuckLake caches a
connection in thread-local storage per worker thread, and they stay counted as
in use while the threads live. A single-table write never notices; a dbt run
building many models can hit `all 8 connections in use`. Mitigation is fewer
threads (`SET threads`) or disabling the thread-local cache.

## Creating more environments

Each environment is **a Neon branch plus a bucket prefix**, named identically,
selected by one word.

Potentially, the future setting could look like this:

| Service | prod | test | dev |
|---|---|---|---|
| Neon | default branch | ephemeral, per PR | branch `dev` |
| Tigris | `prod/` | fork bucket | `dev/` |
| Infisical slug | `prod` | `test` | `dev` |

### Notes when creating more environments:

**Narrow the Tigris keys to a prefix.** Tigris supports AWS-shaped IAM policies
at `https://iam.storage.dev`, attached directly to an access key — the
`--user-name` in `attach-user-policy` is the `tid_…` key ID, as there are no
users or roles.
Note the `s3:prefix` condition on `ListBucket`: anything listing the bucket then
has to pass a matching `Prefix=`, and a bare listing is denied. That is the
isolation working, and it will look like a bug the first time.

**Provision it programmatically rather than by hand.** Neon branches come from
its REST API (`/projects/{id}/branches`, then `/connection_uri` with
`pooled=false`), and Tigris buckets, policies and keys from boto3's `s3` and
`iam` clients against `t3.storage.dev` and `iam.storage.dev`. The intended tool
is **OpenTofu, not Terraform** — OpenTofu has client-side state encryption (its
PBKDF2 key provider needs only a passphrase, no KMS), so the state file can live
on Tigris itself. Terraform only offers backend-side encryption.

The mechanism that makes per-PR environments cheap: DuckLake records data-file
paths *relative* to a single `data_path` row in `ducklake_metadata`. So a Neon
branch plus a Tigris fork is a zero-copy clone of the whole lakehouse, rebased
by rewriting that one row — no component needs to know it is running against a
clone. Two constraints come with it: the bucket needs snapshots enabled before
it can be forked, and the Neon branch must be taken *before* the Tigris fork, or
the catalog will reference files the fork does not have.
