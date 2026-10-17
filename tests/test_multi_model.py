from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
import threading
import time

import pytest

from meterlock.config import AlphaConfig
from meterlock.ledger import InsufficientAllowance, LockUnavailable, SQLiteLedger
from meterlock.pricing import actual_cost_nd, reservation_cost_nd
from meterlock.service import MeterLockService, UnsupportedAlphaRequest


MODELS = ("gpt-5.6-luna", "gpt-6-luna", "gpt-6-sol")


class FakeProvider:
    def __init__(self, inputs=100, usage=None):
        self.inputs = inputs
        self.counted = []
        self.generated = []
        self.result = {"service_tier": "default", "usage": usage or {
            "input_tokens": 100, "output_tokens": 16,
            "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 30},
        }}

    def count_input_tokens(self, body):
        self.counted.append(deepcopy(body))
        return self.inputs

    def create_response(self, body):
        self.generated.append(deepcopy(body))
        return deepcopy(self.result)


def setup(tmp_path, budget=100_000_000, provider=None):
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    lock, _ = ledger.create_lock("test", budget, time.time() + 3600)
    provider = provider or FakeProvider()
    return ledger, lock, provider, MeterLockService(ledger, provider)


def body(model):
    return {"model": model, "input": "hello", "max_output_tokens": 16}


@pytest.mark.parametrize("model,reserved,spent", [
    (MODELS[0], 78_800, 37_100),
    (MODELS[1], 37_000, 16_950),
    (MODELS[2], 740_000, 339_000),
])
def test_dispatch_and_exact_accounting(tmp_path, model, reserved, spent):
    ledger, lock, provider, service = setup(tmp_path)
    result = service.execute(lock, body(model))
    assert provider.counted == provider.generated
    assert provider.generated[0] == dict(body(model), store=False,
        reasoning={"effort": "none"}, service_tier="default")
    assert result["meterlock"]["reserved_nd"] == reserved
    assert result["meterlock"]["actual_cost_nd"] == spent
    assert ledger.state(lock).spent_nd == spent
    assert ledger.state(lock).reserved_nd == 0


@pytest.mark.parametrize("model", MODELS)
def test_insufficient_budget_prevents_generation(tmp_path, model):
    reserve = reservation_cost_nd(100, 16, model=model)
    ledger, lock, provider, service = setup(tmp_path, budget=reserve - 1)
    with pytest.raises(InsufficientAllowance):
        service.execute(lock, body(model))
    assert not provider.generated
    assert ledger.state(lock).spent_nd == ledger.state(lock).reserved_nd == 0


@pytest.mark.parametrize("model", ["gpt-unknown", "gpt-6.1-sol", "gpt-6-sol-latest", None, [], 12])
def test_unknown_models_never_contact_provider(tmp_path, model):
    ledger, lock, provider, service = setup(tmp_path)
    with pytest.raises(UnsupportedAlphaRequest):
        service.execute(lock, body(model))
    assert not provider.counted and not provider.generated


def test_config_can_narrow_but_not_bypass_pricing(tmp_path):
    ledger, lock, provider, service = setup(tmp_path)
    service.config = AlphaConfig(supported_models=("gpt-unknown", MODELS[0]))
    for model in ("gpt-unknown", MODELS[1]):
        with pytest.raises(UnsupportedAlphaRequest):
            service.execute(lock, body(model))
    assert not provider.counted


@pytest.mark.parametrize("field,value", [
    ("stream", True), ("tools", []), ("service_tier", "fast"),
    ("reasoning", {"effort": "max"}), ("input", []),
    ("max_output_tokens", True), ("max_output_tokens", 15), ("max_output_tokens", 501),
])
def test_existing_request_limits_remain(tmp_path, field, value):
    _, lock, provider, service = setup(tmp_path)
    request = dict(body(MODELS[1]), **{field: value})
    with pytest.raises(UnsupportedAlphaRequest):
        service.execute(lock, request)
    assert not provider.counted


