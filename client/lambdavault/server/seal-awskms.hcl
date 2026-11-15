# seal = kms: Vault's root key is wrapped by a KMS key; Vault unseals itself on every cold start.
seal "awskms" {}  # key from VAULT_AWSKMS_SEAL_KEY_ID
