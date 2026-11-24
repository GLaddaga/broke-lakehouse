# The whole platform for one environment, `prod`: storage, catalog, secrets and
# the orchestrator's pool. One root module, applied from the dev container with
# the bootstrap credentials in .env.tofu and .env.prefect. @docs/infrastructure.md

terraform {
  # 1.11+: ephemeral resources and write-only arguments, which keep the Neon
  # runner's password out of the state altogether.
  required_version = ">= 1.11.0"

  required_providers {
    tigris     = { source = "tigrisdata/tigris", version = "1.1.4" }
    neon       = { source = "neondatabase/neon", version = "0.19.0-beta.3" } # beta: only an exact pin installs it
    postgresql = { source = "cyrilgdn/postgresql", version = "1.27.0" }
    infisical  = { source = "infisical/infisical", version = "0.20.16" }
    prefect    = { source = "prefecthq/prefect", version = "3.4.4" }
    aws        = { source = "hashicorp/aws", version = "6.73.0" } # only for Tigris's IAM endpoint
    random     = { source = "hashicorp/random", version = "3.9.1" }
    local      = { source = "hashicorp/local", version = "2.9.1" } # writes .env.runner and .env.reader
  }

  # The state bucket is made by hand in the bootstrap: a backend can't create
  # the bucket it lives in. Credentials are the Tigris admin key, from the
  # AWS_* variables in .env.tofu. The name comes from project.yaml: OpenTofu
  # evaluates locals in the backend block before initialising it.
  backend "s3" {
    bucket                      = "${local.lakehouse_name}-tfstate"
    key                         = "prod/terraform.tfstate"
    region                      = "auto"
    endpoints                   = { s3 = "https://t3.storage.dev" }
    skip_credentials_validation = true # no STS on Tigris
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
    use_lockfile                = true # conditional writes; drop this if Tigris refuses the lock
  }

  # The state holds every credential tofu creates, so it is encrypted before it
  # leaves the machine. Lose the passphrase and the state can't be read: keep
  # it in a password manager, not only in .env.tofu.
  encryption {
    key_provider "pbkdf2" "passphrase" {
      passphrase = var.state_passphrase
    }
    method "aes_gcm" "main" {
      keys = key_provider.pbkdf2.passphrase
    }
    state {
      method   = method.aes_gcm.main
      enforced = true
    }
    plan {
      method   = method.aes_gcm.main
      enforced = true
    }
  }
}

# Project-level choices, from the gitignored project.yaml at the repo root
# (project.example.yaml shows its shape). @docs/infrastructure.md
locals {
  project        = yamldecode(file("${path.root}/../project.yaml"))
  lakehouse_name = local.project.lakehouse.name
  neon_region    = local.project.neon.region
}

locals {
  environment = "prod"                                  # Infisical slug, Neon branch and bucket prefix: one word
  pg_prefix   = replace(local.lakehouse_name, "-", "_") # a Postgres role name can't take `-` unquoted
  endpoint_s3 = "https://t3.storage.dev"                # fly.storage.tigris.dev is an alias; don't mix them
}

# Tigris admin key from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
provider "tigris" {
  endpoint = local.endpoint_s3
}

# The AWS provider only for Tigris's IAM emulation: access keys and their policies.
provider "aws" {
  region                      = "auto"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  endpoints {
    iam = "https://iam.storage.dev"
    s3  = local.endpoint_s3
  }
}

# NEON_API_KEY from the environment.
provider "neon" {}

# Infisical admin identity from INFISICAL_UNIVERSAL_AUTH_CLIENT_ID/_SECRET.
provider "infisical" {
  host = var.infisical_host
}

# PREFECT_API_KEY and PREFECT_API_URL from .env.prefect, the same pair
# `prefect deploy` uses. The workspace URL carries the account and workspace IDs.
provider "prefect" {}
