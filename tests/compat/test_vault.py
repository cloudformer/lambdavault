"""lambdavault vs Vault: the compatibility matrix. One test = one feature; docstring "Category | Feature | note".

    python3 -m pytest tests -q --docker run --aws <var-file>   Vault in Docker vs the deployed lambdavault

The feature list only grows. Both sides run the same Vault binary; what this proves is that Vault on Lambda
(s3 storage, KMS auto-unseal, one process at a time, cold starts) answers exactly like a normal Vault.
"""
import pytest

MOUNT = "compat"  # the KV v2 mount conftest.fresh() recreates empty on both sides
kv = lambda c: c.secrets.kv.v2  # noqa: E731


def test_kv_write_read(pair):
    """KV v2 | write a secret and read the latest version"""
    pair([
        lambda c: kv(c).create_or_update_secret("app/db", {"user": "u", "password": "p"}, mount_point=MOUNT)["data"]["version"],
        lambda c: kv(c).read_secret_version("app/db", mount_point=MOUNT, raise_on_deleted_version=True)["data"]["data"],
    ])


def test_kv_versions(pair):
    """KV v2 | versions: an older version stays readable; metadata counts them"""
    pair([
        lambda c: [kv(c).create_or_update_secret("app/v", {"n": str(i)}, mount_point=MOUNT)["data"]["version"]
                   for i in range(3)],
        lambda c: kv(c).read_secret_version("app/v", version=1, mount_point=MOUNT, raise_on_deleted_version=True)["data"]["data"],
        lambda c: {k: v for k, v in kv(c).read_secret_metadata("app/v", mount_point=MOUNT)["data"].items()
                   if k in ("current_version", "oldest_version", "max_versions")},
    ])


@pytest.mark.xfail(reason="task 5: the Function URL refuses the HTTP method LIST that hvac sends; "
                          "GET ?list=true (vault CLI, Terraform, UI) works")
def test_kv_list(pair):
    """KV v2 | list keys: folders end with /"""
    pair([
        lambda c: [kv(c).create_or_update_secret(p, {"x": "1"}, mount_point=MOUNT)["data"]["version"]
                   for p in ("list/a", "list/b", "list/sub/c")],
        lambda c: sorted(kv(c).list_secrets("list", mount_point=MOUNT)["data"]["keys"]),
    ])


def test_kv_soft_delete_undelete(pair):
    """KV v2 | soft delete of the latest version, then undelete restores it"""
    pair([
        lambda c: kv(c).create_or_update_secret("app/del", {"k": "v"}, mount_point=MOUNT)["data"]["version"],
        lambda c: kv(c).delete_latest_version_of_secret("app/del", mount_point=MOUNT).status_code,
        lambda c: kv(c).read_secret_version("app/del", mount_point=MOUNT, raise_on_deleted_version=True),
        lambda c: kv(c).undelete_secret_versions("app/del", versions=[1], mount_point=MOUNT).status_code,
        lambda c: kv(c).read_secret_version("app/del", mount_point=MOUNT, raise_on_deleted_version=True)["data"]["data"],
    ])


def test_kv_destroy(pair):
    """KV v2 | destroy a version for good"""
    pair([
        lambda c: [kv(c).create_or_update_secret("app/gone", {"n": str(i)}, mount_point=MOUNT)["data"]["version"]
                   for i in range(2)],
        lambda c: kv(c).destroy_secret_versions("app/gone", versions=[1], mount_point=MOUNT).status_code,
        lambda c: kv(c).read_secret_version("app/gone", version=1, mount_point=MOUNT, raise_on_deleted_version=True),
    ])


def test_kv_delete_metadata(pair):
    """KV v2 | delete metadata removes every version"""
    pair([
        lambda c: kv(c).create_or_update_secret("app/meta", {"k": "v"}, mount_point=MOUNT)["data"]["version"],
        lambda c: kv(c).delete_metadata_and_all_versions("app/meta", mount_point=MOUNT).status_code,
        lambda c: kv(c).read_secret_version("app/meta", mount_point=MOUNT, raise_on_deleted_version=True),
    ])


