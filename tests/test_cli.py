"""lambdavault status / output against a fake Vault (a local HTTP server) and a fake `terraform output`."""
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lambdavault import cli


@pytest.fixture
def vault():
    """A Vault that answers sys/health; state["busy"] answers 429 that many times first."""
    state = {"busy": 0, "initialized": True}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            code, body = (429, {"errors": ["busy"]}) if state["busy"] else \
                (200, {"initialized": state["initialized"], "sealed": False, "version": "1.20.3"})
            state["busy"] = max(0, state["busy"] - 1)
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["addr"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()


@pytest.fixture
def terraform(monkeypatch, vault):
    """`terraform output -json` of a deployed stack, and no VAULT_ADDR in the environment."""
    def run(cmd, **kw):
        assert cmd[:1] == ["terraform"] and cmd[-2:] == ["output", "-json"]
        out = {"vault_addr": {"value": vault["addr"]}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")
    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.delenv("VAULT_ADDR", raising=False)


def test_output_reads_terraform_output(terraform, vault, capsys):
    cli.main(["output"])
    assert capsys.readouterr().out.strip() == f"export VAULT_ADDR={vault['addr']}"


def test_addr_overrides_terraform(terraform, capsys):
    cli.main(["output", "--addr", "https://example.lambda-url.us-east-2.on.aws/"])
    assert capsys.readouterr().out.strip() == "export VAULT_ADDR=https://example.lambda-url.us-east-2.on.aws"


def test_status(terraform, vault, capsys):
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "initialized True" in out and "Vault 1.20.3" in out


def test_status_says_how_to_initialize(terraform, vault, capsys):
    vault["initialized"] = False
    cli.main(["status"])
    assert "vault operator init -recovery-shares=1 -recovery-threshold=1" in capsys.readouterr().out


def test_busy_function_is_retried(terraform, vault, capsys):
    vault["busy"] = 2   # reserved concurrency 1: a second caller gets 429 while the function is busy
    cli.main(["status"])
    assert "Vault 1.20.3" in capsys.readouterr().out


def test_not_deployed_says_so(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "{}", ""))
    with pytest.raises(SystemExit) as e:
        cli.main(["status"])
    assert "no vault_addr" in str(e.value)
