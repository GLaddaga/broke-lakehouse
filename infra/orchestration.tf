# Prefect Cloud: the managed pool and the runner's Infisical credential. The
# deployment itself stays in orchestrate/prefect.yaml (`prefect deploy`),
# because it belongs to the project, not to the platform. @docs/operations.md

resource "prefect_work_pool" "managed" {
  name = "managed"
  type = "prefect:managed"
}

# The names `_bootstrap()` in orchestrate/flows/pipeline.py loads.
locals {
  bootstrap_blocks = {
    "infisical-client-id"     = infisical_identity_universal_auth_client_secret.this["runner"].client_id
    "infisical-client-secret" = infisical_identity_universal_auth_client_secret.this["runner"].client_secret
    "infisical-project-id"    = infisical_project.this["runner"].id
  }
}

resource "prefect_block" "bootstrap" {
  for_each  = toset(["infisical-client-id", "infisical-client-secret", "infisical-project-id"])
  name      = each.key
  type_slug = "secret"
  data      = jsonencode({ value = local.bootstrap_blocks[each.key] })
}
