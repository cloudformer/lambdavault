"""The public entrance: queues requests for the Vault function, whose reserved concurrency is 1.

A Function URL request is passed unchanged to the Vault function (Lambda Web Adapter takes the same event) and
its reply returned unchanged. When the Vault function is busy, Lambda refuses the invoke (TooManyRequests);
this waits and tries again instead of handing the caller a 429, so concurrent callers queue up.

SEAL = ssm (Shamir seal, one key share): `vault operator init` passes through here. Only an init with one key
share and threshold one is let through; its unseal key is written to the SSM SecureString UNSEAL_KEY_PARAMETER
(the Vault function reads it on every cold start: server/entrypoint.sh) and the running Vault is unsealed with
it. The init reply goes back as Vault gave it; the key is never logged. SEAL = kms: none of this.
"""
import base64
import copy
import json
import os
import random
import time

import boto3
from botocore.config import Config

VAULT_FUNCTION = os.environ["VAULT_FUNCTION"]
SEAL = os.environ["SEAL"]                                       # kms | ssm
UNSEAL_KEY_PARAMETER = os.environ.get("UNSEAL_KEY_PARAMETER")   # seal = ssm only
QUEUE_SECONDS = float(os.environ.get("QUEUE_SECONDS", "25"))   # longest wait for a turn, below the timeout
lam = boto3.client("lambda", config=Config(retries={"max_attempts": 1}, read_timeout=35))
ssm = boto3.client("ssm") if SEAL == "ssm" else None


def lambda_handler(event, context):
    if SEAL == "ssm" and is_init(event):
        return init(event)
    return forward(event)


def forward(event):
    """Invoke the Vault function with the event, waiting for a turn: its reply, or an error reply."""
    payload, deadline, pause = json.dumps(event).encode(), time.time() + QUEUE_SECONDS, 0.05
    while True:
        try:
            r = lam.invoke(FunctionName=VAULT_FUNCTION, Payload=payload)
            break
        except lam.exceptions.TooManyRequestsException:
            if time.time() + pause > deadline:
                return reply(429, "Vault is busy: no turn within %.0f s" % QUEUE_SECONDS)
            time.sleep(pause * random.uniform(0.5, 1.0))   # jitter: waiting callers do not retry in lockstep
            pause = min(pause * 2, 1.0)
    body = r["Payload"].read()
    if r.get("FunctionError"):
        return reply(502, "the Vault function failed: " + body.decode(errors="replace")[:300])
    return json.loads(body)


# ---------------- seal = ssm: `vault operator init` stores the unseal key ----------------
def is_init(event):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    return method in ("PUT", "POST") and event.get("rawPath", "").rstrip("/") == "/v1/sys/init"


def body_json(message):
    raw = message.get("body") or ""
    if message.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    return json.loads(raw or "{}")


def init(event):
    try:
        request = body_json(event)
    except ValueError:
        return forward(event)   # Vault answers a malformed request itself
    if request.get("secret_shares") != 1 or request.get("secret_threshold") != 1 or request.get("pgp_keys"):
        return reply(400, "seal = ssm keeps the one unseal key in SSM (%s): initialize with "
                          "`vault operator init -key-shares=1 -key-threshold=1` (no -pgp-keys)" % UNSEAL_KEY_PARAMETER)
    r = forward(event)
    if r.get("statusCode") != 200:
        return r
    try:
        key = body_json(r)["keys"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return r
    try:
        ssm.put_parameter(Name=UNSEAL_KEY_PARAMETER, Value=key, Type="SecureString", Overwrite=True,
                          Description="lambdavault unseal key (Shamir, 1 of 1): read by the Vault function at a cold start")
    except Exception as e:   # the reply is the only copy of the root token and the key: hand it back whatever happens
        print("lambdavault: the unseal key was NOT stored in %s: %s" % (UNSEAL_KEY_PARAMETER, type(e).__name__))
        return warn(r, "the unseal key could not be stored in SSM parameter %s (%s): store Unseal Key 1 there "
                       "yourself (aws ssm put-parameter --type SecureString), otherwise Vault stays sealed after its "
                       "next cold start" % (UNSEAL_KEY_PARAMETER, type(e).__name__))
    u = forward(unseal_event(event, key))
    if u.get("statusCode") != 200:   # the key is stored: the next cold start unseals
        return warn(r, "Vault is initialized but still sealed (unseal answered %s): it unseals at its next cold "
                       "start, or run `vault operator unseal`" % u.get("statusCode"))
    return r


def unseal_event(event, key):
    """The init request turned into PUT /v1/sys/unseal {"key": ...} for the running Vault."""
    e = copy.deepcopy(event)
    e["rawPath"], e["rawQueryString"], e["isBase64Encoded"] = "/v1/sys/unseal", "", False
    e["body"] = json.dumps({"key": key})
    e["headers"] = {k: v for k, v in (e.get("headers") or {}).items() if k.lower() != "content-length"}
    e["headers"]["content-type"] = "application/json"
    e.setdefault("requestContext", {}).setdefault("http", {}).update(method="PUT", path="/v1/sys/unseal")
    return e


def warn(r, message):
    """The init reply with a warning added; everything Vault returned stays as it was."""
    try:
        body = body_json(r)
    except ValueError:
        return r
    body["warnings"] = (body.get("warnings") or []) + [message]
    return dict(r, body=json.dumps(body), isBase64Encoded=False)


def reply(status, message):
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps({"errors": [message]})}
