# Access

How a researcher reads the lakehouse from their own machine. Researchers use the
same `attach()` as the pipeline. Read-only credentials, not the code, stop them
from writing.

## Install

The package alone brings only `duckdb` and `infisicalsdk`. dlt, dbt and Prefect
come with the `pipeline` extra, which only `requirements.txt` asks for.

```bash
python -m venv .venv && . .venv/bin/activate
pip install "broke-lakehouse @ git+https://github.com/GLaddaga/broke-lakehouse@<tag>" jupyterlab
set -a; . ./.env.reader; set +a      # the reader's three Infisical variables
```

```python
from broke_lakehouse.client import LAKE, attach
con = attach("prod")
con.sql(f"SELECT * FROM {LAKE}.gold.revenue_monthly__tpch")
```

- **Pin a tag** and move it when the pipeline bumps DuckDB: a different DuckDB
  version may not open the catalog.
- The first `attach()` downloads three DuckDB extensions.
- Neon can drop the first connection after it has been idle. Retry once.

Sample notebooks are in `analyse/`. To run them in this repo's container:

```bash
podman run --env-file .env.reader --rm -it -p 8888:8888 -v $(pwd):/workspace \
  localhost/broke-lakehouse \
  jupyter lab --ip 0.0.0.0 --no-browser --allow-root --notebook-dir analyse
```

## Read-only credentials

All of it is tofu (@docs/infrastructure.md). Every apply writes `.env.reader`,
and its three values are what a researcher receives.

- **Tigris:** a key whose policy allows only `GetObject` and `ListBucket` on the bucket.
- **Neon:** `<lakehouse>_reader`, created in SQL as the runner, because a role
  made through the console or API joins `neon_superuser` and can write. It gets
  `CONNECT`, `USAGE` on `public`, `SELECT` on its tables, and default privileges
  for tables the runner adds later (DuckLake creates them at `initialise`).
- **Infisical:** a separate project, `<lakehouse>-reader`, so the reader
  identity never sees the write keys. The secret names and the `prod` slug are
  the same as the writer's, so the code doesn't change.

## Check

```bash
podman run --env-file .env.reader --rm -v $(pwd):/workspace \
  localhost/broke-lakehouse python -m pytest tests/test_reader.py -v --reader
```

The test reads `gold`, then tries two writes. Each must be refused by a
different credential:

| Write | Must fail with | Proves |
|---|---|---|
| `CREATE SCHEMA` | `permission denied` | the Neon role |
| `CREATE TABLE AS` | `403` | the storage key |

The `--reader` flag keeps the test from running with the writer's credentials.
If a write ever goes through, the test undoes it and fails.
