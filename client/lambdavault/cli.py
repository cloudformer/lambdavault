"""lambdavault: the helper around a deployment. Day-to-day work is the vault CLI itself.

    lambdavault init      initialize a fresh deployment once; root token + recovery key go to SSM (SecureString)
    lambdavault status    is it up: initialized / sealed / version, and how long one call took
    lambdavault output    export VAULT_ADDR=... (and VAULT_TOKEN with --token): eval "$(lambdavault output --token)"

The deployment is found by name in SSM (/<name>/vault_addr, written by Terraform), so no repo is needed on the
machine. AWS credentials: --profile / --region or the standard chain.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

from . import __version__


def ssm(args):
    import boto3
    session = boto3.Session(profile_name=args.profile or None, region_name=args.region or None)
    return session.client("ssm")


def param(args, client, key, secure=False):
    try:
        return client.get_parameter(Name=f"/{args.name}/{key}", WithDecryption=secure)["Parameter"]["Value"]
    except client.exceptions.ParameterNotFound:
        return None


def address(args, client):
    addr = param(args, client, "vault_addr")
    if not addr:
        sys.exit(f"no deployment named {args.name!r}: SSM /{args.name}/vault_addr is missing "
                 "(terraform -chdir=terraform apply first, or --name / --profile / --region)")
    return addr


def call(addr, method, path, body=None, token=None, tries=5):
    """One Vault API call. A cold start can take seconds and a busy function answers 429: wait and retry."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    for attempt in range(tries):
        req = urllib.request.Request(addr + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < tries - 1:
                time.sleep(1 + attempt)
                continue
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"errors": [raw.decode(errors="replace")[:200]]}
    raise AssertionError("unreachable")


def cmd_init(args):
    client = ssm(args)
    addr = address(args, client)
    status, state = call(addr, "GET", "/v1/sys/init")
    if status != 200:
        sys.exit(f"{addr}: GET /v1/sys/init answered {status}: {state}")
    if state.get("initialized"):
        print(f"{args.name}: already initialized ({addr})")
        return
    # auto-unseal with KMS: recovery keys instead of unseal keys; one share is enough for a single operator
    status, out = call(addr, "PUT", "/v1/sys/init", {"recovery_shares": 1, "recovery_threshold": 1})
    if status != 200:
        sys.exit(f"{addr}: init failed ({status}): {out}")
    token, recovery = out["root_token"], out["recovery_keys_b64"][0]
    if args.print:
        print(f"root token:   {token}\nrecovery key: {recovery}\nstore both now: they are shown once")
        return
    for key, value in (("root_token", token), ("recovery_key", recovery)):
        client.put_parameter(Name=f"/{args.name}/{key}", Value=value, Type="SecureString", Overwrite=False)
    print(f"{args.name}: initialized ({addr})\n"
          f"  root token and recovery key in SSM: /{args.name}/root_token, /{args.name}/recovery_key\n"
          f"next: eval \"$(lambdavault output --token)\" && vault status")


def cmd_status(args):
    client = ssm(args)
    addr = address(args, client)
    t0 = time.time()
    status, health = call(addr, "GET", "/v1/sys/health?uninitcode=200&sealedcode=200")
    ms = (time.time() - t0) * 1000
    if status != 200:
        sys.exit(f"{args.name}: {addr} answered {status}: {health}")
    print(f"{args.name}: {addr}\n"
          f"  initialized {health.get('initialized')} · sealed {health.get('sealed')} · Vault {health.get('version')}\n"
          f"  one call: {ms:.0f} ms (seconds after idle = a cold start)\n"
          f"  root token in SSM: {'yes' if param(args, client, 'root_token') else 'no'} · UI: {addr}/ui/")


def cmd_output(args):
    client = ssm(args)
    print(f"export VAULT_ADDR={address(args, client)}")
    if args.token:
        token = param(args, client, "root_token", secure=True)
        if not token:
            sys.exit(f"no /{args.name}/root_token in SSM (lambdavault init stores it)")
        print(f"export VAULT_TOKEN={token}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="lambdavault", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"lambdavault {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--name", default=os.environ.get("LAMBDAVAULT_NAME", "lambdavault"),
                        help="deployment name (Terraform var name; default lambdavault or $LAMBDAVAULT_NAME)")
    common.add_argument("--profile", default=None, help="AWS profile")
    common.add_argument("--region", default=None, help="AWS region")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("init", parents=[common], help="initialize a fresh deployment once")
    i.add_argument("--print", action="store_true", help="print the root token and recovery key instead of storing them")
    i.set_defaults(func=cmd_init)
    sub.add_parser("status", parents=[common], help="initialized / sealed / version / latency").set_defaults(func=cmd_status)
    o = sub.add_parser("output", parents=[common], help="print export VAULT_ADDR=... (eval it)")
    o.add_argument("--token", action="store_true", help="also export VAULT_TOKEN (the root token from SSM)")
    o.set_defaults(func=cmd_output)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
