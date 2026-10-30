# lambdavault compatibility report · [tasks](TASKS.md)

Generated 2026-10-29 by `pytest tests` · lambdavault 0.1.0 · Python 3.9.6

Each row is one feature exercised the same way on the reference and on the project; results, types and errors must match. The feature list only grows (a removed case would show in git), so the support percentage can only move up.

Whole test run: **37 passed**, 0 failed, 1 expected failures (known gaps), 0 skipped — regression suite (`tests/`) and compatibility suite (`tests/compat/`) together.

Open tasks: task 5 (1) — see [TASKS.md](TASKS.md).

## lambdavault (Vault on Lambda + S3 + KMS) vs Vault (deployed Lambda https://vwqd4vyakkkwi4rbnbczf4dsiy0ssqll.lambda-url.us-east-2.on.aws) — reference: Vault 2.2.0 (Docker)

**Support 92%** (13 / 14 features) · 1 gap · 13 verified

✅ verified · ❌ gap — known difference, the note names the task that closes it · ⚪ quirk — documented, deliberately not aligned · ⛔ unsupported by design, refused with NotSupportedError · 🟡 fixed — xfail marker to remove · 🔴 regression · ⏭ not run

| Feature | Status | Note |
|---|---|---|
| **KV v2** | | |
| check-and-set: a stale cas is refused | ✅ |  |
| delete metadata removes every version | ✅ |  |
| destroy a version for good | ✅ |  |
| patch merges into the latest version | ✅ |  |
| soft delete of the latest version, then undelete restores it | ✅ |  |
| versions: an older version stays readable; metadata counts them | ✅ |  |
| write a secret and read the latest version | ✅ |  |
| list keys: folders end with / | ❌ gap |  |
| **Tokens** | | |
| create a child token, look it up, revoke it (what the Terraform provider does) | ✅ |  |
| **Policies** | | |
| an ACL policy is stored and enforced: read-only token cannot write | ✅ |  |
| **Auth** | | |
| userpass: create a user and log in (what aws-infra's Terraform does) | ✅ |  |
| **System** | | |
| health: initialized and unsealed | ✅ |  |
| the suite's mount is listed as KV version 2 | ✅ |  |
| **Errors** | | |
| reading a path that was never written | ✅ |  |
