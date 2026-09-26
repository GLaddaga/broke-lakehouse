{#-
    Compaction and file cleanup for the lakehouse, from the MotherDuck recipe
    (https://motherduck.com/docs/cookbook/dbt-local-ducklake/), adapted:

      - `lake` is fixed, not discovered: attach(), dlt and the profile all name it.
      - Snapshots are kept for `retention`, not 1 minute, so time travel works
        inside that window and a table rebuilt by mistake can be recovered.
        Required, never defaulted: how much history a run destroys belongs in
        the command, visibly — the schedule passes it like anyone else.
      - Orphaned files are deleted as well: a failed load leaves Parquet in the
        bucket that no snapshot ever referenced, which expiry cannot reach.
        Same `retention` window, so a load still writing is never taken for one.

    The order matters. Merging writes new files and retires the small ones;
    expiry drops the snapshots that still reference retired files; only then
    does cleanup find them unreferenced and delete them.

        dbt run-operation maintain_ducklake --target prod --args '{retention: 7 days}'

    Any DuckDB interval works: `1 minute`, `12 hours`, `30 days`.
    Not run by `dbt run`. @docs/transformation.md
-#}
{% macro maintain_ducklake(retention=none) %}
    {%- if retention is none -%}
        {% do exceptions.raise_compiler_error(
            "maintain_ducklake needs a retention window, e.g. --args '{retention: 7 days}'") %}
    {%- endif -%}
    {%- set steps = [
        ("merged",  "CALL ducklake_merge_adjacent_files('lake')"),
        ("expired", "CALL ducklake_expire_snapshots('lake', older_than => now() - INTERVAL '" ~ retention ~ "')"),
        ("deleted", "CALL ducklake_cleanup_old_files('lake', cleanup_all => true)"),
        ("deleted orphaned", "CALL ducklake_delete_orphaned_files('lake', older_than => now() - INTERVAL '" ~ retention ~ "')"),
    ] -%}
    {%- for label, sql in steps -%}
        {%- set result = run_query(sql) -%}
        {% do log(label ~ ": " ~ result | length ~ " row(s)", info=true) %}
    {%- endfor -%}
{% endmacro %}
