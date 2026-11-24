# The two bootstrap env files, written by every apply to the repo root (both
# gitignored), so they never go stale after a rotation. Plain KEY=VALUE lines:
# `--env-file` keeps quotes and does no expansion.
#   .env.runner  the runner's: local runs and tests
#   .env.reader  what a researcher receives (@docs/access.md)
# A destroy deletes them.
#
# Local only. Anything that isn't a person's machine (CI) runs
#   tofu apply -exclude=local_sensitive_file.env
# which leaves these resources and their state alone. A variable toggling them
# off would instead remove them from the state on every CI run and re-add them
# on every local one.

locals {
  env_files = { for role in keys(local.roles) : role => join("", [for line in concat([
    "INFISICAL_CLIENT_ID=${infisical_identity_universal_auth_client_secret.this[role].client_id}",
    "INFISICAL_CLIENT_SECRET=${infisical_identity_universal_auth_client_secret.this[role].client_secret}",
    "INFISICAL_PROJECT_ID=${infisical_project.this[role].id}",
  ], var.infisical_host == "https://app.infisical.com" ? [] : ["INFISICAL_HOST=${var.infisical_host}"]) : "${line}\n"]) }
}

resource "local_sensitive_file" "env" {
  for_each        = { runner = ".env.runner", reader = ".env.reader" }
  filename        = "${path.root}/../${each.value}"
  content         = local.env_files[each.key]
  file_permission = "0600"
}
