"""TPC-H into `raw`, at whatever scale factor the run asks for.

    python -m ingest.pipelines.tpch prod --sf 1

DuckDB generates the data itself, so there is no API, no key and no rate limit:
the scale factor is the only variable, which is what makes this a performance
fixture rather than a demo. `sf=1` is roughly 1 GB across the eight tables and
scales linearly from there.
"""

import argparse
import sys
import tempfile
from pathlib import Path

import dlt
import duckdb

from utils.lakehouse import destination

TABLES = ("customer", "lineitem", "nation", "orders",
          "part", "partsupp", "region", "supplier")
BATCH = 100_000  # rows per Arrow batch handed to dlt


def generate(database: Path, sf: float) -> None:
    """
    Run `dbgen` once into a DuckDB file, so the whole scale factor does not
    have to fit in memory and every resource can read the same generated data.
    """
    con = duckdb.connect(database)
    con.install_extension("tpch")  # no-op when the image already baked it in
    con.load_extension("tpch")
    con.sql(f"CALL dbgen(sf = {sf})")
    con.close()


@dlt.source(name="tpch")
def tpch(database: Path):
    """
    One resource per TPC-H table, streamed as Arrow batches.

    Arrow rather than dicts because the point here is to measure the write path:
    row-by-row normalisation would dominate the timings and measure dlt instead
    of the lakehouse. Further information @docs/guides/dlt.md
    """
    def batches(table: str):
        # Its own read-only connection: extraction pulls on these generators
        # after the source function has returned, and each is consumed
        # separately, so they cannot share one cursor.
        con = duckdb.connect(database, read_only=True)
        yield from con.sql(f"SELECT * FROM {table}").to_arrow_reader(BATCH)
        con.close()

    return [
        dlt.resource(batches(table), name=f"{table}__tpch", write_disposition="append")
        for table in TABLES
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m ingest.pipelines.tpch")
    parser.add_argument("environment", help="the lakehouse to load, never defaulted")
    parser.add_argument("--sf", type=float, default=1.0,
                        help="TPC-H scale factor; ~1 GB per unit (default: 1)")
    args = parser.parse_args()

    pipeline = dlt.pipeline(
        pipeline_name="tpch",
        destination=destination(args.environment),
        dataset_name="raw",
    )

    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "tpch.duckdb"
        generate(database, args.sf)
        # Every file in the directory, not just the .duckdb: the WAL holds a
        # good part of a freshly generated database.
        size = sum(f.stat().st_size for f in Path(tmp).iterdir()) / 1e6
        print(f"generated sf={args.sf}: {size:.0f} MB to read from", file=sys.stderr)
        print(pipeline.run(tpch(database)))
