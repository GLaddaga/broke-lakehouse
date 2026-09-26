# Transformation

Data transformation in the lakehouse happens through dbt, 
whose project lives in the `transform/` folder.
This document describes the architectural choices made for dbt
and provides instructions on how to run it.

## Run

From `transform/`, with the environment as the target:

```bash
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace/transform \
  localhost/the-broke-lakehouse dbt run --target prod
```

`-w /workspace/transform` matters: dbt finds `dbt_project.yml` and
`profiles.yml` in the working directory, and the profile's `module_paths: [".."]`
is resolved from there to put the repo root, and so `utils`, on `sys.path`.

There is no default target. A bare `dbt run` fails with *does not have a target
named 'default'*, on purpose: which lakehouse gets built into belongs in the
command.

## How it attaches: `profiles.yml`

A DuckLake needs the same two statements from every client: the S3 secret and
the `ATTACH` (@docs/data-storage.md). dbt gets them through a dbt-duckdb plugin,
`utils/dbt_plugin.py`, which calls `attach()` on the connection dbt-duckdb opened. 
`profiles.yml` holds no credentials and builds no connection itself. It tells 
dbt-duckdb to load the plugin, and it declares what dbt needs to know about the 
database the plugin attaches.

### The file

```yaml
lakehouse:
  outputs:
    prod:
      type: duckdb
      database: lake
      schema: main
      threads: 1
      module_paths: [".."]
      plugins:
        - module: utils.dbt_plugin
          config:
            environment: prod
      attach:
        - path: "ducklake:"
          alias: lake
```

### What happens when dbt connects

When a dbt command first needs the database, dbt-duckdb does the following, in
this order:

1. **Imports the plugin.** It adds each `module_paths` entry to `sys.path`, then
   imports `utils.dbt_plugin` and builds its `Plugin` class, passing the
   `config:` mapping. `Plugin.initialize` stores `environment: prod`. Nothing
   touches the network yet.
2. **Opens DuckDB.** `duckdb.connect(path)`. The profile sets no `path`, so it is
   `:memory:`: an empty, in-memory database named `memory`. It stays empty. The
   lakehouse is attached next to it, not opened as it.
3. **Loads the profile's `extensions:` and creates its `secrets:`.** The profile
   declares neither, so nothing happens here.
4. **Runs each plugin's `configure_connection(conn)`.** This is where the plugin
   calls `attach("prod", con=conn)`, the same function every other client uses.
   It fetches the six values from Infisical's `prod` environment, loads
   `ducklake`, `httpfs` and `postgres`, creates the S3 secret, runs
   `ATTACH 'ducklake:postgres:…' AS lake (DATA_PATH …)` against Neon, and checks
   that `data_inlining_row_limit` is 0. If any of that fails, the run stops here
   with `attach()`'s own error, password already redacted.
5. **Runs each `attach:` entry as `ATTACH IF NOT EXISTS`.** The profile's entry
   becomes `ATTACH IF NOT EXISTS 'ducklake:' AS lake`. A database called `lake`
   already exists from the previous step, so DuckDB skips it without looking at the path.

The connection is kept open for the rest of the invocation (dbt-duckdb's
`keep_open`, on by default). Each dbt thread works on a cursor of that
connection, so the attach happens once per `dbt` command, not once per model.

Two things run earlier, when dbt reads the profile before connecting. Both rely
on the `attach:` entry:

- **`database: lake` is validated.** dbt-duckdb checks the `database` field
  against the database name taken from `path` (`memory`) and against the
  `alias` of every `attach:` entry. `lake` matches no path, so without the entry
  the profile is rejected with *Inconsistency detected between 'path' and
  'database' fields*.
- **`lake` is recorded as a DuckLake.** Any attach entry whose path contains
  `ducklake:` puts its alias in a set that dbt-duckdb's macros consult through
  `adapter.is_ducklake()`. Membership changes the generated SQL.

So the `attach:` entry never attaches anything. It is a declaration that happens
to be written in the shape of an attach, because that is the only place
dbt-duckdb looks.

### Key by key

**`lakehouse:`** The profile name. `dbt_project.yml` selects it with
`profile: lakehouse`.

**No `target:` key.** A profile normally names its default target. Leaving it out
makes dbt fall back to a target called `default`, which does not exist, so a
command without `--target` fails before connecting.

**`outputs: prod:`** One target per environment, named with the same word as the
Infisical slug, the Neon branch and the bucket prefix. `--target prod` selects
it, and the target's plugin config says `environment: prod`.

**`type: duckdb`** Selects the dbt-duckdb adapter.

