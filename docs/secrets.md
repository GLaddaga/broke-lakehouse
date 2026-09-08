# Secrets

Every secret lives in Infisical and is fetched at run time by `helpers/infisical_env.py`.
The single exception is the bootstrap credential below — the machine identity
that lets a process fetch everything else.

## The bootstrap credential

A Universal Auth machine identity (client ID + secret) plus the project ID.
Three variables, and they cannot come from Infisical because they are the key
to Infisical.

| Where | How it gets there |
|---|---|
| Local | a gitignored `.env`, injected by `podman run --env-file .env` |
| Prefect Cloud | a Prefect Secret block, read by the flow before it calls `load()` |

Nothing else is allowed outside Infisical.

### Local setup

```bash
cp .env.example .env
# fill in the three values
```

`--env-file` wants plain `KEY=VALUE` lines. It is not a shell: no `export`, no
quotes (they end up in the value), no `$VAR` expansion.

## The contract

`load()` copies every secret in the project into the environment, so these
names are what each component looks for, not a fetch list.

| Variable | Used by | What it is |
|---|---|---|
| `INFISICAL_CLIENT_ID` | bootstrap | machine identity, from `.env` |
| `INFISICAL_CLIENT_SECRET` | bootstrap | machine identity, from `.env` |
| `INFISICAL_PROJECT_ID` | bootstrap | project UUID, from `.env` |
| `DUCKLAKE_CATALOG_URI` | ingest, transform | Neon Postgres connection string — the DuckLake catalog |
| `DUCKLAKE_DATA_PATH` | ingest, transform | `s3://<bucket>/<prefix>` on Tigris — config, not a credential |
| `AWS_ACCESS_KEY_ID` | ingest, transform | Tigris access key |
| `AWS_SECRET_ACCESS_KEY` | ingest, transform | Tigris secret key |
| `AWS_ENDPOINT_URL_S3` | ingest, transform | Tigris endpoint — config, not a credential |

The Tigris keys use the AWS-standard names because DuckDB's `httpfs` and dlt's
s3 extra both read them natively. One set of names, no mapping layer.

dlt and dbt also accept their own `DESTINATION__…` / profile-level env vars.
Those get pinned down in milestones 3 and 4, against something that actually
runs.

## Infisical layout

One project, environment slug `Development` (override with `INFISICAL_ENV`). Folders
are for humans — `load()` reads recursively from `/` and does not care:

```
/lakehouse   DUCKLAKE_CATALOG_URI, DUCKLAKE_DATA_PATH
/tigris      AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL_S3
```

The machine identity needs read access to the project at `/` with `recursive`
— a role scoped to a single folder returns a short list and the failure looks
like a missing variable rather than a permissions error.

### Setting this up in the Infisical UI

Recorded because it is a once-a-project task that will have been forgotten by
the time it is needed again.

**1. Project.** Create one named `<your project name>`. It ships with `Development`,
`Staging` and `Production` environments; only `Development` is used. Leave the other two
alone rather than deleting them — `INFISICAL_ENV` selects between them, so they
cost nothing and removing them is irreversible.

**2. Project ID.** Project → Settings → General. This is `INFISICAL_PROJECT_ID`
in `.env`. It is an identifier, not a credential, but it lives in `.env` because
the other two do.

**3. Folders.** In the `Development` environment, create `lakehouse` and `tigris` via
*Add Folder*. Purely organisational — `load()` reads recursively from `/`.

**4. Secrets.** Inside each folder, *Add Secret* for the names in the layout
block above. Create them with empty values if the upstream service does not
exist yet: milestone 1 proves the plumbing, and empty strings travel through
`load()` exactly like real values do.

**5. Machine identity.** Organization → Access Control → Identities → *Create
identity*. Name it `<your project name>-runner` and give it the org role **No
Access** — org role governs organisation administration, and project access is
granted separately in step 6.

**6. Auth method.** On the identity, add **Universal Auth**, then *Create Client
Secret*. The client secret is displayed once and is unrecoverable afterwards;
put it straight into `.env`. The client ID stays visible on the identity page.
Together these are `INFISICAL_CLIENT_ID` and `INFISICAL_CLIENT_SECRET`.

**7. Grant project access.** Back in the project → Access Control → Identities
→ *Add identity* → `<your project name>-runner`, role **Viewer**.

Step 7 is the one to double-check, as without it authentication still succeeds —
the identity is real, the credentials are valid — and `list_secrets` simply
returns an empty list.

### Adding a secret later

Add it in the UI under the appropriate folder, then add it to `.env.example`
if it is a bootstrap variable, or to the contract table above if it is not.
No code changes: `load()` copies whatever the project contains.
