import importlib
import json
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from meterlock.provider import OpenAIProvider


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-placeholder")
    monkeypatch.setenv("METERLOCK_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("METERLOCK_ADMIN_TOKEN", "offline-admin-placeholder")
    sys.modules.pop("meterlock.api", None)
    module = importlib.import_module("meterlock.api")
    yield module
    sys.modules.pop("meterlock.api", None)


@pytest.mark.parametrize("model,cost", [
    ("gpt-5.6-luna", "44200"), ("gpt-6-luna", "20500"), ("gpt-6-sol", "410000"),
])
def test_http_adapter_and_passthrough(api, monkeypatch, model, cost):
    calls = []
    result = {"id": "resp_offline", "model": model, "service_tier": "default",
              "output": [], "usage": {"input_tokens": 100, "output_tokens": 16,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 100}}}
    def handle(request):
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        assert request.url.host == "api.openai.com"
        assert payload["model"] == model
        if request.url.path.endswith("/input_tokens"):
            assert payload == {"model": model, "input": "hello", "reasoning": {"effort": "none"}}
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 100})
        assert api.ledger.state(lock).reserved_nd > 0
        assert payload["service_tier"] == "default"
        assert payload["store"] is False
        return httpx.Response(200, json=result)
    original_client = httpx.Client
    def mocked_client(**kwargs):
        return original_client(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr("meterlock.provider.httpx.Client", mocked_client)
    lock, key = api.ledger.create_lock("http", 10_000_000, time.time() + 60)
    with TestClient(api.app) as client:
        response = client.post("/v1/responses", headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "input": "hello", "max_output_tokens": 16})
    assert response.status_code == 200
    assert response.json() == result
    assert response.headers["X-MeterLock-Actual-Cost-ND"] == cost
    assert [path for path, _ in calls] == ["/v1/responses/input_tokens", "/v1/responses"]


def test_http_unknown_model_returns_400_without_upstream(api, monkeypatch):
    def forbidden(*args):
        raise AssertionError("unsupported model must not contact upstream")
    monkeypatch.setattr(api.provider, "count_input_tokens", forbidden)
    _, key = api.ledger.create_lock("http", 10_000_000, time.time() + 60)
    with TestClient(api.app) as client:
        response = client.post("/v1/responses", headers={"Authorization": f"Bearer {key}"},
            json={"model": "unknown", "input": "hello", "max_output_tokens": 16})
    assert response.status_code == 400
    assert "gpt-6-sol" in response.json()["detail"]


@pytest.mark.parametrize("bad", [True, -1, 1.2, "10", None])
def test_adapter_does_not_coerce_invalid_counts(monkeypatch, bad):
    original_client = httpx.Client
    def mocked_client(**kwargs):
        return original_client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"input_tokens": bad})), **kwargs)
    monkeypatch.setattr("meterlock.provider.httpx.Client", mocked_client)
    with pytest.raises(ValueError):
        OpenAIProvider(api_key="offline-placeholder").count_input_tokens({
            "model": "gpt-6-luna", "input": "hello", "reasoning": {"effort": "none"}})