@pytest.mark.parametrize("model,short,long", [
    (MODELS[0], 68_019_200, 136_029_300),
    (MODELS[1], 34_008_000, 68_012_250),
    (MODELS[2], 680_160_000, 1_360_245_000),
])
def test_long_context_threshold_and_cache_writes(model, short, long):
    def usage(n):
        return {"input_tokens": n, "output_tokens": 16,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": n}}
    assert actual_cost_nd(usage(272_000), model=model) == short
    assert actual_cost_nd(usage(272_001), model=model) == long


@pytest.mark.parametrize("model", MODELS)
def test_reservation_covers_every_supported_input_mix(model):
    # Exercise cache partitions, the pricing boundary and long context.
    for total in (0, 1, 7, 272_000, 272_001, 1_000_000):
        for cached, written in ((0, 0), (0, total), (total, 0),
                                 (total // 3, total // 3)):
            usage = {"input_tokens": total, "output_tokens": 500,
                "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": written}}
            assert actual_cost_nd(usage, model=model) <= reservation_cost_nd(total, 500, model=model)


@pytest.mark.parametrize("bad", [-1, True, 1.5, "10", None])
def test_bad_count_fails_before_generation(tmp_path, bad):
    _, lock, provider, service = setup(tmp_path, provider=FakeProvider(inputs=bad))
    with pytest.raises(ValueError):
        service.execute(lock, body(MODELS[0]))
    assert not provider.generated


@pytest.mark.parametrize("patch", [
    {"usage": None},
    {"usage": {"input_tokens": -1, "output_tokens": 16}},
    {"usage": {"input_tokens": True, "output_tokens": 16}},
    {"usage": {"input_tokens": "100", "output_tokens": 16}},
    {"usage": {"input_tokens": 100, "output_tokens": 17}},
    {"usage": {"input_tokens": 101, "output_tokens": 16}},
    {"usage": {"input_tokens": 100, "output_tokens": -1}},
    {"usage": {"input_tokens": 100, "output_tokens": 16,
               "input_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 30}}},
    {"usage": {"input_tokens": 100, "output_tokens": 16, "input_tokens_details": None}},
    {"usage": {"input_tokens": 100, "output_tokens": 16,
               "input_tokens_details": {"cached_tokens": 0}}},
    {"service_tier": "priority"}, {"service_tier": None},
])
def test_uncertain_usage_retains_full_reservation(tmp_path, patch):
    ledger, lock, provider, service = setup(tmp_path)
    provider.result.update(patch)
    with pytest.raises((RuntimeError, ValueError)):
        service.execute(lock, body(MODELS[1]))
    assert ledger.state(lock).spent_nd == 37_000
    assert ledger.state(lock).reserved_nd == 0
    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute("SELECT state FROM reservations").fetchone()[0] == "uncertain"


def test_transport_failure_retains_full_reservation(tmp_path):
    ledger, lock, provider, service = setup(tmp_path)
    def fail(body):
        raise RuntimeError("simulated upstream failure")
    provider.create_response = fail
    with pytest.raises(RuntimeError):
        service.execute(lock, body(MODELS[2]))
    assert ledger.state(lock).spent_nd == 740_000


def test_mixed_models_share_one_wallet(tmp_path):
    ledger, lock, _, service = setup(tmp_path)
    for model in MODELS:
        service.execute(lock, body(model))
    assert ledger.state(lock).spent_nd == 393_050
    assert SQLiteLedger(ledger.db_path).state(lock).spent_nd == 393_050


def test_lifecycle_still_blocks_all_models(tmp_path):
    ledger, lock, provider, service = setup(tmp_path)
    ledger.set_paused(lock, True)
    with pytest.raises(LockUnavailable, match="paused"):
        service.execute(lock, body(MODELS[1]))
    ledger.set_paused(lock, False)
    service.execute(lock, body(MODELS[1]))
    ledger.revoke(lock)
    for model in MODELS:
        with pytest.raises(LockUnavailable, match="revoked"):
            service.execute(lock, body(model))
    assert len(provider.generated) == 1


def test_concurrent_models_cannot_double_spend(tmp_path):
    # Hold one generation open while a second model tries to spend the same wallet.
    ledger, lock, provider, service = setup(tmp_path, budget=740_000)
    entered, release = threading.Event(), threading.Event()
    original = provider.create_response
    def block(request):
        entered.set()
        assert release.wait(5)
        return original(request)
    provider.create_response = block
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.execute, lock, body(MODELS[2]))
        try:
            assert entered.wait(5)
            second = pool.submit(service.execute, lock, body(MODELS[1]))
            with pytest.raises(InsufficientAllowance):
                second.result(timeout=5)
        finally:
            release.set()
        first.result(timeout=5)
    assert len(provider.generated) == 1
    assert ledger.state(lock).spent_nd == 339_000
