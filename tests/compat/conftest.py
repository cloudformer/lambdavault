"""Compatibility harness: the same hvac calls on a real Vault (Docker, the version the image runs) and on the
deployed lambdavault (--aws <var-file>), compared step by step.

lambdavault runs the official Vault binary, so there is no in-process side: without --aws the comparisons are
skipped. A test is one feature; its docstring "Category | Feature | note" is the report row. Each step is a
callable(client) -> value; results are normalised (timestamps, request ids, accessors dropped) and errors
compare as their hvac exception class.
"""
import json
import os

import pytest

import compat_aws
import compat_report

hvac = pytest.importorskip("hvac")

MOUNT = "compat"          # a KV v2 mount of the suite's own, recreated empty once per run on both sides
VOLATILE = {"created_time", "deletion_time", "updated_time", "request_id", "lease_id", "lease_duration",
            "renewable", "accessor", "client_token", "entity_id", "creation_time", "expire_time",
            "issue_time", "last_renewal_time", "creation_ttl", "ttl", "id", "mount_accessor", "uuid",
            "wrap_info", "warnings", "warning", "token_accessor", "mount_type", "metadata"}


def normalise(value):
    if isinstance(value, dict):
        return {k: normalise(v) for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, list):
        return [normalise(v) for v in value]
    return value


def outcome(client, step):
    try:
        return ("ok", normalise(step(client)))
    except hvac.exceptions.VaultError as e:
        return ("error", type(e).__name__)


def fresh(client):
    """The suite's KV v2 mount and userpass auth, empty: the reference container starts empty, so must we."""
    if f"{MOUNT}/" in client.sys.list_mounted_secrets_engines()["data"]:
        client.sys.disable_secrets_engine(MOUNT)
    client.sys.enable_secrets_engine("kv", path=MOUNT, options={"version": "2"})
    if "userpass/" in client.sys.list_auth_methods()["data"]:
        client.sys.disable_auth_method("userpass")
    client.sys.enable_auth_method("userpass")


@pytest.fixture(scope="session")
def real():
    addr, token = os.environ.get("VAULT_ADDR"), os.environ.get("VAULT_TOKEN")
    if not addr:
        pytest.skip("the reference Vault is not running: python3 -m pytest tests -q --docker up | run | down")
    client = hvac.Client(url=addr, token=token)
    compat_report.versions["vault"] = f"Vault {client.sys.read_health_status(method='GET')['version']} (Docker)"
    fresh(client)
    return client


@pytest.fixture(scope="session")
def ours(request):
    if not request.config.getoption("--aws", None):
        pytest.skip("lambdavault runs the real Vault binary: compare the deployed stack with --aws <var-file>")
    addr = compat_aws.aws["outputs"].get("vault_addr")
    if not addr:
        pytest.exit("--aws: no vault_addr in terraform output; deploy first", returncode=4)
    compat_aws.aws["url"] = addr
    token = os.environ.get("LAMBDAVAULT_TOKEN")
    if not token:
        pytest.exit("--aws: set LAMBDAVAULT_TOKEN to the deployed Vault's token (vault operator init printed it)",
                    returncode=4)
    client = hvac.Client(url=addr, token=token, timeout=60)
    fresh(client)
    return client


@pytest.fixture
def pair(real, ours):
    """pair([step, ...]): each step(client) on both sides; the outcomes must be equal."""
    def run(steps):
        for i, step in enumerate(steps):
            r, o = outcome(real, step), outcome(ours, step)
            assert r == o, (f"step {i}\n  real: {json.dumps(r, default=str)[:400]}\n"
                            f"  ours: {json.dumps(o, default=str)[:400]}")
    return run