**`database: lake`** The database dbt builds into and reads sources from by
default, so compiled SQL reads `"lake"."<schema name>"."<table>__<source>"`. 
`lake` is the alias `attach()` uses, and the one dlt's `ducklake_name` sets. 
A DuckLake view stores its SQL with the alias written into it, so every client 
has to use the same alias.

**`schema: main`** Required by dbt. It is only the fallback for a model outside
any layer folder.

**`module_paths: [".."]`** The `dbt` executable lives in `/usr/local/bin`, and
Python puts the script's directory on `sys.path`, not the working directory. So
`utils` is not importable from a bare `dbt` command. dbt-duckdb inserts these
paths into `sys.path` before importing plugins. They are relative to the working
directory, so `..` from `/workspace/transform` is `/workspace`, the repo root.
This is why commands run with `-w /workspace/transform`. From anywhere else, the
import fails with *Unable to import module 'utils.dbt_plugin'*.

**`plugins:`** The only line that makes a connection happen. `module` is the
Python module, which must define a class called `Plugin`. `config` is passed to
the plugin, merged over the profile's `settings:` (none here). The plugin reads
only `environment`.

**`attach:`** The declaration described above. The path is `"ducklake:"`, with
nothing after it, because nothing ever opens it. The only requirements are that
it contains `ducklake:` and that the `alias` matches `database`.

### What is deliberately absent

| Key | Why it is not there |
|---|---|
| `path` | The lakehouse is attached, not opened. `:memory:` gives an empty scratch database and no local file to manage |
| `extensions` | `attach()` loads `ducklake`, `httpfs` and `postgres` itself. The image already has them installed |
| `secrets` | `attach()` creates the S3 secret itself, with values from Infisical |
| any `env_var()` | No value comes from the environment. The only env vars involved are Infisical's bootstrap three, read by `utils/infisical.py`, not by dbt |
| `settings` | No DuckDB setting needs changing yet. If the Neon connection limit ever bites, `threads` for DuckDB goes here |
| `is_ducklake` | Only needed when the path has no `ducklake:` scheme, which is MotherDuck's case. |

### What `utils/dbt_plugin.py` adds

One class, two methods. `initialize` keeps `environment` from the config, and
`configure_connection` calls `attach(self.environment, con=conn)`. For this,
`attach()` in `utils/lakehouse.py` gained one optional argument, `con`: given a
connection, it configures that one instead of opening its own. Every existing
caller is unaffected.

The plugin module imports dbt, so it is kept apart from `utils/lakehouse.py`,
which dlt pipelines import too.

### Adding an environment

Copy the `prod:` block under `outputs:`, rename it, and change
`environment:`. The rest is identical by design: the names are the same in
every environment, and what differs (catalog, bucket prefix, keys) comes from
that environment's Infisical slug.

```yaml
    dev:
      # …same as prod…
      plugins:
        - module: utils.dbt_plugin
          config:
            environment: dev
```

### When it breaks

| Symptom | Cause |
|---|---|
| *does not have a target named 'default'* | `--target` missing |
| *Unable to import module 'utils.dbt_plugin'* | not run from `transform/`, so `..` is not the repo root |
| *Inconsistency detected between 'path' and 'database'* | the `attach:` entry was removed, or its `alias` no longer matches `database` |
| a connect error with `<catalog uri>` in it | Neon unreachable or credentials wrong; the redaction is `attach()`'s |
| `DROP … CASCADE` not supported | `lake` is not recognised as a DuckLake: the `attach:` path lost its `ducklake:` |

**Upgrade risk.** The design depends on the order of steps 4 and 5: plugins configure
the connection before `attach:` entries run. If a dbt-duckdb upgrade reversed
it, the profile's `ATTACH IF NOT EXISTS 'ducklake:' AS lake` would run first,
against no catalog. Tested: it fails straight away with *Default secret was not
found*, before anything reaches Neon or the bucket, so a breaking upgrade shows
up as a failed run and never as data written somewhere else. `dbt-duckdb` is
pinned exactly in `requirements.txt`, so this can only happen on a deliberate
bump — after which one `dbt run` is the whole check.

### Why not a profile filled from env vars

It would work; a self-hosted catalog does not prevent it. It just was not used
because of what it needs around it in this project. The main reason that justifies
this implementation is that the DuckLake attachment should be identical everywhere,
and any nuance in passing the attachment settings could result in the lakehouse 
malfunctioning as the _broke_ requirement requires strict rules.

**1. Something has to put Infisical's values into env vars first.** Jinja in
`profiles.yml` can only read the environment. It cannot call Infisical.
A wrapper that fetches the secrets, writes them into `os.environ`, then calls
dbt could work, but it would be a new layer on top of `attach()` and every dbt
call would have to go through it. The plugin puts the same fetch inside dbt, 
so plain dbt commands work.

