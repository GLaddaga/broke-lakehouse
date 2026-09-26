# dlt

How dlt is structured and what it does to data on the way in. The worked
example is `ingest/pipelines/tpch.py`; its own specifics live in its comments.

## Resources, sources, pipelines

Three objects, each wrapping the one before it: a **resource** is a table, a
**source** is a group of resources, a **pipeline** moves a source into a
destination. Built up in that order below, on one example.

### 1. A resource is one table

A generator function, decorated. Whatever it yields — dicts, lists of dicts,
Arrow tables or record batches — becomes the rows of one table, named after the
function:

```python
@dlt.resource
def orders():
    yield from fetch("orders")          # -> table `orders`
```

Nothing runs when `orders()` is called. It returns a resource object holding an
unstarted generator; the pipeline pulls on it later.

### 2. Hints describe the table the resource will become

Everything dlt cannot work out from the data itself is a hint, and hints are the
decorator's arguments:

```python
@dlt.resource(
    name="orders",                                  # table name
    write_disposition="merge",                      # append | replace | merge
    primary_key=["id", "updated_at"],               # what merge matches on
    columns={"amount": {"data_type": "double"}},    # pin a type dlt would infer
    max_table_nesting=0,                            # keep nested data as JSON
)
def orders():
    yield from fetch("orders")
```

| Hint | What it controls |
|---|---|
| `name` / `table_name` | the destination table. `table_name` may be a callable, evaluated per row, to route rows into different tables |
| `write_disposition` | `append`, `replace` or `merge` |
| `primary_key` | what `merge` matches on; a list makes it composite |
| `merge_key` | matching for merge without implying uniqueness |
| `columns` | per-column overrides: `data_type`, `nullable`, `precision`, `scale`, flags like `unique` |
| `max_table_nesting` | how many levels of nested data become child tables; `0` keeps them whole |
| `schema_contract` | what happens when the source's shape changes — `evolve`, `freeze`, `discard_row`, `discard_value` |
| `file_format` | override the format dlt stages in |

Hints are merged with the inferred schema, not a replacement for it: dlt still
discovers the columns, and a hint overrides only what it would have guessed for
that one. A hint added later applies to new data, never to rows already loaded.

### 3. A source groups resources

One call should load a whole API or a whole schema, so resources that belong
together are returned by a source function:

```python
@dlt.source(name="shop")
def shop(api_key: str = dlt.secrets.value):
    return [orders(api_key), customers(api_key)]    # or `yield` them one by one
```

Three things come with the wrapper:

**Configuration.** The source's arguments are how it is parameterised, and a
default of `dlt.secrets.value` or `dlt.config.value` tells dlt to fill that
argument from the config providers rather than requiring it at the call site.

**A place for setup.** The body runs *before* extraction — so opening a
connection, discovering which tables exist, or generating the data all belong
here, once, rather than in each resource.

**Resources built at run time.** They need not be one decorated function per
table. `dlt.resource()` called directly takes any iterable as its first
argument, so a source can build them in a loop:

```python
@dlt.source(name="shop")
def shop(tables: list[str]):
    def rows(table: str):
        yield from fetch(table)

    return [dlt.resource(rows(t), name=t, write_disposition="append")
            for t in tables]
```

`rows(t)` builds a generator object and reads nothing until extraction pulls on
it. That is the shape `ingest/pipelines/tpch.py` uses.

Hints reach these too, after the fact:

```python
source = shop(tables=["orders"])
source.orders.apply_hints(write_disposition="merge", primary_key="id")
```

`max_table_nesting` and `schema_contract` can also be set on `@dlt.source`,
where they become the default for every resource in the group and a resource's
own hint wins.

Two more compositions worth knowing: `source.with_resources("orders")` loads
part of a source, and a **transformer** — `@dlt.transformer(data_from=orders)` —
is a resource fed by another resource's items, for when one table's rows
determine what to fetch next.

### 4. A pipeline runs a source into a destination

```python
pipeline = dlt.pipeline(
    pipeline_name="shop",       # identifies the state (below)
    destination=destination("prod"),
    dataset_name="raw",         # the schema written to
)
pipeline.run(shop())
```

`pipeline.run()` accepts a source, a single resource, or even a plain list of
dicts — the objects above are what turn that into a named, hinted, repeatable
table rather than a one-off dump.

## What a run actually does

`pipeline.run()` is three stages, and they are separable — `extract()`,
`normalize()` and `load()` can be called on their own.

**Extract.** Consumes the generators and writes what comes out to local files,
untouched. Nothing has been inspected yet. A failure here has written nothing to
the destination.

