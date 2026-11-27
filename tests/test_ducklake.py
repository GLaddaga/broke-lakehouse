"""End-to-end check that an environment is reachable and that data actually flows.

    podman run --env-file .env.runner --rm -v $(pwd):/workspace \
      localhost/broke-lakehouse python -m pytest tests/test_ducklake.py -v \
      --lakehouse-env <environment>

Fetches the Neon and object-storage credentials from Infisical, creates the
catalog with `initialise()`, writes one row, reads it back from a genuinely fresh
process, and asserts the row travelled as Parquet in object storage rather than
as inlined rows in Neon. Then removes every trace — the file, the snapshots and
the `ducklake_*` catalog tables — and asserts both providers end empty.

Runs only against an empty Neon schema and an empty prefix, and skips otherwise:
the teardown drops the catalog itself, so this is a pre-flight check for a lake
that does not exist yet, not a monitoring tool. Once a lakehouse is initialised
it skips for that environment forever.
"""

import os
import subprocess
import sys

import duckdb
import pytest

from broke_lakehouse.client import LAKE, NAMES, _assert_initialised, _path, _sql, attach
from broke_lakehouse.secrets import get_secrets
from broke_lakehouse.ops import (_apply_inlining_options, _confirm, _contents, _empty,
                                 _pg, _project_limit, initialise, survey)

TABLE = "_roundtrip"

needs_credentials = pytest.mark.skipif(
    not os.environ.get("INFISICAL_CLIENT_ID"), reason="no bootstrap credentials"
)


def test_confirm_refuses_another_environments_name(monkeypatch):
    """The guard in front of reset and purge, checked without touching anything:
    a marker decorates the round trip below rather than the module, so this one
    still runs in a clone with no credentials. The names are only labels."""
    monkeypatch.setattr("builtins.input", lambda _: "prod")
    _confirm("prod")  # the right name: returns
    with pytest.raises(RuntimeError, match="nothing removed"):
        _confirm("dev")  # prod typed at dev's prompt: refuses


def test_sql_literal_survives_a_quote():
    """Every credential reaches DuckDB inside a string literal, so a password
    with a quote in it must not be able to end that literal early."""
    password = "pa'ss"
    assert _sql(password) == "'pa''ss'"
    con = duckdb.connect()
    assert con.sql(f"SELECT {_sql(password)} AS v").fetchall() == [(password,)]


def test_empty_keeps_the_catalog(tmp_path):
    """reset()'s work, on a local DuckLake — a file catalog and a directory for
    DATA_PATH — so it needs no credentials and cannot reach a real lakehouse."""
    con = duckdb.connect()
    con.load_extension("ducklake")
    con.sql(f"ATTACH 'ducklake:{tmp_path}/catalog.ducklake' AS {LAKE} "
            f"(DATA_PATH '{tmp_path}/data/')")
    con.sql(f"CALL {LAKE}.set_option('data_inlining_row_limit', 0)")
    con.sql(f"CREATE SCHEMA {LAKE}.raw")
    con.sql(f"CREATE TABLE {LAKE}.raw.events AS SELECT range AS id FROM range(3)")
    con.sql(f"CREATE VIEW {LAKE}.main.recent AS SELECT * FROM {LAKE}.raw.events")
    assert list((tmp_path / "data").rglob("*.parquet")), "setup wrote no Parquet"

    _empty(con)

    assert _contents(con) == []
    assert "raw" not in [r[0] for r in con.sql(
        f"SELECT schema_name FROM duckdb_schemas() WHERE database_name = '{LAKE}'").fetchall()]
    assert not list((tmp_path / "data").rglob("*.parquet")), "files left behind"
    assert con.sql(f"SELECT value FROM __ducklake_metadata_{LAKE}.ducklake_metadata "
                   "WHERE key = 'data_inlining_row_limit'").fetchall() == [("0",)], \
        "the catalog's options did not survive"
    con.sql(f"CREATE TABLE {LAKE}.after AS SELECT 1 AS ok")  # still a working lake


