# Vault inside Lambda. One Vault process runs at a time: the function's reserved concurrency is 1, because
# the s3 storage backend has no lock (terraform/main.tf).
ui            = true
disable_mlock = true   # Lambda does not allow mlock
api_addr      = "http://127.0.0.1:8200"

listener "tcp" {
  address     = "127.0.0.1:8200"
  tls_disable = true   # TLS ends at the Lambda Function URL; the adapter reaches Vault inside the sandbox
  # the caller's address (X-Forwarded-For from the Function URL) is what audit logs and rate limits see
  x_forwarded_for_authorized_addrs = "127.0.0.1/32"
}

storage "s3" {}   # bucket from AWS_S3_BUCKET, region from AWS_REGION (Lambda sets it)

seal "awskms" {}  # key from VAULT_AWSKMS_SEAL_KEY_ID: Vault unseals itself on every cold start
