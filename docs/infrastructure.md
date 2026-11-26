# Infrastructure

Everything the platform runs on is in `infra/`, one OpenTofu root module for
`prod`. A clone plus the bootstrap below, then `tofu apply`, gives the same
platform. What it creates:

| Provider | Resources | File |
|---|---|---|
| Tigris | data bucket `<lakehouse>`, runner and reader keys, each with a policy on that bucket only | `storage.tf` |
| Neon | project, default branch `prod`, role `<lakehouse>_runner` owning `ducklake_catalog`; reader role and grants in SQL | `catalog.tf` |
| Infisical | projects `<lakehouse>` and `<lakehouse>-reader`, env `prod`, the contract secrets (@docs/secrets.md), one identity per project | `secrets.tf` |
| Prefect | work pool `managed`, the three `infisical-*` Secret blocks | `orchestration.tf` |

Not in tofu: the catalog's own tables (`ops initialise`, which is data, not
infrastructure) and the deployment (`orchestrate/prefect.yaml`, which belongs
to the project, @docs/operations.md).

## Project configuration

Project-level choices live in `project.yaml` at the repo root, gitignored so the
lakehouse name stays out of the repository: `cp project.example.yaml project.yaml`
and fill it in. Tofu reads it with `yamldecode` (`local.project` in
`infra/main.tf`), the backend included.

| Key | Names |
|---|---|
| `lakehouse.name` | `<lakehouse>` below: the data bucket, the state bucket `<lakehouse>-tfstate`, the Neon project, the Infisical projects and identities, the roles (Postgres ones with `-` turned into `_`). Permanent once data exists |
| `neon.region` | where the Neon project lives. Permanent |

Keep a copy with the passphrase: a clone without it can't find its state bucket.

## Bootstrap (once, by hand)

The admin credentials tofu itself runs with. They go in a gitignored
`.env.tofu` (`cp .env.tofu.example .env.tofu`), except Prefect's, which stay in
`.env.prefect`.

1. **Tigris:** *Access Keys* → new key, role **Admin**. In its details, turn
   **Default allowed operations** off, so the keys it creates can do only what
   their policy allows. Then create bucket `<lakehouse>-tfstate` (Global,
   Standard): a backend can't create its own bucket.
2. **Neon:** *Organization settings* → *API keys* → new key, plus the org ID
   (`org-…`, *Organization settings* → *General*) for `TF_VAR_neon_org_id`.
3. **Infisical:** *Organization* → *Access Control* → *Identities* → create
   `tofu-admin`, org role **Admin**, add **Universal Auth**, and create a client
   secret. The org ID is in *Organization Settings*.
4. **Prefect:** `.env.prefect` (@docs/operations.md): `PREFECT_API_KEY` and
   `PREFECT_API_URL`. The provider reads the account and workspace from the URL.
5. **State passphrase:** `openssl rand -hex 32` into `TF_VAR_state_passphrase`,
   **and into a password manager**. The state is encrypted with it before it
   leaves the machine, and without it the state can't be read.

## Running tofu

From the repo root, in the dev container:

```bash
podman run --rm -it --env-file .env.tofu --env-file .env.prefect \
  -v $(pwd):/workspace -w /workspace/infra localhost/broke-lakehouse \
  tofu <init | plan | apply>
```

### First apply

1. `tofu init`: reaches the state bucket.
2. `tofu apply -target=terraform_data.policy_attachment`:
   the Tigris bucket, keys and policies alone, because that's the least proven
   part (see [Workaround](#workaround-tigris-policy-attachment)).
3. `tofu apply`: the rest. It also writes the two env files to the repo root
   (`infra/env.tf`, mode 0600, both gitignored): `.env.runner` is the runner's, for
   local runs and tests, and `.env.reader` is what a researcher receives
   (@docs/access.md). An apply puts them back if they're missing or edited,
   or if a credential changed, and a destroy deletes them.
4. A new lakehouse: `survey`, `tests/test_ducklake.py`, `initialise`
   (@docs/data-storage.md). Then `prefect deploy` (@docs/operations.md).
5. `tofu plan` must now show no changes. Once `initialise` has created the
   catalog tables, the reader's table grant must match what the default
   privileges gave them.

### Env files are local only

Only an apply on a person's machine writes `.env.runner` and `.env.reader`.
Anything else, CI included, runs:

```bash
tofu apply -exclude=local_sensitive_file.env
```

That leaves the two files and their state alone. A CI rotation therefore
leaves the local files stale until the next local apply, which rewrites them.

## Changing things

- **Rotate a credential:** `tofu apply -replace=<address>`. Whatever depends
  on it (Infisical secrets, policy attachments, Prefect blocks) follows in the
  same apply.
  - Infisical client secret: `infisical_identity_universal_auth_client_secret.this["runner"]`
    (or `["reader"]`). The same apply rewrites the env file.
  - Tigris key: `aws_iam_access_key.runner`
  - Reader's Neon password: `random_password.reader`
- **Runner's Neon password:** reset it in Neon, then bump `value_wo_version`
  in `infisical_secret.runner_catalog_uri`. The URI is write-only and isn't in
  the state, so tofu can't see that it changed.
- **Destroy:** `ops purge prod` first, because a bucket with objects in it won't
  delete. The state bucket stays.

## Secrets in the state

The state holds every credential tofu creates (keys, the reader's password, the
identities' client secrets), so it is encrypted (`encryption` block in
`infra/main.tf`, enforced for state and plans). The runner's Neon password
never gets there: it's read through ephemeral resources and handed to Infisical
as a write-only value.

## Workaround: Tigris policy attachment

**Temporary: replace it as soon as Tigris offers a native way.** The keys
(`aws_iam_access_key`) and their policies (`aws_iam_policy`) are AWS-provider
resources against Tigris's IAM. Attaching a policy to a key isn't, because no
provider can do it today:

| Tried | Result |
|---|---|
| `aws_iam_user_policy_attachment` | Tigris's policy ARN carries the org ID (`arn:aws:iam::to_…:policy/…`), and the AWS provider rejects anything but a 12-digit account before sending the request |
| `aws_iam_user_policy` (inline) | Tigris answers `PutUserPolicy` with `501 NotImplemented` |
| `tigrisdata/tigris` 1.1.4 | no resource for keys, policies or bucket roles |

So `terraform_data.policy_attachment` runs `AttachUserPolicy` (and
`DetachUserPolicy` on destroy) with boto3, through a `local-exec` provisioner,
using the admin key from `.env.tofu`. What that costs:

- `plan` can't see an attachment removed by hand. Re-attach with
  `tofu apply -replace='terraform_data.policy_attachment["runner"]'`.
- tofu must run where Python and boto3 are: the dev container, and later CI.

**Removing it:** once `tigrisdata/tigris` manages key policies or bucket roles,
or the AWS provider accepts non-AWS account IDs, replace the resource with the
native one, and drop the AWS provider if nothing else uses it. Check the Tigris
provider's changelog when bumping its pin.

## Unverified

Written against the providers' schemas, not yet applied:

- **Postgres provider configured from a resource created in the same apply.**
  If the first `apply` complains about its provider configuration, run
  `tofu apply -target=neon_project.catalog` first.