**Normalize.** The stage that does the work. It infers a schema from the data,
applies dlt's naming rules, unnests, and writes the result as the destination's
preferred file format — Parquet here. Specifically it:

- **Names columns** in `snake_case`, replacing anything that is not alphanumeric
  with `_`. Source fields called `orderKey` and `order-key` both land as
  `order_key`, and collide if both exist.
- **Infers types** from the first rows it sees. When later rows disagree it does
  not fail: it adds a *variant* column, `x__v_double` next to `x`, and leaves
  both populated. Pinning the type with `columns={"x": {"data_type": "double"}}`
  on the resource is how to prevent that.
- **Unnests** nested data. A list becomes a child table named
  `<parent>__<child>`, carrying `_dlt_parent_id`, `_dlt_root_id` and
  `_dlt_list_idx` to rebuild the order. A dict becomes flattened columns,
  `parent__field`. `max_table_nesting=0` on a resource turns this off and keeps
  the structure as a JSON column instead.
- **Adds bookkeeping columns** — `_dlt_load_id`, naming the load a row arrived
  in, and `_dlt_id`, a per-row id. On the Arrow path below, neither is added by
  default.

**Load.** Sends the normalized files to the destination in a *load package* —
an atomic unit with its own id. `LOADED and contains no failed jobs` means the
whole package landed. Individual jobs are retried on transient database errors,
so one exception in the log is not necessarily a failed run.

## The Arrow fast path

If a resource yields `pyarrow` tables or record batches instead of dicts, the
normalize stage is largely bypassed: the data is already columnar and already
typed, so dlt writes Parquet from it directly rather than inspecting row by row.

This changes one visible behaviour. On the Arrow path dlt does **not** add
`_dlt_load_id` or `_dlt_id` by default — adding them means rewriting every row,
which is exactly the cost the fast path exists to avoid. They are settings
(`normalize.parquet_normalizer.add_dlt_load_id` / `add_dlt_id`), off by default.
So an Arrow-loaded table has the source's columns and nothing else, and cannot
be traced back to a load id unless the setting is turned on.

Use Arrow whenever the source can produce it — a database cursor, a Parquet
file, DuckDB — and dicts when the source is JSON anyway.

## Write dispositions

| Disposition | What it does | What it costs |
|---|---|---|
| `append` | adds rows | nothing beyond the write |
| `replace` | drops and rewrites the table | rewrites everything each run |
| `merge` | upserts on `primary_key` | a staging dataset, plus delete-and-insert in the destination |

`merge` cannot upsert in place: dlt loads the incoming package into a second
schema, `<dataset_name>_staging`, and merges from there. That schema appears in
the catalog and in object storage whether or not anyone wanted it, and
`truncate_staging_dataset` (off by default) is what empties it afterwards.

@docs/conventions.md fixes which disposition this project uses where.

## Schema and state

dlt keeps two kinds of memory.

**The schema** — inferred column names and types per table, stored in the
destination in `_dlt_version`, and evolving as the source does. New columns are
added automatically; a type that contradicts an existing column becomes a
variant column rather than an error.

**The pipeline state** — a local directory, `~/.dlt/pipelines/<pipeline_name>`,
holding the last known schema and the incremental cursors. It also lives in the
destination as `_dlt_pipeline_state`, so a pipeline can be resumed on another
machine.

The trap: the local state outlives the data. Empty the destination by hand and
the state still describes the tables that used to be there, so the next run
tries to evolve a schema for tables that no longer exist. Deleting
`~/.dlt/pipelines/<name>` is the fix, and is needed after any out-of-band reset
or rename.

## Incremental loading

`dlt.sources.incremental` gives a resource a cursor — a column whose maximum
value is remembered in the state between runs, so the next run asks the source
only for what is newer. This is what makes `append` idempotent: the source
returns nothing to append rather than the destination deduplicating.

Prefer it over `merge` whenever the source can be asked for changes, because it
is the difference between adding files and rewriting them.

## Destinations

A destination is a factory, `dlt.destinations.<name>(credentials=…)`. This
project's is built by `destination()` in `utils/lakehouse.py`, which hands dlt
the same DuckLake catalog and object storage that `attach()` uses. dlt issues
its own `ATTACH`, so anything that must be true of a connection has to be
arranged there as well as in `attach()`.

## Running a pipeline here

Pipelines are modules, run with the environment as the first argument:

```bash
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace \
  localhost/the-broke-lakehouse python -m ingest.pipelines.tpch prod --sf 1
```

`pipeline.run()` returns a `LoadInfo`; printing it gives the package id, the
destination and the elapsed time per stage.
