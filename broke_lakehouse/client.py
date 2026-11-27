"""Connecting to the lakehouse, and nothing else: what a reader uses.

    from broke_lakehouse.client import LAKE, attach
    con = attach("prod")
    con.sql(f"SELECT * FROM {LAKE}.gold.revenue_monthly__tpch")

The pipeline uses this same code (`broke_lakehouse/ops.py` builds the hand-run
operations on top of it), so readers and writers stay on one DuckDB pin, one
alias and one way of attaching. Imports only duckdb and the secret manager,
which is all a reader installs. What a caller can do is set by the credentials
the Infisical identity hands out, not by this code. @docs/access.md
"""

from urllib.parse import parse_qsl, unquote, urlparse

import duckdb

from broke_lakehouse.secrets import get_secrets

# The attach alias, set once per project: a DuckLake view stores it in its SQL,
# so renaming it after the first view breaks that view. dbt's copy is the
# `database:` and `attach:` entry in transform/profiles.yml. @docs/conventions.md
LAKE = "lake"

NAMES = [
    "DUCKLAKE_CATALOG_URI",
    "DUCKLAKE_DATA_PATH",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ENDPOINT_URL_S3",
    "AWS_REGION",
]


def _sql(value: str) -> str:
    """
    A value as a SQL string literal. DuckDB escapes a quote by doubling it, so
    a password containing one stops truncating the statement it sits in.
    """
    return "'" + value.replace("'", "''") + "'"


def _path(secrets: dict[str, str]) -> tuple[str, str]:
    """
    `s3://bucket/prefix/` split into the two halves S3 APIs want separately.

    The trailing slash is added rather than required: `ATTACH` records DATA_PATH
    in the catalog permanently, so a secret typed `…/prod` instead of `…/prod/`
    would be a one-way mistake. Normalising here means every caller — the
    listing, the guard in initialise(), the attach itself — sees one spelling.
    """
    url = urlparse(secrets["DUCKLAKE_DATA_PATH"])
    return url.netloc, url.path.strip("/") + "/"


def _persisted_limit(con: duckdb.DuckDBPyConnection) -> str | None:
    """The limit persisted in the catalog, None if it was never set."""
    row = con.sql(f"SELECT value FROM {LAKE}.options() WHERE scope = 'GLOBAL' "
                  "AND option_name = 'data_inlining_row_limit'").fetchone()
    return row and row[0]


def _assert_initialised(con: duckdb.DuckDBPyConnection) -> None:
    """
    Refuse a catalog that initialise() did not finish. DuckLake does not persist
    an ATTACH-time limit, so creating the catalog and setting the limit are two
    steps; one that died in between leaves no limit, which DuckLake reads as
    inlining writes of up to 10 rows into Neon.
    """
    if _persisted_limit(con) is None:
        raise RuntimeError("data_inlining_row_limit is not set: the catalog was not "
                           "created by initialise — `configure <environment>` sets it")


def credentials(environment: str, con: duckdb.DuckDBPyConnection) -> None:
    """The three secrets from docs/data-storage.md, on `con`: everything the
    attach needs, so that the attach itself carries no credential.

    Split from attach() for dbt-duckdb, which runs the ATTACH itself from
    `profiles.yml` once `broke_lakehouse/dbt_plugin.py` has called this.
    """
    secrets = get_secrets(NAMES, environment=environment)
    for extension in ("ducklake", "httpfs", "postgres"):
        # Prefect's managed pool doesn't run our image, and nor does a reader's
        # own environment, so nothing is baked in there. A no-op where the
        # extension is already installed.
        con.install_extension(extension)
        con.load_extension(extension)
    # PROVIDER config with the key pair passed directly: the non-AWS S3 stores
    # issue long-lived key pairs only — no STS, no session tokens — so a
    # credential chain has nothing to discover. Every value comes from Infisical,
    # so no provider is named here. ENDPOINT wants the bare host, hence urlparse.
    con.sql(f"""
        CREATE OR REPLACE SECRET storage (
            TYPE s3, PROVIDER config,
            KEY_ID   {_sql(secrets["AWS_ACCESS_KEY_ID"])},
            SECRET   {_sql(secrets["AWS_SECRET_ACCESS_KEY"])},
            ENDPOINT {_sql(urlparse(secrets["AWS_ENDPOINT_URL_S3"]).netloc)},
            REGION   {_sql(secrets["AWS_REGION"])},
            URL_STYLE 'vhost'
        )""")
    # The catalog URI as a postgres secret, one libpq keyword per part: DuckDB
    # redacts PASSWORD and leaves it out of connect errors, which a URI inside
    # the ATTACH or METADATA_PATH would echo whole.
    uri = urlparse(secrets["DUCKLAKE_CATALOG_URI"])
    if uri.scheme not in ("postgresql", "postgres"):
        raise RuntimeError("DUCKLAKE_CATALOG_URI is not a postgresql:// URI")
    catalog = {"HOST": uri.hostname, "PORT": uri.port and str(uri.port),
               "DBNAME": uri.path.lstrip("/"), "USER": unquote(uri.username or ""),
               "PASSWORD": unquote(uri.password or ""),
               **{key.upper(): value for key, value in parse_qsl(uri.query)}}
    con.sql(f"""
        CREATE OR REPLACE SECRET catalog (
            TYPE postgres,
            {", ".join(f"{key} {_sql(value)}" for key, value in catalog.items() if value)}
        )""")
    # Named after LAKE, like the database, and attached as `ducklake:<LAKE>`.
    bucket, prefix = _path(secrets)  # normalised, so the recorded path ends in /
    con.sql(f"""
        CREATE OR REPLACE SECRET {LAKE} (
            TYPE ducklake,
            METADATA_PATH '',
            METADATA_PARAMETERS MAP {{'TYPE': 'postgres', 'SECRET': 'catalog'}},
            DATA_PATH {_sql(f"s3://{bucket}/{prefix}")}
        )""")


def attach(environment: str, *, create: bool = False, verify: bool = True) -> duckdb.DuckDBPyConnection:
    """
    Opens connection, loads credentials in DuckDB secret objects and attaches DuckLake.
    Creates DuckLake if it does not exist only when `create` is set as `True` (only in `initialise()` as we don't want empty catalogs created accidentally).
    """
    con = duckdb.connect()
    credentials(environment, con)
    con.sql(f"ATTACH 'ducklake:{LAKE}' AS {LAKE} (CREATE_IF_NOT_EXISTS {str(create).lower()})")
    if verify:
        _assert_initialised(con)
    return con
