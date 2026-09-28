# dbt

How dbt is structured and what it does with the SQL it is given. The worked
example is the TPC-H project in `transform/`; how dbt reaches the lakehouse is
@docs/transformation.md, not repeated here.

## The problem

TPC-H is a wholesale supplier: customers in 25 nations and 5 regions, split into
market segments, placing orders made of line items. Sales asks one question:

> Which regions and market segments bring in the revenue, month by month?

`ingest/pipelines/tpch.py` has already landed the tables in `raw`, as generated.
Answering from there directly means every analyst repeats the same renames, the
same revenue formula and the same four-way join. dbt writes each of those once,
as a layer:

| Layer | Model | What it adds |
|---|---|---|
| `bronze` | `customer__tpch`, `lineitem__tpch`, `nation__tpch`, `orders__tpch`, `region__tpch` | readable names, one model per `raw` table, nothing else |
| `silver` | `customers__tpch` | customer with its nation and region joined on |
| `silver` | `order_lines__tpch` | line item with its order's customer and date, and `net_revenue` computed |
| `gold` | `revenue_monthly__tpch` | the answer: revenue, orders, customers per month × region × segment |

`part`, `partsupp` and `supplier` are loaded but unused: the question does not
need them, so no model exists for them.

## Models, sources, refs

### 1. A model is one `select`

A `.sql` file under `models/` is a model. dbt wraps its `select` in whatever
DDL builds it, and the file name becomes the relation name:

```sql
-- models/bronze/region__tpch.sql  ->  lake.bronze.region__tpch
select
    r_regionkey as region_key,
    r_name      as name,
    r_comment   as comment
from {{ source('raw', 'region__tpch') }}
```

No `create table`, no `insert`: those are the materialization's job (below).

### 2. `source()` points at data dbt did not build

`raw` is dlt's, so dbt is told it exists in `models/sources.yml`:

```yaml
sources:
  - name: raw
    database: lake
    schema: raw
    tables:
      - name: region__tpch
```

`{{ source('raw', 'region__tpch') }}` compiles to `"lake"."raw"."region__tpch"`.
A table missing from the file is a compile error, not a runtime one — the file is
the list of what transformation is allowed to read.

### 3. `ref()` points at another model, and builds the DAG

```sql
-- models/silver/customers__tpch.sql
select c.customer_key, c.name, c.market_segment, n.name as nation, r.name as region
from {{ ref('customer__tpch') }} c
join {{ ref('nation__tpch') }} n using (nation_key)
join {{ ref('region__tpch') }} r using (region_key)
```

`ref('customer__tpch')` compiles to `"lake"."bronze"."customer__tpch"`, and also
records that `customers__tpch` depends on it. dbt collects every `ref` and
`source` into a graph and runs models in dependency order; nobody writes the
order down. Never hardcode a relation name in a model — it would build, but
outside the graph, possibly before its input exists.

The project's graph:

```
raw.customer ─ bronze.customer ─┐
raw.nation   ─ bronze.nation   ─┼─ silver.customers ───┐
raw.region   ─ bronze.region   ─┘                      ├─ gold.revenue_monthly
raw.lineitem ─ bronze.lineitem ─┬─ silver.order_lines ─┘
raw.orders   ─ bronze.orders   ─┘
```

### 4. Config says how a model is built and where

Set per folder in `dbt_project.yml`, so a model's layer is decided by where the
file sits:

```yaml
models:
  lakehouse:          # the project name
    silver:           # the folder models/silver/
      +schema: silver
      +materialized: table
```

The same keys work in a model's own `{{ config(materialized='view') }}` block,
which wins over the folder. None does here.

| Materialization | What `dbt run` does | Here |
|---|---|---|
| `view` | `create view` — no data written, re-computed on every read | not used |
| `table` | builds a new table from the `select`, swaps it in | every layer (@docs/conventions.md) |
| `incremental` | inserts or merges only rows the model's filter selects | not yet — see below |
| `ephemeral` | nothing; inlined as a CTE into whatever refs it | not used |

## What a run actually does

`dbt run` is parse, compile, execute:

**Parse.** Reads every `.sql` and `.yml`, resolves config, builds the graph.
Nothing connects yet. Output: `target/manifest.json`.

**Compile.** Renders Jinja: `ref`, `source` and macros become plain SQL, in
`target/compiled/`. `dbt compile` stops here — the fastest way to see what a
model will really run.

**Execute.** Connects once (the plugin's attach), then walks the graph. Each
model's compiled `select` is wrapped by its materialization; for `table`, that
is `create table …__dbt_tmp as <select>`, drop the old table, rename. What was
actually sent is in `target/run/`. A failed model skips everything downstream of
it and nothing else.

## Commands

Run from `transform/`, always with a target:

```bash
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace/transform \
  localhost/the-broke-lakehouse dbt <command> --target <environment>
```

| Command | Does |
|---|---|
| `dbt run` | builds every model |
| `dbt run -s gold` | builds one folder |
| `dbt run -s +revenue_monthly__tpch` | the model and everything upstream of it |
| `dbt run -s customer__tpch+` | the model and everything downstream of it |
| `dbt compile -s order_lines__tpch` | renders to `target/compiled/`, runs nothing |
| `dbt show -s revenue_monthly__tpch` | runs the model's `select` and prints rows; builds nothing |
| `dbt ls` | lists the graph's nodes |
| `dbt run-operation <macro>` | runs a macro outside any model |

`dbt build` is `run` plus tests, seeds and snapshots in graph order.

## Jinja and macros

Every model is a Jinja template before it is SQL. A macro is a Jinja function in
`macros/`.

A macro with the name of a dbt built-in replaces it for the whole project. That
is how `generate_schema_name` works, and also how to break dbt without noticing.

## Run the example

```bash
# Build bronze → silver → gold
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace/transform \
  localhost/the-broke-lakehouse dbt run --target prod

# Ask the question from a plain DuckDB session
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace \
  localhost/the-broke-lakehouse python -c "
from utils.lakehouse import attach
attach('prod').sql('''
    select region, sum(net_revenue) as revenue
    from lake.gold.revenue_monthly__tpch
    where year(month) = 1995
    group by region order by revenue desc''').show()"
```
