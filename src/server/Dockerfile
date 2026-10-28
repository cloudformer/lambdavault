# The server: the official Vault binary, unchanged, run by AWS Lambda Web Adapter. The adapter turns each
# Lambda invocation into an HTTP request to Vault on 127.0.0.1:8200 and Vault's reply into the response.
FROM public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 AS adapter

FROM hashicorp/vault:1.20.3
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter
COPY vault.hcl /etc/lambdavault/vault.hcl

# ready = initialized and unsealed (auto-unseal with KMS), or not initialized yet so `lambdavault init` can run
ENV AWS_LWA_PORT=8200 \
    AWS_LWA_READINESS_CHECK_PATH="/v1/sys/health?uninitcode=204&sealedcode=503" \
    VAULT_LOG_LEVEL=info

ENTRYPOINT ["vault", "server", "-config=/etc/lambdavault/vault.hcl"]
