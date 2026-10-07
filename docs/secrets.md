# Secrets

Every secret lives in Infisical and is fetched at run time by `utils/infisical.py`.
The single exception is the bootstrap credential below — the machine identity
that lets a process fetch everything else.

The Infisical CLI is not used: Prefect's managed work pool installs pip packages only and cannot take a Go binary,
so secrets are fetched with `infisicalsdk` and one code path serves both local and serverless.

## The bootstrap credential

A Universal Auth machine identity (client ID + secret) plus the project ID.
Three variables, and they cannot come from Infisical because they are the key
to Infisical.

| Where | How it gets there |
|---|---|
| Local | a gitignored `.env`, injected by `podman run --env-file .env` |
| Prefect Cloud | a Prefect Secret block, read by the flow before it fetches the other secrets |

Nothing else is allowed outside Infisical.

### Local setup

```bash
cp .env.example .env
# fill in the three values
```

`--env-file` wants plain `KEY=VALUE` lines. It is not a shell: no `export`, no
quotes (they end up in the value), no `$VAR` expansion.

## The contract

This is a table listing the secret names, whom they are used by and what they are.

| Variable | Used by | What it is |
|---|---|---|
| `INFISICAL_CLIENT_ID` | bootstrap | machine identity, from `.env` |
| `INFISICAL_CLIENT_SECRET` | bootstrap | machine identity, from `.env` |
| `INFISICAL_PROJECT_ID` | bootstrap | project UUID, from `.env` |
| `DUCKLAKE_CATALOG_URI` | ingest, transform | Neon Postgres connection string — the DuckLake catalog |
| `DUCKLAKE_DATA_PATH` | ingest, transform | `s3://<bucket>/<prefix>` — config, not a credential |
| `AWS_ACCESS_KEY_ID` | ingest, transform | object-storage access key |
| `AWS_SECRET_ACCESS_KEY` | ingest, transform | object-storage secret key |
| `AWS_ENDPOINT_URL_S3` | ingest, transform | object-storage endpoint — config, not a credential. The only variable that names the provider; unset for real AWS S3 |
| `AWS_REGION` | ingest, transform | `auto` for Tigris and R2, a real region for AWS S3 — config, not a credential |
| `TEST_SECRET` | tests | mock value `it-works` — proves the fetch path, nothing else reads it |

The object-storage keys use the AWS-standard names because DuckDB's `httpfs` and
dlt's s3 extra both read them natively. One set of names, no mapping layer — and
no provider named anywhere in code, so moving from Tigris to R2 or plain S3 is a
change of values in Infisical rather than a change of code.

dlt and dbt also accept their own `DESTINATION__…` / profile-level env vars.
Neither uses them: dlt gets its credentials from `destination()`, and dbt from
`credentials()` through `utils/dbt_plugin.py`, so `profiles.yml` holds no secrets.

## Setting this up in the Infisical UI

Recorded because it is a once-a-project task that will have been forgotten by
the time it is needed again.

**1. Project.** Create one named `<your project name>`. It ships with `Development`,
`Staging` and `Production` environments; only `Production` is used.

Infisical separates an environment's *name* from its *slug*: the UI shows
`Production`, the slug is `prod`. The SDK takes the slug, so calls read
`get_secret(..., environment="prod")`. Passing the name instead is accepted and
returns nothing — the same silent empty read as a missing project grant.

**2. Project ID.** Project → Settings → General. This is `INFISICAL_PROJECT_ID`
in `.env`. It is an identifier, not a credential, but it lives in `.env` because
the other two do.

**3. Secrets.** *Add Secret* for the names in the contract table above, at the
root of `Production`. For testing purposes, create them with empty values if the
upstream service does not exist yet.

**4. Test secret.** *Add Secret* `TEST_SECRET` with the value `it-works`. Nothing
but `tests/test_infisical.py` reads it — it exists so the integration check has a
known value to compare against, independent of services that do not exist yet.

**5. Machine identity.** Organization → Access Control → Identities → *Create
identity*. Name it `<your project name>-prd-runner` and give it the org role **No
Access** — org role governs organisation administration, and project access is
granted separately in step 7.

**6. Auth method.** On the identity, add **Universal Auth**, then *Create Client
Secret*. The client secret is displayed once and is unrecoverable afterwards;
put it straight into `.env`. The client ID stays visible on the identity page.
Together these are `INFISICAL_CLIENT_ID` and `INFISICAL_CLIENT_SECRET`.

**7. Grant project access.** Back in the project → Access Control → Identities
→ *Add identity* → `<your project name>-prd-runner`, role **Viewer**.

Step 7 is the one to double-check, as without it authentication still succeeds —
the identity is real, the credentials are valid — and `list_secrets` simply
returns an empty list.

## Checking it works

```bash
podman run --env-file .env --rm \
  -v $(pwd)/utils:/workspace/utils \
  -v $(pwd)/tests:/workspace/tests \
  localhost/the-broke-lakehouse python -m pytest tests/test_infisical.py --verbose
```

`import utils` resolves from any working directory: the image installs the repo
as an editable package (`-e .` in `requirements.txt`, `pyproject.toml`), pointing
at `/workspace/utils`, which is where the mount puts the live code.

`test_login_succeeds` covers the credentials and the host; `test_returns_known_value`
covers step 7 and the environment slug. Both skip when `.env` is absent.

## Adding a secret later

Add it in the UI, then add it to `.env.example`
if it is a bootstrap variable, or to the contract table above if it is not.
