from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import CONFIG, AlphaConfig
from .ledger import SQLiteLedger
from .pricing import MODEL_PRICING, actual_cost_nd, reservation_cost_nd, token_count
from .provider import Provider


class UnsupportedAlphaRequest(ValueError):
    pass


@dataclass
class MeterLockService:
    ledger: SQLiteLedger
    provider: Provider
    config: AlphaConfig = CONFIG

    def _validate(self, body: dict[str, Any]) -> tuple[str, int]:
        allowed = {"model", "input", "max_output_tokens"}
        unexpected = set(body) - allowed
        if unexpected:
            raise UnsupportedAlphaRequest(
                f"Alpha rejects unsupported fields: {sorted(unexpected)}"
            )
        model = body.get("model")
        if not isinstance(model, str) or model not in self.config.supported_models or model not in MODEL_PRICING:
            raise UnsupportedAlphaRequest(
                "Unsupported model. Choose: " + ", ".join(
                    m for m in self.config.supported_models if m in MODEL_PRICING
                )
            )
        text = body.get("input")
        if not isinstance(text, str) or not text:
            raise UnsupportedAlphaRequest("input must be a non-empty plain string")
        max_output_tokens = body.get("max_output_tokens")
        if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool):
            raise UnsupportedAlphaRequest("max_output_tokens must be an integer")
        if (
            max_output_tokens < self.config.min_output_tokens
            or max_output_tokens > self.config.max_output_tokens_cap
        ):
            raise UnsupportedAlphaRequest(
                f"max_output_tokens must be {self.config.min_output_tokens}..{self.config.max_output_tokens_cap}"
            )
        return text, max_output_tokens

    def execute(self, lock_id: str, body: dict[str, Any]) -> dict[str, Any]:
        text, max_output_tokens = self._validate(body)
        provider_body = {
            "model": body["model"],
            "input": text,
            "max_output_tokens": max_output_tokens,
            "store": False,
            "reasoning": {"effort": "none"},
            "service_tier": "default",
        }

        input_tokens = token_count(self.provider.count_input_tokens(provider_body), "input_tokens")
        reserve_nd = reservation_cost_nd(input_tokens, max_output_tokens, model=body["model"])
        reservation_id = self.ledger.reserve(lock_id, reserve_nd)

        try:
            result = self.provider.create_response(provider_body)
            if result.get("service_tier") != "default":
                raise RuntimeError("provider did not confirm Standard processing")
            usage = result.get("usage")
            if not isinstance(usage, dict):
                raise RuntimeError("provider response did not contain usage")
            cost_nd = actual_cost_nd(usage, model=body["model"])
            if usage["input_tokens"] > input_tokens or usage["output_tokens"] > max_output_tokens:
                raise RuntimeError("provider usage exceeded the pre-authorized token bounds")
            self.ledger.settle(reservation_id, cost_nd)
            state = self.ledger.state(lock_id)
            return {
                "status": "ok",
                "meterlock": {
                    "lock_id": lock_id,
                    "reserved_nd": reserve_nd,
                    "actual_cost_nd": cost_nd,
                    "remaining_nd": state.available_nd,
                },
                "provider_response": result,
            }
        except Exception:
            self.ledger.mark_uncertain_full_cost(reservation_id)
            raise
