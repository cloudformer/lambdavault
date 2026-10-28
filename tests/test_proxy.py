"""The proxy: requests pass through unchanged, a busy Vault function is waited for, not answered with 429."""
import importlib.util
import io
import json
import os

import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-2")
os.environ.setdefault("VAULT_FUNCTION", "lambdavault-lambda")
spec = importlib.util.spec_from_file_location(
    "proxy", os.path.join(os.path.dirname(__file__), "..", "src", "proxy", "lambda_function.py"))
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class Busy(Exception):
    pass


class FakeLambda:
    """Refuses the first `busy` invokes as Lambda does when the reserved concurrency is used up."""
    class exceptions:
        TooManyRequestsException = Busy

    def __init__(self, busy=0, error=None):
        self.busy, self.error, self.calls = busy, error, []

    def invoke(self, FunctionName, Payload):
        self.calls.append((FunctionName, json.loads(Payload)))
        if self.busy:
            self.busy -= 1
            raise Busy()
        if self.error:
            return {"FunctionError": "Unhandled", "Payload": io.BytesIO(self.error.encode())}
        reply = {"statusCode": 200, "headers": {"content-type": "application/json"}, "body": '{"sealed":false}'}
        return {"Payload": io.BytesIO(json.dumps(reply).encode())}


EVENT = {"rawPath": "/v1/sys/health", "requestContext": {"http": {"method": "GET"}}, "headers": {"x-vault-token": "t"}}


@pytest.fixture
def lam(monkeypatch):
    def use(fake):
        monkeypatch.setattr(proxy, "lam", fake)
        monkeypatch.setattr(proxy.time, "sleep", lambda s: None)
        return fake
    return use


def test_passes_the_request_and_the_reply_through_unchanged(lam):
    fake = lam(FakeLambda())
    r = proxy.lambda_handler(EVENT, None)
    assert fake.calls == [("lambdavault-lambda", EVENT)]
    assert r["statusCode"] == 200 and r["body"] == '{"sealed":false}'


def test_a_busy_vault_is_waited_for(lam):
    fake = lam(FakeLambda(busy=5))
    assert proxy.lambda_handler(EVENT, None)["statusCode"] == 200
    assert len(fake.calls) == 6


def test_gives_up_only_after_the_queue_time(lam, monkeypatch):
    lam(FakeLambda(busy=10 ** 6))
    clock = iter(range(0, 10 ** 6, 5))   # every look at the clock is 5 s later
    monkeypatch.setattr(proxy.time, "time", lambda: next(clock))
    r = proxy.lambda_handler(EVENT, None)
    assert r["statusCode"] == 429 and "busy" in r["body"]


def test_a_failing_vault_function_is_a_502(lam):
    lam(FakeLambda(error='{"errorMessage":"boom"}'))
    r = proxy.lambda_handler(EVENT, None)
    assert r["statusCode"] == 502 and "boom" in r["body"]
