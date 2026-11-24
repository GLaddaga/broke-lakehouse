# Neon: the DuckLake catalog. The project's default branch, role and database
# are the ones the lakehouse uses, so the runner owns `ducklake_catalog` from
# the start (Postgres 15+ lets only the owner create tables in `public`).

resource "neon_project" "catalog" {
  name      = local.lakehouse_name
  org_id    = var.neon_org_id
  region_id = local.neon_region
  branch = {
    name = local.environment
  }
  database_name  = "ducklake_catalog"
  database_user  = "${local.pg_prefix}_runner"
  store_password = true # the ephemeral neon_role below reads it back
  # The free plan caps point-in-time restore at 6 hours. The default is 1 day.
  history_retention_seconds = 21600
}

# The runner's password and URI are read on each run and never stored: the
# URI goes to Infisical through a write-only argument, the password only into
# the postgresql provider's configuration.
ephemeral "neon_role" "runner" {
  project_id = neon_project.catalog.id
  branch_id  = neon_project.catalog.branch.id
  name       = neon_project.catalog.database_user
}

ephemeral "neon_connection_uri" "runner" {
  project_id = neon_project.catalog.id
  branch_id  = neon_project.catalog.branch.id
  database   = neon_project.catalog.database_name
  role       = neon_project.catalog.database_user
}

# The reader is made in SQL as the runner, not through the Neon API: a role
# the API makes joins `neon_superuser` and can write.
provider "postgresql" {
  host      = neon_project.catalog.primary_compute.host # unpooled: the pooler drops DuckDB's prepared statements
  port      = 5432
  database  = neon_project.catalog.database_name
  username  = neon_project.catalog.database_user
  password  = ephemeral.neon_role.runner.password
  sslmode   = "require"
  superuser = false
}

resource "random_password" "reader" {
  length  = 48
  special = false # it goes into a URI unescaped
}

resource "postgresql_role" "reader" {
  name     = "${local.pg_prefix}_reader"
  login    = true
  password = random_password.reader.result
}

resource "postgresql_grant" "reader_connect" {
  database    = neon_project.catalog.database_name
  role        = postgresql_role.reader.name
  object_type = "database"
  privileges  = ["CONNECT"]
}

resource "postgresql_grant" "reader_schema" {
  database    = neon_project.catalog.database_name
  role        = postgresql_role.reader.name
  schema      = "public"
  object_type = "schema"
  privileges  = ["USAGE"]
}

# The catalog tables exist only after `ops initialise`, so on a first apply
# these two grant nothing and the default privileges do the work. On a later
# apply they cover tables that predate the grant.
resource "postgresql_grant" "reader_tables" {
  database    = neon_project.catalog.database_name
  role        = postgresql_role.reader.name
  schema      = "public"
  object_type = "table"
  privileges  = ["SELECT"]
}

resource "postgresql_default_privileges" "reader_tables" {
  database    = neon_project.catalog.database_name
  role        = postgresql_role.reader.name
  owner       = neon_project.catalog.database_user
  schema      = "public"
  object_type = "table"
  privileges  = ["SELECT"]
}

locals {
  reader_catalog_uri = "postgresql://${postgresql_role.reader.name}:${random_password.reader.result}@${neon_project.catalog.primary_compute.host}/${neon_project.catalog.database_name}?sslmode=require"
}
