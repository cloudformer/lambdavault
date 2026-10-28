# Changelog

## 0.1.0 — unreleased

First release: HashiCorp Vault Community 1.20.3, unchanged, on AWS Lambda.

- `src/server/`: the official `hashicorp/vault` image + AWS Lambda Web Adapter; `s3` storage, `awskms`
  auto-unseal, the Vault UI on, TLS at the Function URL.
- `terraform/`: S3 (versioned, encrypted, private), a KMS key for the seal, ECR (images for arm64 and x86_64,
  built and pushed by `apply`), the Lambda (reserved concurrency 1, `architecture` default arm64) and its
  Function URL, SSM `/<name>/vault_addr`.
- `lambdavault init | status | output`: initialize once (root token and recovery key to SSM SecureString),
  check a deployment, `eval "$(lambdavault output --token)"` for the vault CLI.
- Compatibility suite: the same hvac calls on Vault 1.20.3 in Docker and on the deployed stack (`--aws`).
