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

## Setup: read-only credentials

**Tigris:** a new access key, role **ReadOnly**, scoped to the bucket.

**Neon:** create the role in SQL. A role made in the console joins
`neon_superuser` and can write. Run this as `<lakehouse>_runner` on
`ducklake_catalog`, with a strong password (`openssl rand -hex 24`):

```sql
CREATE ROLE <lakehouse>_reader WITH LOGIN PASSWORD '<generated>';
GRANT CONNECT ON DATABASE ducklake_catalog TO <lakehouse>_reader;
GRANT USAGE ON SCHEMA public TO <lakehouse>_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO <lakehouse>_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE <lakehouse>_runner IN SCHEMA public
  GRANT SELECT ON TABLES TO <lakehouse>_reader;   -- tables added by future DuckLake versions
```

Its `DUCKLAKE_CATALOG_URI` is the runner's unpooled string with the reader's
role and password.

**Infisical:** a separate project, so the reader identity never sees the write
keys. The code doesn't change: the secret names and the `prod` slug are the same.

1. Create project `<lakehouse>-reader`, with environment slug `prod`.
2. Add the six contract secrets (@docs/secrets.md) with the reader URI and the
   ReadOnly key pair. Path, endpoint and region are the same as the writer's.
   Add `TEST_SECRET=it-works` too.
3. Create identity `<lakehouse>-reader` with org role **No Access** and
   Universal Auth. Make it **Viewer** on this project only.
4. Put its client ID and secret and the project ID in a gitignored `.env.reader`.
   These three values are what a researcher receives.

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
