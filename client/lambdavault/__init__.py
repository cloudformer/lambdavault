"""lambdavault: HashiCorp Vault on AWS Lambda + S3. The vault CLI, hvac and the Terraform vault provider are the
clients; this package is the helper around a deployment (`lambdavault status | output`).

It also carries what a deployment is built from, so one can come from a PyPI release:
lambdavault/server (the Vault image's Docker build context) and lambdavault/proxy (the proxy Lambda)."""

__version__ = "0.1.3"
