# lambdavault

**HashiCorp Vault, truly serverless: the official Vault binary on AWS Lambda, data in S3, auto-unseal by KMS,
≈ $1 a month when idle.** Part of [Redefine AWS Serverless](https://github.com/topics/redefine-aws-serverless).

![lambdavault architecture](https://raw.githubusercontent.com/cloudformer/lambdavault/main/docs/architecture.svg)

The vault CLI, hvac and the Terraform vault provider are the clients — unchanged, only `VAULT_ADDR` points at
the Lambda. This package is the helper around a deployment:

```bash
pip install lambdavault
lambdavault init      # once: root token + recovery key -> SSM SecureString
lambdavault status    # initialized / sealed / version / latency
eval "$(lambdavault output --token)"   # export VAULT_ADDR / VAULT_TOKEN for the vault CLI
vault kv get kvv2/app
```

Deploy the server from the [main repository](https://github.com/cloudformer/lambdavault) with Terraform.
Compatibility with a normal Vault: [REPORT.md](https://github.com/cloudformer/lambdavault/blob/main/tests/compat/REPORT.md).
