"""Milestone 7: a reader's credentials read `gold`, and every write is refused.

    podman run --env-file .env.reader --rm -v $(pwd):/workspace \
      localhost/broke-lakehouse python -m pytest tests/test_reader.py -v --reader

Opt-in with --reader: with a writer's credentials the writes below succeed,
which is a failure here (and is undone at once), so a plain `pytest tests/`
with the writer's .env.runner skips this file.

Each write fails in a different place, so each test proves one credential:
a CREATE SCHEMA only touches the catalog (the Neon role), a CREATE TABLE AS
writes its Parquet file to the bucket before it commits to the catalog (the
storage key). @docs/access.md
"""

import duckdb
import pytest

from broke_lakehouse.client import LAKE, _persisted_limit, attach

PROBE = "reader_probe"


@pytest.fixture(scope="module")
def con(request, environment):
    if not request.config.getoption("--reader"):
        pytest.skip("needs a reader's credentials and --reader")
    con = attach(environment)  # the initialised-catalog guard doubles as a catalog read
    yield con
    con.close()


def refused(con, sql: str, undo: str) -> str:
    """The error a write raised. If it went through, undo it and fail."""
    try:
        con.sql(sql)
    except duckdb.Error as e:
        return str(e)
    con.sql(undo)
    pytest.fail(f"a reader could run: {sql}")


def test_reads_gold(con):
    """Any gold table, so the test holds for whatever models a project has: the
    listing reads the catalog (the Neon role), the SELECT a Parquet file (the key)."""
    tables = con.sql("SELECT table_name FROM duckdb_tables() "
                     f"WHERE database_name = '{LAKE}' AND schema_name = 'gold'").fetchall()
    assert tables, "nothing in gold: has the pipeline run?"
    con.sql(f"SELECT * FROM {LAKE}.gold.{tables[0][0]} LIMIT 1").fetchall()


def test_catalog_refuses_a_write(con):
    error = refused(con, f"CREATE SCHEMA {LAKE}.{PROBE}", f"DROP SCHEMA {LAKE}.{PROBE}")
    assert "permission denied" in error.lower(), error  # Postgres's wording, not a typo in our SQL


def test_catalog_refuses_an_option(con):
    before = _persisted_limit(con)
    error = refused(con, f"CALL {LAKE}.set_option('data_inlining_row_limit', 1000)",
                    f"CALL {LAKE}.set_option('data_inlining_row_limit', {before})")
    assert "permission denied" in error.lower(), error


def test_storage_refuses_a_write(con):
    error = refused(con, f"CREATE TABLE {LAKE}.gold.{PROBE} AS SELECT 1 AS x",
                    f"DROP TABLE {LAKE}.gold.{PROBE}")
    assert "403" in error, error  # the bucket said Forbidden, not the catalog
