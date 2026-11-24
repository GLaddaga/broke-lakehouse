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
| 6½ | Infrastructure as code | `tofu apply` from a clone plus the bootstrap builds `prod` and the reader's credentials, and a second `plan` shows no changes (@docs/infrastructure.md) | |
| 7 | Researcher access | a machine with only read-only keys and a read-only Neon role reads `gold`, and a write from it fails (`tests/test_reader.py --reader`, @docs/access.md) | |
| 8 | Maintenance | scheduled cleanup, plus a monthly cost figure | after MVP |

**Later:** Evidence, GitHub Actions (its `tofu apply` takes
`-exclude=local_sensitive_file.env`, @docs/infrastructure.md), the scaffolding tool.

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
- **Workaround to remove: Tigris policy attachment runs boto3 from tofu.** No
  provider can attach a policy to a Tigris key (the AWS provider rejects
  Tigris's `to_…` ARNs, Tigris doesn't implement inline policies, the Tigris
  provider has no key resources), so `terraform_data.policy_attachment` calls
  Tigris's IAM through a `local-exec`. Replace it when Tigris ships a native
  way (@docs/infrastructure.md).
- **The Neon provider is a beta** (`neondatabase/neon`, the successor of the
  archived `kislerdm/neon`), pinned exactly. Read the changelog before bumping.

## Known bugs

- **`attach()` creates a catalog on an empty lakehouse, without the inlining
  option.** Running a pipeline before `initialise` fails the guard but leaves the
  catalog behind, and `initialise` then refuses without `--force`. Fix: check for
  `ducklake_*` tables before attaching.
