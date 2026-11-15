"""The seal: kms (Vault's awskms auto-unseal) or ssm (Shamir, the one unseal key kept in SSM Parameter Store).

entrypoint.sh runs with a fake `vault` (records how it was started) and a fake `curl` (answers Vault's
seal-status / unseal and SSM GetParameter); the proxy's init path with a fake Lambda and a fake SSM.
"""
import importlib.util
import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRYPOINT = os.path.join(ROOT, "client", "lambdavault", "server", "entrypoint.sh")
PARAMETER = "/lambdavault/unseal-key"
KEY = "6f1c0ffee0ddba11"
SEALED = '{"type":"shamir","initialized":true,"sealed":true,"t":1,"n":1}'

FAKE_VAULT = """#!%s
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"vault": sys.argv[1:]}) + "\\n")
"""

FAKE_CURL = """#!%s
import json, os, sys
args, url = sys.argv[1:], sys.argv[-1]
data = sys.stdin.read() if "@-" in args else None
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"curl": args, "stdin": data}) + "\\n")
if url.endswith("/v1/sys/seal-status"):
    print(os.environ["FAKE_SEAL_STATUS"])
elif url.startswith("https://ssm."):
    if not os.environ.get("FAKE_SSM_VALUE"):
        print('{"__type":"ParameterNotFound"}')
        sys.exit(22)
    print(json.dumps({"Parameter": {"Name": "x", "Type": "SecureString", "Value": os.environ["FAKE_SSM_VALUE"], "Version": 1}}))
elif url.endswith("/v1/sys/unseal"):
    if json.loads(data)["key"] != os.environ["FAKE_GOOD_KEY"]:
        sys.exit(22)   # Vault: 400, curl -f
    print('{"type":"shamir","initialized":true,"sealed":false}')
"""


