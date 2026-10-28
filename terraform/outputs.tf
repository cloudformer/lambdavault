output "vault_addr" {
  description = "export VAULT_ADDR=<this> for the vault CLI, the Terraform vault provider and hvac"
  value       = local.vault_addr
}

output "ui_url" {
  description = "The Vault UI"
  value       = "${local.vault_addr}/ui/"
}

output "bucket" {
  value = aws_s3_bucket.data.bucket
}

output "kms_key_id" {
  value = aws_kms_key.seal.key_id
}
