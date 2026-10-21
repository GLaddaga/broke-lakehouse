# Transformation

Data transformation in the lakehouse happens through dbt, 
whose project lives in the `transform/` folder.
This document describes the architectural choices made for dbt
and provides instructions on how to run it.

## Run

With the environment as the target:

```bash
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace/transform \
  localhost/the-broke-lakehouse dbt run --target prod
```

`-w /workspace/transform` is only so that dbt finds `dbt_project.yml` and
`profiles.yml` without flags. From anywhere else, `--project-dir transform
--profiles-dir transform` does the same. The plugin imports from any working
directory, because `utils` is an installed package (`-e .` in
`requirements.txt`).

There is no default target. A bare `dbt run` fails with *does not have a target
named 'default'*, on purpose: which lakehouse gets built into belongs in the
command.

## How it attaches: `profiles.yml`

A DuckLake needs the same secrets and `ATTACH` from every client
(@docs/data-storage.md). Only the secrets need credentials. The `ATTACH` is
`ATTACH 'ducklake:lake' AS lake`, where `ducklake:lake` names a secret, not a
catalog. So the work splits cleanly:

- a dbt-duckdb plugin, `utils/dbt_plugin.py`, calls `credentials()` from
  `utils/lakehouse.py` on dbt-duckdb's connection, creating the secrets with
  values from Infisical;
- `profiles.yml` declares the `ATTACH`, and dbt-duckdb runs it like any other
  attach.

Both are dbt-duckdb's documented extension points, used for what they are for.
`profiles.yml` holds no credentials, and every line in it does what it says.

### The file

```yaml
lakehouse:
  outputs:
    prod:
      type: duckdb
      database: lake
      schema: main
      threads: 1
      plugins:
        - module: utils.dbt_plugin
          config:
            environment: prod
      attach:
        - path: "ducklake:lake"
          alias: lake
```

### What happens when dbt connects

When a dbt command first needs the database, dbt-duckdb does the following, in
this order:

1. **Builds the plugin.** It imports `utils.dbt_plugin` and passes the `config:`
   mapping to `Plugin.initialize`. That method keeps `environment: prod`, then
   runs `attach("prod")` once on a throwaway connection and closes it. This is
   the `data_inlining_row_limit = 0` guard, done the same way `destination()`
   does it for dlt: dbt's own attach happens in step 5, after the last plugin
   hook, where nothing could check it. It also means a wrong password or an
   unreachable Neon stops the run here, before dbt has done anything. Cost: one
   extra Neon round trip per dbt command.
2. **Opens DuckDB.** `duckdb.connect(path)`. The profile sets no `path`, so it is
   `:memory:`: an empty, in-memory database named `memory`. It stays empty. The
   lakehouse is attached next to it, not opened as it.
3. **Loads the profile's `extensions:` and creates its `secrets:`.** The profile
   declares neither, so nothing happens here.
4. **Runs each plugin's `configure_connection(conn)`.** The plugin calls
   `credentials("prod", conn)`. It fetches the six values from Infisical's `prod`
   environment, loads `ducklake`, `httpfs` and `postgres`, and creates the three
   secrets: `storage` (S3), `catalog` (Neon, as a postgres secret) and `lake`
   (the DuckLake: catalog secret plus data path).
5. **Runs each `attach:` entry.** `ATTACH IF NOT EXISTS 'ducklake:lake' AS lake`.
   DuckLake resolves `lake` to the secret from step 4 and connects to Neon.

The connection is kept open for the rest of the invocation (dbt-duckdb's
`keep_open`, on by default). Each dbt thread works on a cursor of that
connection, so steps 2 to 5 happen once per `dbt` command, not once per model.

Two things run earlier, when dbt reads the profile before connecting. Both come
from the `attach:` entry:

- **`database: lake` is validated.** dbt-duckdb checks the `database` field
  against the database name taken from `path` (`memory`) and against the
  `alias` of every `attach:` entry. `lake` matches the alias.
- **`lake` is recorded as a DuckLake.** Any attach entry whose path contains
  `ducklake:` puts its alias in a set that dbt-duckdb's macros consult through
  `adapter.is_ducklake()`. Membership changes the generated SQL: DuckLake has
  no `DROP … CASCADE`, so the macros leave it out.

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

**`plugins:`** `module` is the Python module, which must define a class called
`Plugin`. `config` is passed to the plugin, merged over the profile's
`settings:` (none here). The plugin reads only `environment`. It imports from
anywhere because the repo is installed as a package: the `dbt` executable lives
in `/usr/local/bin`, and Python would otherwise put only that directory, not
the repo, on `sys.path`.

**`attach:`** The attach. `path: "ducklake:lake"` is DuckLake's syntax for
"attach using the ducklake secret called `lake`", and `alias: lake` is the name
it gets. It fails with *Secret "lake" was not found* if the plugin did not run.

### What is deliberately absent

| Key | Why it is not there |
|---|---|
| `path` | The lakehouse is attached, not opened. `:memory:` gives an empty scratch database and no local file to manage |
| `extensions` | `credentials()` loads `ducklake`, `httpfs` and `postgres` itself. The image already has them installed |
| `secrets` | `credentials()` creates them, with values from Infisical |
| any `env_var()` | No value comes from the environment. The only env vars involved are Infisical's bootstrap three, read by `utils/secrets/infisical.py`, not by dbt |
| `module_paths` | `utils` is installed (`-e .`), so no `sys.path` entry is needed and nothing depends on the working directory |
| `settings` | No DuckDB setting needs changing yet. If the Neon connection limit ever bites, `threads` for DuckDB goes here |
| `is_ducklake` | Only needed when the path has no `ducklake:` scheme, which is MotherDuck's case. |

### What `utils/dbt_plugin.py` adds

One class, two methods: `initialize` keeps `environment` and runs the guard,
and `configure_connection` calls `credentials(self.environment, conn)`. The
secrets are split out of `attach()` into `credentials()` so that the plugin and
`attach()` create them with the same code. `attach()` is now `credentials()`
plus `ATTACH 'ducklake:lake' AS lake` on a connection of its own.

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
| *Unable to import module 'utils.dbt_plugin'* | the repo is not installed: an image built before `-e .` was added to `requirements.txt` — rebuild it |
| *Inconsistency detected between 'path' and 'database'* | the `attach:` entry was removed, or its `alias` no longer matches `database` |
| *Secret "lake" was not found* | the `plugins:` entry was removed, or a dbt-duckdb upgrade runs `attach:` before plugins |
| a connect error from Neon | Neon unreachable or credentials wrong. The password is never in it: it sits in the postgres secret, which DuckDB does not echo |
| `DROP … CASCADE` not supported | `lake` is not recognised as a DuckLake: the `attach:` path lost its `ducklake:` |

**Upgrade risk.** The design depends on dbt-duckdb running plugins'
`configure_connection` before `attach:` entries, which is what the hook is for:
a plugin prepares the connection. If an upgrade reversed the order, the
`ATTACH` would find no secret and fail with *Secret "lake" was not found* before
anything reaches Neon or the bucket. A breaking upgrade shows up as a failed
run, never as data written somewhere else. `dbt-duckdb` is pinned exactly in
`requirements.txt`, so this can only happen on a deliberate bump, and one
`dbt run` afterwards is the whole check.

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
