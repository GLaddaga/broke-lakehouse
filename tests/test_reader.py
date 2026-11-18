"""Milestone 7: a reader's credentials read `gold`, and every write is refused.

    podman run --env-file .env.reader --rm -v $(pwd):/workspace \
      localhost/broke-lakehouse python -m pytest tests/test_reader.py -v --reader

Opt-in with --reader: with a writer's credentials the writes below succeed,
which is a failure here (and is undone at once), so a plain `pytest tests/`
with the writer's .env skips this file.

Each write fails in a different place, so each test proves one credential:
a CREATE SCHEMA only touches the catalog (the Neon role), a CREATE TABLE AS
writes its Parquet file to the bucket before it commits to the catalog (the
storage key). @docs/access.md
"""

import duckdb
import pytest

from broke_lakehouse.client import LAKE, attach

PROBE = "reader_probe"


@pytest.fixture(scope="module")
def con(request, environment):
    if not request.config.getoption("--reader"):
        pytest.skip("needs a reader's credentials and --reader")
    con = attach(environment)  # the inlining guard doubles as a catalog read
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
    assert con.sql(f"SELECT count(*) FROM {LAKE}.gold.revenue_monthly__tpch").fetchone()[0] > 0


def test_catalog_refuses_a_write(con):
    error = refused(con, f"CREATE SCHEMA {LAKE}.{PROBE}", f"DROP SCHEMA {LAKE}.{PROBE}")
    assert "permission denied" in error.lower(), error  # Postgres's wording, not a typo in our SQL


def test_storage_refuses_a_write(con):
    error = refused(con, f"CREATE TABLE {LAKE}.gold.{PROBE} AS SELECT 1 AS x",
                    f"DROP TABLE {LAKE}.gold.{PROBE}")
    assert "403" in error, error  # the bucket said Forbidden, not the catalog