@needs_credentials
def test_roundtrip(environment):
    s = get_secrets(NAMES, environment=environment)
    assert all(s.values()), f"empty secret(s): {sorted(k for k, v in s.items() if not v)}"

    bucket, prefix = _path(s)
    pg = _pg(s)

    def ask(sql):
        return pg.sql(f"select * from postgres_query('pg', $${sql}$$)").fetchall()[0][0]

    # Both providers have to be empty, not merely free of user tables: the
    # teardown below drops the catalog itself, so anything found here would be
    # something this test is about to destroy.
    tables, objects = survey(s)
    if tables or objects:
        pytest.skip(f"{environment} is not a clean slate — {len(tables)} ducklake_* "
                    f"table(s) in Neon, {len(objects)} object(s) under {prefix}; "
                    "this test tears both down")

    # Only initialise() may create the catalog: a plain attach on an empty
    # lakehouse refuses, and the refusal must leave nothing behind in Neon.
    with pytest.raises(duckdb.InvalidInputException, match="explicitly disabled"):
        attach(environment)
    assert survey(s) == ([], []), "a refused attach left something behind"

    initialise(environment)
    con = attach(environment)  # plain attach: the limit can only come from the catalog
    try:
        assert ask("select count(*) from ducklake_metadata where key = "
                   "'data_inlining_row_limit' and value = '0' and scope is null") == 1, \
            "the inlining limit was not persisted to the catalog"

        # One row sits under DuckLake's default inlining threshold, so this fails
        # loudly if the persisted limit is ever lost or stops being honoured.
        con.sql(f"CREATE OR REPLACE TABLE {LAKE}.{TABLE} AS SELECT 42 AS answer")

        files = [r[0] for r in con.sql(
            f"SELECT data_file FROM ducklake_list_files('{LAKE}', '{TABLE}')").fetchall()]
        assert files, "no Parquet file written — the row was inlined into Neon"
        assert files[0].startswith(f"s3://{bucket}/{prefix}"), \
            f"data file is not under the configured data path: {files[0]}"
        assert ask("select count(*) from ducklake_inlined_data_tables") == 0, \
            "catalog holds inlined row data"
        # Relative paths are what will later let a Neon branch and a bucket fork
        # be rebased onto another bucket by rewriting one metadata row. This is
        # the last run against an empty catalog, so the last cheap check.
        assert ask("select bool_and(path_is_relative) from ducklake_data_file"), \
            "absolute data-file paths recorded in the catalog"

        # A second interpreter sharing no state with the writer, so a successful
        # read can only have come back through the catalog on Neon.
        fresh = subprocess.run(
            [sys.executable, "-c",
             "from broke_lakehouse.client import attach;"
             f"print(attach('{environment}').sql("
             f"'SELECT answer FROM {LAKE}.{TABLE}').fetchall()[0][0])"],
            capture_output=True, text=True)
        assert fresh.returncode == 0, fresh.stderr
        assert fresh.stdout.strip() == "42", f"fresh process read {fresh.stdout.strip()!r}"
    finally:
        _empty(con)
        con.close()  # before dropping the tables from underneath it
        if names := ", ".join(f'"{t}"' for t in survey(s)[0]):
            pg.sql(f"CALL postgres_execute('pg', 'DROP TABLE IF EXISTS {names} CASCADE')")

    tables, objects = survey(s)
    assert not objects, f"left {len(objects)} object(s) in the bucket: {objects}"
    assert not tables, f"left {len(tables)} ducklake_* table(s) in Neon: {tables}"
    pg.close()


def test_configure_repairs_and_changes_the_limit(tmp_path):
    """
    The regression that the round trip above cannot catch: it runs only against
    a lake that does not exist yet, so a *live* lake whose option went missing —
    an initialise() interrupted between creating the catalog and setting the
    limit — would go unnoticed until rows turned up in the catalog. Then the
    repair, and a change, through the step initialise() and configure() share.
    Local DuckDB catalog, no credentials, always runs.
    """
    con = duckdb.connect()
    con.load_extension("ducklake")
    con.sql(f"ATTACH 'ducklake:{tmp_path}/cat.duckdb' AS {LAKE} "
            f"(DATA_PATH '{tmp_path}/data/')")
    project = tmp_path / "project.yaml"

    with pytest.raises(RuntimeError, match="data_inlining_row_limit"):
        _assert_initialised(con)  # a bare attach persists no option at all

    project.write_text("lakehouse:\n  inlining_row_limit: 5\n")
    assert _apply_inlining_options(con, project) == (None, 5)
    _assert_initialised(con)  # any chosen limit passes, not only 0

    project.write_text("lakehouse:\n  inlining_row_limit: 0\n")
    assert _apply_inlining_options(con, project) == ("5", 0)
    con.close()


@pytest.mark.parametrize("text, limit", [
    ("lakehouse:\n  inlining_row_limit: 1_000\n", 1000),  # safe loader: a plain int
    ("lakehouse:\n  name: x\n", 0),                         # key absent
    ("", 0),                                                # empty file
])
def test_project_limit_reads(tmp_path, text, limit):
    (tmp_path / "project.yaml").write_text(text)
    assert _project_limit(tmp_path / "project.yaml") == limit


@pytest.mark.parametrize("value", ["-1", "true", "yes", '"10"', "1.5"])
def test_project_limit_refuses(tmp_path, value):
    (tmp_path / "project.yaml").write_text(f"lakehouse:\n  inlining_row_limit: {value}\n")
    with pytest.raises(RuntimeError, match="whole number"):
        _project_limit(tmp_path / "project.yaml")


def test_project_limit_needs_the_file(tmp_path):
    with pytest.raises(RuntimeError, match="repo root"):
        _project_limit(tmp_path / "project.yaml")
