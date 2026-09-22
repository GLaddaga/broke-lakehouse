"""The lakehouse itself: attaching to it, and the hand-run operations on it.

    python -m utils.lakehouse survey     prod   # what is there, read-only (exit 1 if occupied)
    python -m utils.lakehouse initialise prod   # create the catalog, once per lakehouse
    python -m utils.lakehouse initialise prod --force   # purge first (asks), then create
    python -m utils.lakehouse reset      prod   # empty it, keep the catalog (asks first)
    python -m utils.lakehouse purge      prod   # destroy it, catalog and all (asks first)

The environment is required and never defaulted. It is the one word that names
the Infisical slug, the Neon branch and the bucket prefix, so it selects which
lakehouse a command touches — and that belongs in the command, visibly.
"""

import argparse
import sys
from urllib.parse import urlparse

import boto3
import duckdb

from utils.infisical import get_secrets

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


def _redact(error: Exception, uri: str) -> RuntimeError:
    """
    DuckDB echoes the whole connection string, password included, when a
    connect fails. Keep it out of tracebacks and CI logs.
    """
    return RuntimeError(str(error).replace(uri, "<catalog uri>"))


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


def _s3(secrets: dict[str, str]):
    """
    The bucket seen without DuckDB in the way: asking DuckDB to confirm
    DuckDB's own writes would trust a listing it may still have cached.
    """
    return boto3.client(
        "s3",
        endpoint_url=secrets["AWS_ENDPOINT_URL_S3"],
        region_name=secrets["AWS_REGION"],
        aws_access_key_id=secrets["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=secrets["AWS_SECRET_ACCESS_KEY"],
    )


def _pg(secrets: dict[str, str]) -> duckdb.DuckDBPyConnection:
    """
    Neon as plain Postgres, no DuckLake involved, so the `ducklake_*` tables
    are visible as the ordinary tables they are.
    """
    con = duckdb.connect()
    con.load_extension("postgres")
    try:
        con.sql(f"ATTACH {_sql(secrets['DUCKLAKE_CATALOG_URI'])} AS pg (TYPE postgres)")
    except duckdb.Error as e:
        raise _redact(e, secrets["DUCKLAKE_CATALOG_URI"]) from None
    return con


def attach(environment: str) -> duckdb.DuckDBPyConnection:
    """The two statements from docs/data-storage.md, nothing else."""
    secrets = get_secrets(NAMES, environment=environment)
    con = duckdb.connect()
    for extension in ("ducklake", "httpfs", "postgres"):
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
    try:
        bucket, prefix = _path(secrets)  # normalised, so the recorded path ends in /
        con.sql(f"""
            ATTACH {_sql("ducklake:postgres:" + secrets["DUCKLAKE_CATALOG_URI"])} AS lake
                   (DATA_PATH {_sql(f"s3://{bucket}/{prefix}")})""")
    except duckdb.Error as e:
        raise _redact(e, secrets["DUCKLAKE_CATALOG_URI"]) from None
    return con


def survey(secrets: dict[str, str]) -> tuple[list[str], list[str]]:
    """
    What is already there: `ducklake_*` tables in Neon, objects under the
    prefix. Two empty lists mean a lakehouse that does not exist yet.
    """
    bucket, prefix = _path(secrets)
    # Prefix= because the data path is prefixed: a bucket-wide listing would also
    # count objects belonging to another environment.
    pages = _s3(secrets).get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix)
    # The bare prefix is not content. Creating the folder in a storage console
    # leaves a zero-byte object keyed exactly `prod/`, while S3 prefixes are
    # virtual and DuckLake never needs one — so counting it would make a bucket
    # built through the UI look non-empty forever, and initialise() refuse it.
    objects = sorted(o["Key"] for p in pages for o in p.get("Contents", [])
                     if o["Key"] != prefix)

    pg = _pg(secrets)
    tables = [r[0] for r in pg.sql(
        "select * from postgres_query('pg', $$select tablename from pg_tables "
        "where schemaname='public' and starts_with(tablename, 'ducklake_')$$)").fetchall()]
    pg.close()
    return tables, objects


def initialise(environment: str, *, force: bool = False) -> None:
    """
    Create the catalog and persist the options every later client inherits.
    """
    secrets = get_secrets(NAMES, environment=environment)
    bucket, prefix = _path(secrets)
    # The prefix has to be the environment's own: a mismatch means the wrong
    # environment's secrets, or a typo about to be written into the catalog for
    # good. This is also what keeps `dev` from being initialised over `prod/`.
    if prefix != f"{environment}/":
        raise RuntimeError(
            f"DUCKLAKE_DATA_PATH is s3://{bucket}/{prefix}, expected the {environment}/ "
            "prefix — the catalog records this permanently")
    if force:  # after the prefix check, so a misconfigured path is never purged
        purge(environment)  # lists, asks for the name; returns at once if empty
    tables, objects = survey(secrets)
    if tables or objects:
        raise RuntimeError(f"{environment} is not an empty lakehouse, refusing to "
                           f"initialise: {len(tables)} table(s) in Neon, {len(objects)} "
                           f"object(s) in the bucket — `survey {environment}` lists them")

    con = attach(environment)  # the first attach is what creates the ducklake_* tables
    # No table_name/schema_name, so this is the global scope: one row in
    # ducklake_metadata, read by every connection from now on.
    con.sql("CALL lake.set_option('data_inlining_row_limit', 0)")
    con.close()


