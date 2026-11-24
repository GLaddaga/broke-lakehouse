# Infisical: one project per role, so the reader identity never sees the
# writer's keys. Both hold the same secret names under the same `prod` slug,
# so the code doesn't know which one it's reading. @docs/secrets.md

locals {
  # Role → Infisical project name. Plain strings only: for_each iterates over it.
  roles = {
    runner = local.lakehouse_name
    reader = "${local.lakehouse_name}-reader"
  }
  storage_keys = { runner = aws_iam_access_key.runner, reader = aws_iam_access_key.reader }

  contract_names = ["DUCKLAKE_DATA_PATH", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
  "AWS_ENDPOINT_URL_S3", "AWS_REGION", "TEST_SECRET"]

  # The contract, minus DUCKLAKE_CATALOG_URI (below): "<role>/<NAME>" → value.
  contract = merge([for role, key in local.storage_keys : {
    "${role}/DUCKLAKE_DATA_PATH"    = "s3://${tigris_bucket.data.bucket}/${local.environment}/"
    "${role}/AWS_ACCESS_KEY_ID"     = key.id
    "${role}/AWS_SECRET_ACCESS_KEY" = key.secret
    "${role}/AWS_ENDPOINT_URL_S3"   = local.endpoint_s3
    "${role}/AWS_REGION"            = "auto"
    "${role}/TEST_SECRET"           = "it-works"
  }]...)
}

resource "infisical_project" "this" {
  for_each                   = local.roles
  name                       = each.value
  slug                       = each.value
  should_create_default_envs = false
}

# The SDK takes the slug. Asking for the name, `Production`, returns nothing.
resource "infisical_project_environment" "prod" {
  for_each   = local.roles
  project_id = infisical_project.this[each.key].id
  name       = "Production"
  slug       = local.environment
}

resource "infisical_secret" "contract" {
  # Keys built from plain names: for_each can't take the sensitive values.
  for_each     = toset([for pair in setproduct(keys(local.roles), local.contract_names) : join("/", pair)])
  workspace_id = infisical_project.this[split("/", each.key)[0]].id
  env_slug     = infisical_project_environment.prod[split("/", each.key)[0]].slug
  folder_path  = "/"
  name         = split("/", each.key)[1]
  value        = local.contract[each.key]
}

# Write-only: the URI comes from an ephemeral resource and never reaches the
# state. Bump the version to push a new one, e.g. after resetting the password.
resource "infisical_secret" "runner_catalog_uri" {
  workspace_id     = infisical_project.this["runner"].id
  env_slug         = infisical_project_environment.prod["runner"].slug
  folder_path      = "/"
  name             = "DUCKLAKE_CATALOG_URI"
  value_wo         = ephemeral.neon_connection_uri.runner.uri
  value_wo_version = 1
}

resource "infisical_secret" "reader_catalog_uri" {
  workspace_id = infisical_project.this["reader"].id
  env_slug     = infisical_project_environment.prod["reader"].slug
  folder_path  = "/"
  name         = "DUCKLAKE_CATALOG_URI"
  value        = local.reader_catalog_uri
}

# The bootstrap credential: a machine identity with no org access, Viewer on
# its own project only. Without the project membership, login still works and
# every read comes back empty.
resource "infisical_identity" "this" {
  for_each = local.roles
  name     = "${local.lakehouse_name}-${each.key}"
  org_id   = var.infisical_org_id
  role     = "no-access"
}

resource "infisical_identity_universal_auth" "this" {
  for_each    = local.roles
  identity_id = infisical_identity.this[each.key].id
}

resource "infisical_identity_universal_auth_client_secret" "this" {
  for_each    = local.roles
  identity_id = infisical_identity_universal_auth.this[each.key].identity_id
  description = "managed by tofu: replace this resource to rotate"
}

resource "infisical_project_identity" "this" {
  for_each    = local.roles
  project_id  = infisical_project.this[each.key].id
  identity_id = infisical_identity.this[each.key].id
  roles       = [{ role_slug = "viewer" }]
}
