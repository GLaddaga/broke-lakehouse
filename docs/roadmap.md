# Roadmap

TPC-H is the reference source. The project is built against it, and it stays in
as the sample dataset. A real deployment replaces it with its own data.

**MVP = milestones 0–7**: a scheduled cloud pipeline builds `gold`, and an
analyst reads it from their own machine.

| # | Milestone | Done when | Status |
|---|---|---|---|
| 0 | Skeleton | `podman build` works; `dlt --version` and `dbt --version` run in the container | ✅ |
| 1 | Secrets | `tests/test_infisical.py` passes against `prod` (@docs/secrets.md) | ✅ |
| 2 | Catalog + storage | a table written in one process is read from a fresh one (`tests/test_ducklake.py`, @docs/data-storage.md) | ✅ |
| 3 | First dlt pipeline | TPC-H in `raw` with `replace`; a second run leaves no duplicates (@docs/ingestion.md) | ✅ |
| 4 | dbt attached | `dbt run --target prod` builds models, readable from a plain `attach('prod')` (@docs/transformation.md) | ✅ |
| 5 | Prefect flow | one `pipeline_flow` (dlt, then dbt) completes locally (@docs/orchestration.md) | ✅ |
| 6 | Serverless | a run started from Prefect Cloud completes on the managed pool, with nothing running locally. Produces `docs/operations.md` | ✅ |
| 7 | Researcher access | a machine with only read-only keys and a read-only Neon role reads `gold`, and a write from it fails (`tests/test_reader.py --reader`, @docs/access.md) | |
| 8 | Maintenance | scheduled cleanup, plus a monthly cost figure | after MVP |

**Later:** Evidence, OpenTofu for the hand-built infrastructure, GitHub Actions,
the scaffolding tool.

## Known risks

- **Prefect free tier: 1 concurrent flow run.** Separate deployments can't
  overlap, so use one, or stagger their schedules.
  [docs](https://docs.prefect.io/3.0/deploy/infrastructure-examples/managed)
- **Neon autosuspends.** The first query after idle pays a cold start. Allow for
  it in flow timeouts.
- **Only Tigris is verified.** R2 should need only different values; AWS S3 has
  a real region and no endpoint override. Neither has been run.
- **Prefect's managed pool installs from `requirements.txt` and takes no custom
  image.** Anything pinned only in the Containerfile drifts from the cloud.
- **A dlt connect failure can print the catalog password, and Prefect logs a
  failed task's traceback.** `redacted()` strips it, tested offline
  (`tests/test_redaction.py`). Not yet seen in a real Prefect Cloud log.

## Known bugs

- **`attach()` creates a catalog on an empty lakehouse, without the inlining
  option.** Running a pipeline before `initialise` fails the guard but leaves the
  catalog behind, and `initialise` then refuses without `--force`. Fix: check for
  `ducklake_*` tables before attaching.