def _list(heading: str, lines: list[str]) -> None:
    """Capped, so a real lakehouse does not scroll the prompt off screen."""
    print(heading)
    for line in lines[:40]:
        print(f"  {line}")
    if len(lines) > 40:
        print(f"  … and {len(lines) - 40} more")


def _show(environment: str, tables: list[str], objects: list[str]) -> None:
    """What survey() found."""
    _list(f"{environment}: {len(tables)} ducklake_* table(s) in Neon, "
          f"{len(objects)} object(s) in the bucket",
          [f"neon    {t}" for t in tables] + [f"bucket  {o}" for o in objects])


def _confirm(environment: str) -> None:
    """Require the environment name back before anything is destroyed."""
    try:
        typed = input(f'type "{environment}" to destroy all of it: ')
    except EOFError:  # the documented command needs podman's -it for this to work
        raise RuntimeError("no terminal to confirm on — run podman with -it") from None
    if typed != environment:
        raise RuntimeError(f"typed {typed!r}, expected {environment!r} — nothing removed")


def purge(environment: str) -> tuple[list[str], list[str]]:
    """
    Destroy the lakehouse: every `ducklake_*` table in Neon, every object
    under the prefix. Lists them, asks, and returns what it removed.

    For a half-created catalog that `initialise()` refuses to touch. Needs a
    terminal, so run it with `podman run -it`.
    """
    secrets = get_secrets(NAMES, environment=environment)
    tables, objects = survey(secrets)
    if not tables and not objects:
        return [], []  # nothing to destroy, so nothing to confirm
    _show(environment, tables, objects)
    _confirm(environment)

    if names := ", ".join(f'"{t}"' for t in tables):
        pg = _pg(secrets)
        pg.sql(f"CALL postgres_execute('pg', 'DROP TABLE IF EXISTS {names} CASCADE')")
        pg.close()

    bucket, _ = _path(secrets)
    s3 = _s3(secrets)
    for batch in range(0, len(objects), 1000):  # delete_objects takes 1000 at a time
        s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in objects[batch:batch + 1000]]})
    return tables, objects


def _contents(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
    """
    (kind, schema, name) of everything the attached lake holds, views first
    so that dropping in this order never pulls a table out from under a view.
    """
    return con.sql("""
        SELECT * FROM (
            SELECT 'VIEW' AS kind, schema_name AS s, view_name AS n FROM duckdb_views()
             WHERE database_name = 'lake' AND NOT internal 
            UNION ALL
            SELECT 'TABLE', schema_name, table_name FROM duckdb_tables()
             WHERE database_name = 'lake')
        ORDER BY kind = 'TABLE', s, n""").fetchall()


def _empty(con: duckdb.DuckDBPyConnection) -> None:
    """
    Drop everything in the attached lake and delete its files, leaving the
    catalog and its options exactly as initialise() made them.
    """
    for kind, schema, name in _contents(con):
        con.sql(f'DROP {kind} lake."{schema}"."{name}"')
    for (schema,) in con.sql(
            "SELECT schema_name FROM duckdb_schemas() WHERE database_name = 'lake' "
            "AND NOT internal AND schema_name <> 'main'").fetchall():
        con.sql(f'DROP SCHEMA lake."{schema}"')  # dlt's `raw` and the like
    con.sql("CALL ducklake_expire_snapshots('lake', older_than => now())")
    con.sql("CALL ducklake_cleanup_old_files('lake', cleanup_all => true)")
    # Files no snapshot ever recorded — a write that failed halfway. Without this
    # a reset lake could still hold objects that survey() counts.
    con.sql("CALL ducklake_delete_orphaned_files('lake', cleanup_all => true)")


def reset(environment: str) -> list[str]:
    """Empty the lakehouse but keep it: every table, view and schema other than
    `main` dropped and their files deleted, the catalog and its options untouched.
    Ready to write straight away. Returns what it dropped.

    Same end state as `purge` then `initialise`, without the moment in between
    when there is no catalog. Asks first, like purge — it destroys every table.
    """
    con = attach(environment)
    try:
        found = [f"{kind.lower():5}  {schema}.{name}" for kind, schema, name in _contents(con)]
        if found:  # nothing to confirm otherwise, but still expire and clean up
            _list(f"{environment}: {len(found)} table(s) and view(s) in the lakehouse", found)
            _confirm(environment)
        _empty(con)
    finally:
        con.close()
    return found


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m utils.lakehouse")
    parser.add_argument("command", choices=["survey", "initialise", "reset", "purge"])
    parser.add_argument("environment",
                        help="Infisical slug, Neon branch and bucket prefix")
    parser.add_argument("--force", action="store_true",
                        help="initialise only: purge an existing lakehouse first, "
                             "after the same typed confirmation")
    args = parser.parse_args()
    if args.force and args.command != "initialise":
        parser.error("--force only applies to initialise")
    env = args.environment
    try:
        if args.command == "survey":
            tables, objects = survey(get_secrets(NAMES, environment=env))
            _show(env, tables, objects)
            # 0 empty, 1 occupied — so `survey && initialise` reads as a sentence
            # and a script need not parse the listing.
            sys.exit(1 if tables or objects else 0)
        elif args.command == "initialise":
            initialise(env, force=args.force)
            print(f"{env}: catalog created, data_inlining_row_limit persisted as 0")
        elif args.command == "reset":
            print(f"{env}: dropped {len(reset(env))} table(s) and view(s), catalog kept")
        else:
            tables, objects = purge(env)
            print(f"{env}: removed {len(tables)} table(s) and {len(objects)} object(s)")
    except RuntimeError as e:  # refusals are messages, not tracebacks
        sys.exit(f"error: {e}")
