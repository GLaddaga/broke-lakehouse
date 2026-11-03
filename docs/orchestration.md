# Orchestration

`pipeline_flow` in `orchestrate/flows/pipeline.py` runs dlt, then dbt, in one
process. The lakehouse must already be initialised (@docs/data-storage.md).

```bash
podman run --env-file .env --rm -v $(pwd):/workspace -w /workspace \
  localhost/the-broke-lakehouse python -m orchestrate.flows.pipeline <environment> --sf 1
```

Without `PREFECT_API_URL`, Prefect starts a temporary local server for the run,
so nothing has to be running beforehand and no account is needed.

A failed stage fails the flow, and dbt does not start after a failed load.

`log_prints=True` sends `print` output to the flow's logs. No timeout is set, so
a Neon cold start can't fail a run.

In Prefect Cloud the same flow is the `pipeline-flow/prod` deployment on the
managed pool. Setup, deploying and running it are in @docs/operations.md.