def test_kv_check_and_set(pair):
    """KV v2 | check-and-set: a stale cas is refused"""
    pair([
        lambda c: kv(c).create_or_update_secret("app/cas", {"n": "1"}, mount_point=MOUNT)["data"]["version"],
        lambda c: kv(c).create_or_update_secret("app/cas", {"n": "2"}, cas=1, mount_point=MOUNT)["data"]["version"],
        lambda c: kv(c).create_or_update_secret("app/cas", {"n": "3"}, cas=1, mount_point=MOUNT),
    ])


def test_kv_patch(pair):
    """KV v2 | patch merges into the latest version"""
    pair([
        lambda c: kv(c).create_or_update_secret("app/patch", {"a": "1", "b": "2"}, mount_point=MOUNT)["data"]["version"],
        lambda c: kv(c).patch("app/patch", {"b": "3"}, mount_point=MOUNT)["data"]["version"],
        lambda c: kv(c).read_secret_version("app/patch", mount_point=MOUNT, raise_on_deleted_version=True)["data"]["data"],
    ])


def test_missing_path(pair):
    """Errors | reading a path that was never written"""
    pair([lambda c: kv(c).read_secret_version("nope/never", mount_point=MOUNT, raise_on_deleted_version=True)])


def test_policy_enforced(pair):
    """Policies | an ACL policy is stored and enforced: read-only token cannot write"""
    rules = f'path "{MOUNT}/data/ro/*" {{ capabilities = ["read"] }}'

    def as_reader(c, fn):
        t = c.auth.token.create(policies=["compat-ro"], ttl="5m")["auth"]["client_token"]
        r = type(c)(url=c.url, token=t, timeout=60)
        try:
            return fn(r)
        finally:
            r.auth.token.revoke_self()
    pair([
        lambda c: c.sys.create_or_update_policy("compat-ro", rules).status_code,
        lambda c: c.sys.read_policy("compat-ro")["data"]["rules"],
        lambda c: kv(c).create_or_update_secret("ro/x", {"k": "v"}, mount_point=MOUNT)["data"]["version"],
        lambda c: as_reader(c, lambda r: kv(r).read_secret_version("ro/x", mount_point=MOUNT,
                                                                   raise_on_deleted_version=True)["data"]["data"]),
        lambda c: as_reader(c, lambda r: kv(r).create_or_update_secret("ro/x", {"k": "w"}, mount_point=MOUNT)),
    ])


def test_child_token(pair):
    """Tokens | create a child token, look it up, revoke it (what the Terraform provider does)"""
    def child(c):
        t = c.auth.token.create(policies=["default"], ttl="20m")["auth"]["client_token"]
        r = type(c)(url=c.url, token=t, timeout=60)
        me = r.auth.token.lookup_self()["data"]
        r.auth.token.revoke_self()
        return {"policies": me["policies"], "orphan": me["orphan"], "type": me["type"]}
    pair([child])


def test_userpass_login(pair):
    """Auth | userpass: create a user and log in (what aws-infra's Terraform does)"""
    pair([
        lambda c: c.auth.userpass.create_or_update_user("terraform", "pw-123", policies=["default"]).status_code,
        lambda c: sorted(c.auth.userpass.login("terraform", "pw-123")["auth"]["policies"]),
        lambda c: c.auth.userpass.login("terraform", "wrong"),
    ])


def test_mounts(pair):
    """System | the suite's mount is listed as KV version 2"""
    pair([lambda c: c.sys.read_mount_configuration(MOUNT)["data"].get("options") or
          c.sys.list_mounted_secrets_engines()["data"][f"{MOUNT}/"]["options"]])


def test_health(pair):
    """System | health: initialized and unsealed"""
    pair([lambda c: {k: v for k, v in c.sys.read_health_status(method="GET").items()
                     if k in ("initialized", "sealed", "standby", "version")}])
