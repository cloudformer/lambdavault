"""The image, the Vault config and Terraform agree on the few values they share."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
read = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()  # noqa: E731


def test_adapter_port_is_the_vault_listener():
    port = re.search(r"AWS_LWA_PORT=(\d+)", read("src", "server", "Dockerfile")).group(1)
    assert f'address     = "127.0.0.1:{port}"' in read("src", "server", "vault.hcl")


def test_vault_version_is_the_reference_version():
    image = re.search(r"FROM hashicorp/vault:(\S+)", read("src", "server", "Dockerfile")).group(1)
    assert f"image: hashicorp/vault:{image}" in read("tests", "compat", "docker-compose.yml")


def test_storage_and_seal_come_from_the_environment_terraform_sets():
    hcl, tf = read("src", "server", "vault.hcl"), read("terraform", "main.tf")
    assert 'storage "s3" {}' in hcl and 'seal "awskms" {}' in hcl
    assert "AWS_S3_BUCKET" in tf and "VAULT_AWSKMS_SEAL_KEY_ID" in tf


def test_one_vault_process_at_a_time():
    assert "reserved_concurrent_executions = 1" in read("terraform", "main.tf")
