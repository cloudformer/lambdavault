# lambdavault — HashiCorp Vault, truly serverless

> A self-managed **Vault** means servers that run all day (three for HA); **HCP Vault** starts around
> $450 a month. **lambdavault** runs the official Vault binary, unchanged, inside **AWS Lambda**, with its
> data in **S3** and auto-unseal by **KMS**: ≈ $1 a month when idle (the KMS key, billed by the hour). The vault CLI, hvac and the Terraform
> vault provider talk to it as to any Vault — only `VAULT_ADDR` changes.

[中文](README.zh.md) · [compatibility report](tests/compat/REPORT.md) · [tasks](tests/compat/TASKS.md) · [changelog](CHANGELOG.md)

![architecture](docs/architecture.svg)

| | Vault on EC2 (self-managed) | HCP Vault Dedicated | lambdavault |
|---|---|---|---|
| Idle cost / month | the instances (3 for HA), load balancer, disks | ≈ $450 (Development) · ≈ $1,150+ (Essentials) | ≈ $1 (the KMS key) |
| Runs | Vault Community on your instances | Vault Enterprise, by HashiCorp | Vault Community 1.20.3 in Lambda |
| Storage | Raft on the instances' disks | HashiCorp's cloud | S3 in your account (versioned), Vault-encrypted |
| Unseal | manual or KMS | managed | KMS, by Vault itself at every cold start |
| Endpoint | your load balancer | HCP | Lambda Function URL (HTTPS) |
| Clients | vault CLI, hvac, Terraform provider | the same | the same, unchanged |
| Console | Vault UI | Vault UI | Vault UI (`<vault_addr>/ui/`) |
| Compatibility | — | — | [see the report](tests/compat/REPORT.md) |

## Why

Most teams use Vault to keep static secrets and hand them to Terraform and applications a few times a day. That
needs a Vault that is always reachable, not one that is always running. Lambda runs Vault only while a request
is being answered; S3 and KMS keep the state and the key.

## How it works

`src/server/Dockerfile` is the official `hashicorp/vault` image plus AWS Lambda Web Adapter, which turns each
invocation into an HTTP request to Vault on `127.0.0.1:8200`. Vault's config (`src/server/vault.hcl`) uses the
`s3` storage backend and the `awskms` seal, so a cold start reads its state from S3 and unseals itself with
KMS. The function's reserved concurrency is 1: the s3 backend has no lock, so exactly one Vault process ever
writes. Terraform builds the image for arm64 and x86_64, pushes both to ECR and deploys one
(`architecture`, default arm64).

## Quick start

### 1. Deploy

Needs Terraform, Docker running and the AWS CLI (for the ECR login).

```bash
cp terraform/example.json terraform/my.json      # set aws_profile, region, name
terraform -chdir=terraform init
terraform -chdir=terraform apply -var-file=my.json
terraform -chdir=terraform output                 # vault_addr, ui_url
```

### 2. Initialize once

```bash
export VAULT_ADDR=$(terraform -chdir=terraform output -raw vault_addr)
vault operator init -recovery-shares=1 -recovery-threshold=1   # prints the root token and recovery key once: keep both
export VAULT_TOKEN=<root token>
vault status
```

### 3. Use it as any Vault

```bash
vault secrets enable -path=kvv2 kv-v2
vault kv put kvv2/app user=u password=p
vault kv get kvv2/app
```

```hcl
provider "vault" {
  address = "<vault_addr>"   # terraform output vault_addr
}

data "vault_kv_secret_v2" "app" {
  mount = "kvv2"
  name  = "app"
}
```

Open `<vault_addr>/ui/` in a browser for the Vault UI.

Until task 1 is done, run Terraform with `-parallelism=1` when it reads many secrets: one Vault process answers
one request at a time and a concurrent one gets 429.

## Compatibility

Both sides run the same Vault binary, so the report checks that Vault on Lambda answers exactly like a normal
Vault: the same hvac calls on Vault 1.20.3 in Docker and on the deployed stack, compared step by step.

```bash
LAMBDAVAULT_TOKEN=<token> python3 -m pytest tests -q --docker run --aws my.json   # Vault in Docker vs the deployed lambdavault
python3 -m pytest tests -q                               # regression suite only
```

## Guarantees

| | How |
|---|---|
| **Encryption** | Vault's barrier encrypts every value before it reaches S3 (S3 adds SSE-S3); Vault's root key is wrapped by KMS |
| **Durability** | S3 (versioned: an overwritten object can be recovered) |
| **One writer** | reserved concurrency 1: two Vault processes never share the storage |
| **Availability** | Lambda, S3 and KMS are regional, multi-AZ: no instance to fail or patch |

## Who this is for

Teams that use Vault for static secrets (KV), tokens, policies and auth methods such as userpass, at a few
requests per second. Not yet: many concurrent callers (task 1), Raft / replication / Enterprise features.
See MIGRATION.md for moving to a Vault cluster.

## Repository layout

```
src/server/       Dockerfile (Vault + Lambda Web Adapter), vault.hcl
client/           the pip package lambdavault: status, output (optional helper)
terraform/        S3 (versioned), a KMS key (the seal), ECR, the Lambda, its Function URL
tests/            regression suite; tests/compat/ Vault vs lambdavault, REPORT.md, TASKS.md
```

## Releasing

CI runs the suite on every push. A release is a tag: bump the version in `client/pyproject.toml` and
`client/lambdavault/__init__.py`, add the CHANGELOG entry, commit, then `git tag vX.Y.Z && git push --tags`.

---

Part of **[Redefine AWS Serverless](https://github.com/topics/redefine-aws-serverless)** — AWS services that bill
while idle, rebuilt on primitives that cost ≈ $0 when idle. MIT. Vault is a trademark of HashiCorp; lambdavault
runs the unmodified Vault Community binary under its own license (BSL 1.1).