**2. The attach would exist twice.** @docs/data-storage.md requires every client
to produce the same two statements, with `attach()` as the reference. The YAML-only
approach would rewrite both, and some of `attach()`'s logic does not carry over:

- **The endpoint's scheme.** `AWS_ENDPOINT_URL_S3` is stored as `https://…`
  because the AWS SDK and dlt need that, but DuckDB needs the bare host.
  `attach()` strips it with `urlparse`. In Jinja it becomes a
  `replace('https://', '')`, which quietly breaks on an `http://` endpoint.
- **The trailing slash on `DATA_PATH`.** `_path()` adds it because the catalog
  records the path permanently on first attach. The YAML passes the secret
  through as typed.
- **The inlining guard.** `attach()` refuses a catalog whose
  `data_inlining_row_limit` is not 0. Jinja cannot run a query, so dbt would lose
  the guard unless the wrapper from point 1 also ran `attach()` first. By then
  both implementations exist anyway.

**3. The password could leak.** When a connect fails, DuckDB includes the full
catalog URI, password in cleartext, in its error message. `attach()` redacts it.
In the YAML version the error would go straight into dbt's console output and
`logs/dbt.log`. dbt has a native fix: it masks any env var whose name starts with
`DBT_ENV_SECRET_`. But the wrapper would then have to rename
`DUCKLAKE_CATALOG_URI` to `DBT_ENV_SECRET_DUCKLAKE_CATALOG_URI`, and
@docs/secrets.md chose one set of names with no mapping layer. With the plugin
the credentials never enter dbt's config, so there is nothing of theirs in
`target/` or `logs/` to mask.

**4. The environment would come from the process, not the command.** With env
vars, which lakehouse dbt builds into depends on whichever values happen to be in
the process. Here the environment is always an argument
(`python -m utils.lakehouse … prod`). With the plugin it is `--target prod`, and a
missing target fails before anything connects. In Prefect, the flow passes
`--target` rather than rewriting `os.environ` for a whole process.

**What the env-var route has going for it.**

- **It is documented.** Anyone who knows dbt reads it at a glance. The plugin
  relies on the order in which dbt-duckdb runs plugins and `attach:` entries,
  read from the 1.11.0 source and not in the README. That is the upgrade risk in
  [When it breaks](#when-it-breaks).
- **The profile would be self-contained.** Other tools that only read
  `profiles.yml` would see a complete connection. Here they see the placeholder
  `ducklake:`.

One attach implementation was judged worth more than those two. Going the
conventional way instead costs the wrapper plus the renaming.

## Schemas

Each layer is a folder under `models/`, and `dbt_project.yml` gives the folder
its schema: `<schema>/` builds into `lake.<schema>`.

dbt's default would name it `main_<schema>` — the target's schema, then the
model's. `macros/generate_schema_name.sql` overrides that to use the layer's name
as-is, because names are identical in every environment (@docs/conventions.md).
The profile's `schema: main` is only the fallback for a model outside any layer.

Sources are declared in `models/sources.yml`, pointing at `lake.raw`.

## What a table build leaves behind

A `table` model is built as `<table>__dbt_tmp`, then the old table is dropped and
the new one renamed. Two consequences in the bucket:

**Files keep the path they were written under.** DuckLake records the file path
at write time and a rename does not move anything, so `<schema>.<table>__<source>`
lives at:

```
s3://<bucket>/<environment>/<schema>/<table>__<source>__dbt_tmp/ducklake-<uuid>.parquet
```

**Every run rewrites the whole table**, and the previous run's files stay
behind, referenced by old snapshots, until snapshot expiry and file cleanup
remove them.

## Maintenance

`macros/maintain_ducklake.sql`, adapted from the MotherDuck recipe. It is a
`run-operation`, so `dbt run` never triggers it:

```bash
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace/transform \
  localhost/the-broke-lakehouse dbt run-operation maintain_ducklake --target prod \
  --args '{retention: 7 days}'
```

In order: merge small adjacent files, expire snapshots older than `retention`,
delete the files no remaining snapshot references, delete orphaned files older
than `retention`.

`retention` is required, any DuckDB interval (`1 minute`, `12 hours`,
`30 days`), and it is how far back time travel reaches afterwards. No default,
like the target: how much history a run destroys is chosen in the command.
Without it the macro refuses before touching anything.

It covers the whole lakehouse, `raw` included, not only what dbt builds.

## Threads

`threads: 1`. DuckLake holds one Neon connection per DuckDB thread
(@docs/data-storage.md), so more dbt threads add Postgres connections as well as
parallelism. With one model there is nothing to parallelise; raise it once there
is, and watch for `all 8 connections in use`.
