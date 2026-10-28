# Tasks

The numbers [REPORT.md](REPORT.md) and the README refer to. Open first; done ones stay below so old notes keep
resolving. Numbers are never reused.

## Open

| task | what |
|---|---|
| 2 | `lambdavault migrate --from <vault addr>`: copy every KV v2 secret (all versions) from an existing Vault |
| 3 | Source-IP allowlist for the Function URL |
| 4 | Several isolated vaults: one deployment per `name` (own bucket, KMS key, URL); document and test |

Permanent, not tasks: ⛔ unsupported — Raft, replication, performance standbys and every Vault Enterprise
feature (the binary is Vault Community).

## Done

| task | what | release |
|---|---|---|
| 1 | Concurrent callers: the proxy Lambda queues them for the one Vault (was: Lambda's 429) | 0.1.0 |
