# Per-person values and secrets, from TF_VAR_* in .env.tofu. Project-level
# choices are in project.yaml instead (`local.project` in main.tf).

variable "neon_org_id" {
  description = "Neon organization that owns the project. Null for an API key that maps to one org."
  type        = string
  default     = null
}

variable "infisical_host" {
  description = "https://app.infisical.com, or https://eu.infisical.com for an EU organization."
  type        = string
  default     = "https://app.infisical.com"
}

variable "infisical_org_id" {
  description = "Infisical organization ID: Organization Settings → General."
  type        = string
}

variable "state_passphrase" {
  description = "Encrypts the state and plans. At least 16 characters."
  type        = string
  sensitive   = true
}
