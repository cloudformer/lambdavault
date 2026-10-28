"""The public entrance: queues requests for the Vault function, whose reserved concurrency is 1.

A Function URL request is passed unchanged to the Vault function (Lambda Web Adapter takes the same event) and
its reply returned unchanged. When the Vault function is busy, Lambda refuses the invoke (TooManyRequests);
this waits and tries again instead of handing the caller a 429, so concurrent callers queue up.
"""
import json
import os
import random
import time

import boto3
from botocore.config import Config

VAULT_FUNCTION = os.environ["VAULT_FUNCTION"]
QUEUE_SECONDS = float(os.environ.get("QUEUE_SECONDS", "25"))   # longest wait for a turn, below the timeout
lam = boto3.client("lambda", config=Config(retries={"max_attempts": 1}, read_timeout=35))


def lambda_handler(event, context):
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


def reply(status, message):
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps({"errors": [message]})}
