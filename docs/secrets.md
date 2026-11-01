# Secrets

Every secret lives in Infisical and is fetched at run time through
`utils.secrets.get_secrets(names, *, environment)`. The only exception is the
bootstrap credential, which gives access to everything else.

Each secret manager is one module under `utils/secrets/`, and
`utils/secrets/__init__.py` re-exports the one in use. Swapping managers means
a new module, that import, and new bootstrap variables.

The SDK is used instead of the Infisical CLI because Prefect's managed pool
installs pip packages only.

## Bootstrap credential

A Universal Auth machine identity plus the project ID:
`INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET`, `INFISICAL_PROJECT_ID`.

- **Locally:** `cp .env.example .env` and fill it in. Use plain `KEY=VALUE` lines,
  because `--env-file` keeps quotes as part of the value and does no `$VAR` expansion.
- **Prefect:** a Secret block.

## Contract

| Variable | Used by | Note |
|---|---|---|
| `DUCKLAKE_CATALOG_URI` | ingest, transform | Neon connection string, unpooled |
| `DUCKLAKE_DATA_PATH` | ingest, transform | `s3://<bucket>/<prefix>/` |
| `AWS_ACCESS_KEY_ID` | ingest, transform | object-storage key |
| `AWS_SECRET_ACCESS_KEY` | ingest, transform | object-storage secret |
| `AWS_ENDPOINT_URL_S3` | ingest, transform | the only value that names the provider; unset for AWS S3 |
| `AWS_REGION` | ingest, transform | `auto` for Tigris/R2, a real region for AWS |
| `TEST_SECRET` | tests | `it-works` |

The AWS-standard names are read natively by DuckDB and dlt. Switching provider
(Tigris → R2 → S3) is a change of values, not of code.

## Setup in the Infisical UI

1. Create a project. Only the `Production` environment is used. Its **slug** is
   `prod`, and the SDK takes the slug. Passing the name `Production` silently
   returns nothing.
2. Project → Settings → General: the project ID.
3. Add the contract secrets at the root of `Production`, plus `TEST_SECRET=it-works`.
4. Organization → Access Control → Identities → create `<project>-prd-runner`
   with org role **No Access**.
5. Add **Universal Auth** to it and create a client secret (shown once).
6. In the project → Access Control → Identities, add the identity as
   **Viewer**. **Without this, login still succeeds and every read returns
   empty.**

## Check

```bash
podman run --env-file .env --rm -v $(pwd):/workspace \
  localhost/the-broke-lakehouse python -m pytest tests/test_infisical.py -v
```
