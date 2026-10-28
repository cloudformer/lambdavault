# Moving to a Vault cluster

lambdavault is for teams whose Vault is idle most of the time. When you need many concurrent callers, Raft,
replication or Enterprise features, move to a Vault cluster. The data moves with Vault's own tool: it is the
same Vault, only the storage changes.

1. Stop writes (or accept that the last minutes are re-applied by hand).
2. On a machine with AWS credentials for the bucket, write a migration config and run Vault's storage migration:

   ```hcl
   # migrate.hcl
   storage_source "s3" {
     bucket = "<terraform output bucket>"
     region = "<region>"
   }
   storage_destination "raft" {
     path    = "/opt/vault/data"
     node_id = "vault-1"
   }
   cluster_addr = "https://vault-1:8201"
   ```

   ```bash
   vault operator migrate -config=migrate.hcl
   ```

3. Start the new cluster with the same `seal "awskms"` key (`terraform output kms_key_id`), so it unseals the
   migrated data; then change `VAULT_ADDR` everywhere.
4. Delete the stack: `terraform -chdir=terraform destroy -var-file=my.json` (set `force_destroy = true` first if
   the bucket should go with it).

What you gain: concurrency, Raft HA, replication and every Vault feature. What you lose: the ≈ $1 idle bill.
