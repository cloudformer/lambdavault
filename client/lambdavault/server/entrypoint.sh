#!/bin/sh
# Starts Vault in the Lambda sandbox. LAMBDAVAULT_SEAL (set by Terraform) picks the seal:
#
#   kms  Vault's awskms seal: Vault unseals itself (seal-awskms.hcl, key VAULT_AWSKMS_SEAL_KEY_ID).
#   ssm  Shamir seal, one key share. The key is an SSM SecureString (LAMBDAVAULT_UNSEAL_KEY_PARAMETER), written by
#        the proxy when `vault operator init` ran through it. Here, on every cold start, it is read and Vault
#        unsealed before Lambda Web Adapter's readiness check passes.
#
# Fail closed: a key that cannot be read or does not unseal leaves Vault sealed; the readiness check
# (sealedcode=503) then never passes and every request gets an error. The key is never printed.
CONFIG=/etc/lambdavault
VAULT=http://127.0.0.1:8200

case "$LAMBDAVAULT_SEAL" in
  kms) exec vault server -config="$CONFIG/vault.hcl" -config="$CONFIG/seal-awskms.hcl" ;;
  ssm) ;;
  *) echo "lambdavault: LAMBDAVAULT_SEAL must be kms or ssm, not '$LAMBDAVAULT_SEAL'" >&2; exit 1 ;;
esac

vault server -config="$CONFIG/vault.hcl" &
pid=$!
trap 'kill -TERM "$pid" 2>/dev/null' TERM INT

sealed() { echo "lambdavault: Vault stays sealed: $1" >&2; }

# wait for Vault's API (a few seconds at most); a Vault that exits ends the script with its status
status=""
for _ in $(seq 1 300); do
  status=$(curl -sf "$VAULT/v1/sys/seal-status" | tr -d ' \n') && [ -n "$status" ] && break
  status=""
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.1
done

case "$status" in
  "") sealed "no answer from Vault" ;;
  *'"initialized":false'*) ;;   # not initialized yet: `vault operator init` comes through the proxy
  *'"sealed":false'*) ;;
  *)
    # SSM GetParameter, signed with the function's role (Lambda sets the AWS_* variables)
    key=$(curl -sf --aws-sigv4 "aws:amz:$AWS_REGION:ssm" \
            --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY" \
            -H "x-amz-security-token: $AWS_SESSION_TOKEN" \
            -H "content-type: application/x-amz-json-1.1" \
            -H "x-amz-target: AmazonSSM.GetParameter" \
            --data "{\"Name\":\"$LAMBDAVAULT_UNSEAL_KEY_PARAMETER\",\"WithDecryption\":true}" \
            "https://ssm.$AWS_REGION.amazonaws.com/" | sed -n 's/.*"Value" *: *"\([^"]*\)".*/\1/p')
    if [ -z "$key" ]; then
      sealed "cannot read the unseal key from SSM parameter $LAMBDAVAULT_UNSEAL_KEY_PARAMETER"
    elif printf '{"key":"%s"}' "$key" | curl -sf -X PUT --data-binary @- "$VAULT/v1/sys/unseal" \
         | tr -d ' \n' | grep -q '"sealed":false'; then
      echo "lambdavault: unsealed with the key from SSM parameter $LAMBDAVAULT_UNSEAL_KEY_PARAMETER" >&2
    else
      sealed "the key in SSM parameter $LAMBDAVAULT_UNSEAL_KEY_PARAMETER did not unseal it"
    fi
    key=""
    ;;
esac

wait "$pid"
