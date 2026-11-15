# Changelog

## 0.1.2 — 2026-11-15

The image builds again: the official Vault image runs as the `vault` user, so installing curl (for the
ssm seal) now runs as root for that one step and switches back. 0.1.1's image did not build.

## 0.1.1 — 2026-11-15

The server ships in the pip package and a free seal is the default.

- `src/server/` moved to `client/lambdavault/server/` (the Vault image's Docker build context) and `src/proxy/` to
  `client/lambdavault/proxy/`, so a deployment can come from a PyPI release; `terraform/` now calls the Registry
  module `cloudformer/infra/aws//modules/lambdavault`. The image is still built with Docker from these files.
- `seal`: `ssm` (default, free) or `kms` (≈ $1 / month, the 0.1.0 behaviour). `ssm` = Vault's Shamir seal with one
  key share, kept as the SSM SecureString `/<project_name>/unseal-key`: the proxy stores it at
  `vault operator init -key-shares=1 -key-threshold=1` (other inits are refused) and unseals the running Vault;
  `entrypoint.sh` reads it at every cold start and unseals before the first request. A key that cannot be read
  leaves Vault sealed (fail closed). A deployed vault keeps its seal: switching needs a seal migration.
- The image adds `curl` (the SSM call) and starts through `entrypoint.sh`; `seal "awskms"` moved from `vault.hcl`
  to `seal-awskms.hcl`, used only with `kms`.
- `lambdavault status` names the right init flags for the seal.

## 0.1.0 — 2026-10-28

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
- Known gap (task 5): the Function URL refuses the HTTP method `LIST` (hvac, `curl -X LIST`); the vault
  CLI, the Terraform provider and the UI send `GET ?list=true` and work.
- Compatibility suite: the same hvac calls on Vault 2.2.0 in Docker and on the deployed stack (`--aws`).
