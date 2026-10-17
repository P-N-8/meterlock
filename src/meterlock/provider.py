from __future__ import annotations

import os
from typing import Any, Protocol

import httpx

from .pricing import token_count


class Provider(Protocol):
    def count_input_tokens(self, body: dict[str, Any]) -> int: ...
    def create_response(self, body: dict[str, Any]) -> dict[str, Any]: ...


class OpenAIProvider:
    """Minimal OpenAI adapter preserved from the successful Stage-A proof."""

    def __init__(self, api_key: str | None = None, timeout_seconds: float = 60.0):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for live forwarding")
        self.timeout_seconds = timeout_seconds

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def count_input_tokens(self, body: dict[str, Any]) -> int:
        count_body = {"model": body["model"], "input": body["input"], "reasoning": body["reasoning"]}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/responses/input_tokens",
                headers=self._headers,
                json=count_body,
            )
            response.raise_for_status()
            return token_count(response.json()["input_tokens"], "input_tokens")

    def create_response(self, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers=self._headers,
                json=body,
            )
            response.raise_for_status()
            return response.json()