@pytest.fixture
def start(tmp_path):
    """Run entrypoint.sh with the fakes; returns (exit code, output, [calls])."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, src in (("vault", FAKE_VAULT), ("curl", FAKE_CURL)):
        (bin_dir / name).write_text(src % sys.executable)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "calls.jsonl"

    def run(seal, seal_status=SEALED, ssm_value=KEY, good_key=KEY):
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", FAKE_LOG=str(log),
                   FAKE_SEAL_STATUS=seal_status, FAKE_SSM_VALUE=ssm_value, FAKE_GOOD_KEY=good_key,
                   LAMBDAVAULT_SEAL=seal, LAMBDAVAULT_UNSEAL_KEY_PARAMETER=PARAMETER, AWS_REGION="us-east-2",
                   AWS_ACCESS_KEY_ID="AKIDEXAMPLE", AWS_SECRET_ACCESS_KEY="secret", AWS_SESSION_TOKEN="token")
        r = subprocess.run(["sh", ENTRYPOINT], env=env, capture_output=True, text=True, timeout=30)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        log.unlink(missing_ok=True)
        return r.returncode, r.stdout + r.stderr, calls
    return run


def vault_args(calls):
    return [c["vault"] for c in calls if "vault" in c]


def curl_to(calls, part):
    return [c for c in calls if "curl" in c and part in c["curl"][-1]]


def test_kms_vault_unseals_itself_with_the_awskms_config(start):
    code, _, calls = start("kms")
    assert code == 0
    assert vault_args(calls) == [["server", "-config=/etc/lambdavault/vault.hcl",
                                  "-config=/etc/lambdavault/seal-awskms.hcl"]]
    assert not curl_to(calls, "")   # nothing read from SSM, nothing unsealed


def test_ssm_reads_the_key_and_unseals_on_start(start):
    code, out, calls = start("ssm")
    assert code == 0
    assert vault_args(calls) == [["server", "-config=/etc/lambdavault/vault.hcl"]]   # Shamir: no seal stanza
    [get] = curl_to(calls, "https://ssm.us-east-2.amazonaws.com/")
    assert "aws:amz:us-east-2:ssm" in get["curl"] and "x-amz-target: AmazonSSM.GetParameter" in get["curl"]
    assert json.loads(get["curl"][get["curl"].index("--data") + 1]) == {"Name": PARAMETER, "WithDecryption": True}
    [unseal] = curl_to(calls, "/v1/sys/unseal")
    assert json.loads(unseal["stdin"]) == {"key": KEY}
    assert all(KEY not in " ".join(c["curl"]) for c in curl_to(calls, ""))   # the key goes on stdin, not argv
    assert KEY not in out and "unsealed with the key from SSM" in out


def test_ssm_missing_parameter_leaves_vault_sealed(start):
    code, out, calls = start("ssm", ssm_value="")
    assert code == 0 and not curl_to(calls, "/v1/sys/unseal")
    assert "stays sealed" in out and PARAMETER in out


def test_ssm_wrong_key_leaves_vault_sealed(start):
    _, out, calls = start("ssm", ssm_value="0000", good_key=KEY)
    assert curl_to(calls, "/v1/sys/unseal") and "did not unseal" in out and "0000" not in out


def test_ssm_not_initialized_yet_reads_nothing(start):
    _, _, calls = start("ssm", seal_status='{"type":"shamir","initialized":false,"sealed":true}')
    assert not curl_to(calls, "https://ssm.") and not curl_to(calls, "/v1/sys/unseal")


def test_unknown_seal_does_not_start_vault(start):
    code, out, calls = start("")
    assert code == 1 and not vault_args(calls) and "must be kms or ssm" in out


# ---------------- the proxy, seal = ssm: `vault operator init` ----------------
INIT_REPLY = {"keys": [KEY], "keys_base64": ["bxwM/+DduhE="], "root_token": "hvs.root"}


class FakeLambda:
    class exceptions:
        class TooManyRequestsException(Exception):
            pass

    def __init__(self):
        self.calls = []

    def invoke(self, FunctionName, Payload):
        event = json.loads(Payload)
        self.calls.append(event)
        body = {"/v1/sys/init": INIT_REPLY, "/v1/sys/unseal": {"sealed": False}}.get(event["rawPath"], {})
        reply = {"statusCode": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}
        return {"Payload": io.BytesIO(json.dumps(reply).encode())}


class FakeSSM:
    def __init__(self, fail=False):
        self.fail, self.puts = fail, []

    def put_parameter(self, **kw):
        if self.fail:
            raise PermissionError("AccessDenied")
        self.puts.append(kw)


@pytest.fixture
def proxy(monkeypatch):
    def load(seal, ssm=None):
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
        monkeypatch.setenv("VAULT_FUNCTION", "lambdavault-lambda")
        monkeypatch.setenv("SEAL", seal)
        monkeypatch.setenv("UNSEAL_KEY_PARAMETER", PARAMETER)
        spec = importlib.util.spec_from_file_location(
            "proxy_" + seal, os.path.join(ROOT, "client", "lambdavault", "proxy", "lambda_function.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.lam, module.ssm = FakeLambda(), ssm
        return module
    return load


def init_event(shares=1, threshold=1):
    return {"rawPath": "/v1/sys/init", "rawQueryString": "", "requestContext": {"http": {"method": "PUT", "path": "/v1/sys/init"}},
            "headers": {"content-type": "application/json", "content-length": "40"}, "isBase64Encoded": False,
            "body": json.dumps({"secret_shares": shares, "secret_threshold": threshold})}


def test_init_stores_the_key_in_ssm_and_unseals(proxy):
    ssm = FakeSSM()
    p = proxy("ssm", ssm)
    r = p.lambda_handler(init_event(), None)
    assert json.loads(r["body"]) == INIT_REPLY   # returned as Vault gave it, nothing more
    assert ssm.puts == [dict(ssm.puts[0], Name=PARAMETER, Value=KEY, Type="SecureString", Overwrite=True)]
    init, unseal = p.lam.calls
    assert unseal["rawPath"] == "/v1/sys/unseal" and unseal["requestContext"]["http"]["method"] == "PUT"
    assert json.loads(unseal["body"]) == {"key": KEY} and "content-length" not in unseal["headers"]


def test_init_with_more_than_one_key_share_is_refused(proxy):
    p = proxy("ssm", FakeSSM())
    r = p.lambda_handler(init_event(shares=5, threshold=3), None)
    assert r["statusCode"] == 400 and "-key-shares=1 -key-threshold=1" in r["body"]
    assert p.lam.calls == []   # Vault never saw it


def test_init_reply_survives_a_failed_ssm_write(proxy):
    p = proxy("ssm", FakeSSM(fail=True))
    body = json.loads(p.lambda_handler(init_event(), None)["body"])
    assert body["root_token"] == "hvs.root" and body["keys"] == [KEY]   # the only copy: never lost
    assert PARAMETER in body["warnings"][0]
    assert [c["rawPath"] for c in p.lam.calls] == ["/v1/sys/init"]   # not unsealed: the problem shows at once


def test_kms_init_passes_through_untouched(proxy):
    p = proxy("kms")
    event = init_event(shares=5, threshold=3)
    assert json.loads(p.lambda_handler(event, None)["body"]) == INIT_REPLY
    assert p.lam.calls == [event]
