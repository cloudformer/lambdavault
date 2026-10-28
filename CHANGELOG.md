# Changelog

## 0.1.0 — unreleased

First release: HashiCorp Vault Community 2.2.0, unchanged, on AWS Lambda.

- `src/server/`: the official `hashicorp/vault` image + AWS Lambda Web Adapter; `s3` storage, `awskms`
  auto-unseal, the Vault UI on, TLS at the Function URL.
- `terraform/`: S3 (versioned; private and encrypted by AWS default), a KMS key for the seal, ECR (images for arm64 and x86_64,
  built and pushed by `apply`), the Lambda (reserved concurrency 1, `architecture` default arm64) and its
  Function URL.
- `lambdavault status | output`: check a deployment, `eval "$(lambdavault output)"` for the vault CLI; the
  address comes from the local Terraform output. Initialize with `vault operator init`.
- `src/proxy/`: the public entrance; queues concurrent callers for the one Vault (up to 25 s) instead of
  Lambda's 429.
- Compatibility suite: the same hvac calls on Vault 2.2.0 in Docker and on the deployed stack (`--aws`).
