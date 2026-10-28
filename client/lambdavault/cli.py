"""lambdavault: the helper around a deployment. Day-to-day work (and `vault operator init`) is the vault CLI.

    lambdavault output    export VAULT_ADDR=...: eval "$(lambdavault output)"
    lambdavault status    is it up: initialized / sealed / version, and how long one call took

The address comes from the deployment's local Terraform state (`terraform -chdir=terraform output -json`, run
from the repo root), or from --addr / $VAULT_ADDR. Nothing is stored anywhere else.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import __version__


def address(args):
    if args.addr:
        return args.addr.rstrip("/")
    try:
        r = subprocess.run(["terraform", f"-chdir={args.dir}", "output", "-json"], capture_output=True, text=True)
    except FileNotFoundError:
        r = None
    if r is None or r.returncode:
        sys.exit(f"no address: run from the repo root after terraform apply, or give --addr / VAULT_ADDR "
                 f"({(r.stderr.strip()[:200] if r else 'terraform not found')})")
    out = json.loads(r.stdout or "{}")
    if "vault_addr" not in out:
        sys.exit(f"terraform output in {args.dir} has no vault_addr: deploy first (terraform -chdir={args.dir} apply)")
    return out["vault_addr"]["value"]


def call(addr, path, tries=5):
    """GET one Vault API path. A cold start can take seconds and a busy function answers 429: wait and retry."""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(addr + path, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
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


def cmd_status(args):
    addr = address(args)
    t0 = time.time()
    status, health = call(addr, "/v1/sys/health?uninitcode=200&sealedcode=200")
    ms = (time.time() - t0) * 1000
    if status != 200:
        sys.exit(f"{addr} answered {status}: {health}")
    print(f"{addr}\n"
          f"  initialized {health.get('initialized')} · sealed {health.get('sealed')} · Vault {health.get('version')}\n"
          f"  one call: {ms:.0f} ms (seconds after idle = a cold start) · UI: {addr}/ui/")
    if not health.get("initialized"):
        print(f"next: VAULT_ADDR={addr} vault operator init -recovery-shares=1 -recovery-threshold=1")


def cmd_output(args):
    print(f"export VAULT_ADDR={address(args)}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="lambdavault", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"lambdavault {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", default="terraform", help="the Terraform directory (default terraform, from the repo root)")
    common.add_argument("--addr", default=os.environ.get("VAULT_ADDR"), help="the Vault address instead of terraform output")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("output", parents=[common], help="print export VAULT_ADDR=... (eval it)").set_defaults(func=cmd_output)
    sub.add_parser("status", parents=[common], help="initialized / sealed / version / latency").set_defaults(func=cmd_status)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
