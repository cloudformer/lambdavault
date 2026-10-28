"""lambdavault init / status / output against a fake Vault (a local HTTP server) and a fake SSM."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lambdavault import cli


class FakeSSM:
    class exceptions:
        class ParameterNotFound(Exception):
            pass

    def __init__(self, params):
        self.params = dict(params)

    def get_parameter(self, Name, WithDecryption=False):
        if Name not in self.params:
            raise self.exceptions.ParameterNotFound(Name)
        return {"Parameter": {"Value": self.params[Name]}}

    def put_parameter(self, Name, Value, Type, Overwrite):
        assert Type == "SecureString" and not Overwrite and Name not in self.params
        self.params[Name] = Value


@pytest.fixture
def vault():
    """A Vault that answers sys/init and sys/health; state["busy"] answers 429 that many times first."""
    state = {"initialized": False, "busy": 0, "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def handle_any(self):
            state["calls"].append((self.command, self.path))
            if state["busy"]:
                state["busy"] -= 1
                return self.reply(429, {"errors": ["busy"]})
            if self.path == "/v1/sys/init" and self.command == "GET":
                return self.reply(200, {"initialized": state["initialized"]})
            if self.path == "/v1/sys/init" and self.command == "PUT":
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                assert body == {"recovery_shares": 1, "recovery_threshold": 1}
                state["initialized"] = True
                return self.reply(200, {"root_token": "hvs.root", "recovery_keys_b64": ["rk=="]})
            if self.path.startswith("/v1/sys/health"):
                return self.reply(200, {"initialized": state["initialized"], "sealed": False, "version": "1.20.3"})
            self.reply(404, {"errors": []})

        do_GET = do_PUT = handle_any

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["addr"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()


@pytest.fixture
def ssm(monkeypatch, vault):
    fake = FakeSSM({"/lambdavault/vault_addr": vault["addr"]})
    monkeypatch.setattr(cli, "ssm", lambda args: fake)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    return fake


def test_init_stores_root_token_and_recovery_key(ssm, vault, capsys):
    cli.main(["init"])
    assert ssm.params["/lambdavault/root_token"] == "hvs.root"
    assert ssm.params["/lambdavault/recovery_key"] == "rk=="
    assert "initialized" in capsys.readouterr().out


def test_init_twice_changes_nothing(ssm, vault, capsys):
    cli.main(["init"])
    cli.main(["init"])
    assert "already initialized" in capsys.readouterr().out
    assert [c for c in vault["calls"] if c[0] == "PUT"] == [("PUT", "/v1/sys/init")]


def test_init_print_stores_nothing(ssm, vault, capsys):
    cli.main(["init", "--print"])
    assert "hvs.root" in capsys.readouterr().out
    assert "/lambdavault/root_token" not in ssm.params


def test_busy_function_is_retried(ssm, vault, capsys):
    vault["busy"] = 2   # reserved concurrency 1: a second caller gets 429 while the function is busy
    cli.main(["status"])
    assert "Vault 1.20.3" in capsys.readouterr().out


def test_output_exports(ssm, vault, capsys):
    cli.main(["init"])
    capsys.readouterr()
    cli.main(["output", "--token"])
    assert capsys.readouterr().out.splitlines() == [f"export VAULT_ADDR={vault['addr']}", "export VAULT_TOKEN=hvs.root"]


def test_unknown_deployment_says_so(monkeypatch):
    monkeypatch.setattr(cli, "ssm", lambda args: FakeSSM({}))
    with pytest.raises(SystemExit) as e:
        cli.main(["status", "--name", "other"])
    assert "/other/vault_addr" in str(e.value)
