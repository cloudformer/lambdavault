"""The image, the Vault config and the package agree on the few values they share.

What Terraform sets (reserved concurrency 1, the proxy as the only URL, the seal's resources) lives in the Registry
module (terraform-aws-infra modules/lambdavault); its mock tests cover the seal's resources and names."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = ("client", "lambdavault", "server")
read = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()  # noqa: E731


def test_adapter_port_is_the_vault_listener():
    port = re.search(r"AWS_LWA_PORT=(\d+)", read(*SERVER, "Dockerfile")).group(1)
    assert f'address     = "127.0.0.1:{port}"' in read(*SERVER, "vault.hcl")


def test_vault_version_is_the_reference_version():
    image = re.search(r"FROM hashicorp/vault:(\S+)", read(*SERVER, "Dockerfile")).group(1)
    assert f"image: hashicorp/vault:{image}" in read("tests", "compat", "docker-compose.yml")


def test_storage_from_the_environment_and_the_seal_by_mode():
    hcl, kms = read(*SERVER, "vault.hcl"), read(*SERVER, "seal-awskms.hcl")
    assert 'storage "s3" {}' in hcl and "seal " not in re.sub(r"#.*", "", hcl)   # no stanza = Shamir (seal = ssm)
    assert 'seal "awskms" {}' in kms                                              # key: VAULT_AWSKMS_SEAL_KEY_ID


def test_a_sealed_vault_is_never_ready():
    # fail closed: the adapter forwards nothing until Vault is unsealed (or not initialized yet)
    assert 'AWS_LWA_READINESS_CHECK_PATH="/v1/sys/health?uninitcode=204&sealedcode=503"' in read(*SERVER, "Dockerfile")


def test_every_file_the_image_copies_is_in_the_package():
    copied = re.search(r"^COPY (vault\.hcl.*) /etc/lambdavault/$", read(*SERVER, "Dockerfile"), re.M).group(1).split()
    data = re.search(r'^"lambdavault\.server" = \[(.*)\]', read("client", "pyproject.toml"), re.M).group(1)
    assert sorted(copied + ["Dockerfile"]) == sorted(re.findall(r'"([^"]+)"', data))   # + what builds the image
