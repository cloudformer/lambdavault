# The server: the official Vault binary, unchanged, run by AWS Lambda Web Adapter. The adapter turns each
# Lambda invocation into an HTTP request to Vault on 127.0.0.1:8200 and Vault's reply into the response.
FROM public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 AS adapter

FROM hashicorp/vault:2.2.0
# curl: entrypoint.sh reads the unseal key from SSM (SigV4) and talks to Vault (seal = ssm)
RUN apk add --no-cache curl
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter
COPY vault.hcl seal-awskms.hcl entrypoint.sh /etc/lambdavault/

# ready = initialized and unsealed (kms: by Vault itself; ssm: by entrypoint.sh), or not initialized yet so
# `vault operator init` can run. A Vault that stays sealed never becomes ready: callers get an error.
ENV AWS_LWA_PORT=8200 \
    AWS_LWA_READINESS_CHECK_PATH="/v1/sys/health?uninitcode=204&sealedcode=503" \
    VAULT_LOG_LEVEL=info

ENTRYPOINT ["/bin/sh", "/etc/lambdavault/entrypoint.sh"]
