"""The Vault function's container image: the official hashicorp/vault image, unchanged, plus AWS Lambda Web Adapter.

Dockerfile        the image; built with Docker from this directory as the context (both arm64 and x86_64)
vault.hcl         Vault's config: s3 storage, the listener the adapter talks to
seal-awskms.hcl   added for seal = kms: Vault unseals itself with KMS
entrypoint.sh     starts Vault; for seal = ssm it unseals Vault with the key kept in SSM Parameter Store

Nothing here is Python: the package only carries these files to the machine that builds the image."""
