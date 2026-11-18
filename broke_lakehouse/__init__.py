"""The lakehouse's Python code. Imports nothing, so a reader who installs this
without the `pipeline` extra never loads dlt, dbt or Prefect.

    client       attach() and the `lake` alias: all a reader needs
    ops          the hand-run operations (`python -m broke_lakehouse.ops`), dlt's destination
    dbt_plugin   the dbt-duckdb plugin `transform/profiles.yml` loads
    secrets      the secret manager in use
"""
