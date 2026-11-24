# Operations

How the pipeline runs in Prefect Cloud: one deployment, `pipeline-flow/prod`, on
the Prefect Managed work pool `managed`. Defined in `orchestrate/prefect.yaml`.

## How a run works

Every run starts from nothing. The pool clones `main` from GitHub, runs
`pip install -r requirements.txt`, and calls `pipeline_flow`. So:

- only pushed code runs, and a push is all a code change needs;
- the pool's own Prefect image is used, not the Containerfile (it takes no
  custom image), and the DuckDB extensions are downloaded on each run;
- the Infisical credential comes from three Secret blocks, which
  `pipeline_flow` loads itself. They're not in `job_variables.env`, because
  `prefect deploy` would write their values into the deployment.

## Setup

The pool `managed` and the three Secret blocks (`infisical-client-id`,
`infisical-client-secret`, `infisical-project-id`) are created by tofu
(@docs/infrastructure.md). By hand: an API key (avatar → **API keys**), which
both tofu and `prefect deploy` use.

## Deploying

Needed only when `orchestrate/prefect.yaml` changes. The UI can't create a
deployment.

Put the API key and the workspace URL in a gitignored `.env.prefect`, not in
`.env.runner`, so that local runs stay local:

```
PREFECT_API_KEY=
PREFECT_API_URL=https://api.prefect.cloud/api/accounts/<account_id>/workspaces/<workspace_id>
```

The two IDs are in the workspace's URL in the browser. Then, from the repo root:

```bash
podman run --rm --env-file .env.prefect -v $(pwd):/workspace -w /workspace \
  localhost/broke-lakehouse \
  prefect --no-prompt deploy --prefect-file orchestrate/prefect.yaml --all
```

## Running

Deployments → `pipeline-flow/prod` → **Quick run**, or **Custom run** to change
`sf` for one run. There is no schedule. The deployment defaults to `sf: 0.01`
(about 10 MB), and every run replaces `raw` and rebuilds `gold` at that size.

## Cost

Hobby includes 500 serverless minutes a month. A run is billed from container
start to teardown, rounded up to the minute, so the clone and the `pip install`
count. An idle or unpaused pool costs nothing.

## Rotating the Infisical credential

`tofu apply -replace='infisical_identity_universal_auth_client_secret.this["runner"]'`
updates the block and `.env.runner` in the same apply (@docs/infrastructure.md).
Nothing needs redeploying.
