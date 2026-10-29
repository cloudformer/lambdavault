# lambdavault

**HashiCorp Vault, truly serverless: the official Vault binary on AWS Lambda, data in S3, auto-unseal by KMS,
≈ $1 a month when idle.** Part of [Redefine AWS Serverless](https://github.com/topics/redefine-aws-serverless).

![lambdavault architecture](https://raw.githubusercontent.com/cloudformer/lambdavault/main/docs/architecture.svg)

The vault CLI, the Terraform vault provider, the UI and hvac are the clients — unchanged, only `VAULT_ADDR`
points at the Lambda (hvac: except `list`, which sends the HTTP method LIST that Lambda Function URLs refuse;
[task 5](https://github.com/cloudformer/lambdavault/blob/main/tests/compat/TASKS.md)). This package is the helper around a deployment:

```bash
pip install lambdavault
lambdavault status    # initialized / sealed / version / latency (address from terraform output)
eval "$(lambdavault output)"   # export VAULT_ADDR for the vault CLI
vault operator init -recovery-shares=1 -recovery-threshold=1   # once
vault kv get kvv2/app
```

Deploy the server from the [main repository](https://github.com/cloudformer/lambdavault) with Terraform.
Compatibility with a normal Vault: [REPORT.md](https://github.com/cloudformer/lambdavault/blob/main/tests/compat/REPORT.md).
