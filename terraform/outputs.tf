output "vault_addr" {
  description = "export VAULT_ADDR=<this> for the vault CLI, the Terraform vault provider and hvac"
  value       = module.lambdavault.vault_addr
}

output "ui_url" {
  description = "The Vault UI"
  value       = module.lambdavault.ui_url
}

output "bucket" {
  value = module.lambdavault.bucket
}

output "kms_key_id" {
  description = "seal = kms: the seal key; null for seal = ssm"
  value       = module.lambdavault.kms_key_id
}

output "unseal_key_parameter" {
  description = "seal = ssm: the SSM SecureString holding the unseal key; null for seal = kms"
  value       = module.lambdavault.unseal_key_parameter
}
