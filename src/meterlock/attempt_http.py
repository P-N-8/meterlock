"""One fixed HTTP POST action guarded by durable Attempt Lock reservation.

No redirects, retries, proxies, credentials or provider SDK. The storage owner
and caller are trusted; this adapter does not sandbox other networking code.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import http.client
import math
from typing import Any
from urllib.parse import SplitResult, urlsplit

from .attempt_lock import AttemptLock


@dataclass(frozen=True)
class AttemptHTTPAction:
    """Bind one owner-selected task/action identity to one endpoint.

    Authority must already exist; construction never creates or resets it.
    Every send reserves separately, including manual retries after failures.
    """

    lock: AttemptLock
    task_id: str
    action: str
    url: str
    timeout: float = 5.0
    _endpoint: SplitResult = field(init=False, repr=False)

    def __post_init__(self):
        for identity in (self.task_id, self.action):
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError("task_id and action must be non-empty strings")
        if not isinstance(self.url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in self.url):
            raise ValueError("url must be an HTTP(S) URL without whitespace/control characters")
        endpoint = urlsplit(self.url)
        if (endpoint.scheme not in ("http", "https") or not endpoint.hostname
                or endpoint.username is not None or endpoint.password is not None
                or "#" in self.url):
            raise ValueError("url must have an HTTP(S) host, without credentials or fragment")
        # Force invalid ports to fail during local validation, without dispatch.
        endpoint.port
        if (type(self.timeout) not in (int, float) or not math.isfinite(self.timeout)
                or self.timeout <= 0):
            raise ValueError("timeout must be a finite positive number")
        object.__setattr__(self, "_endpoint", endpoint)

    def send(self, body: bytes = b"") -> dict[str, Any]:
        """Reserve before connection creation/DNS; make at most one HTTP request.

        Validation errors do not consume authority. After a committed grant,
        transport errors, non-2xx responses and crashes never refund the slot.
        dispatch_attempted reports entering transport, not confirmed delivery.
        """
        if type(body) is not bytes:
            raise TypeError("body must be bytes")
        decision = self.lock.reserve(self.task_id, self.action)
        if decision["outcome"] != "ALLOW":
            return {**decision, "dispatch_attempted": False, "http": None}

        connection = None
        try:
            endpoint = self._endpoint
            connection_type = (http.client.HTTPSConnection if endpoint.scheme == "https"
                               else http.client.HTTPConnection)
            connection = connection_type(endpoint.hostname, endpoint.port, timeout=self.timeout)
            target = endpoint.path or "/"
            if endpoint.query:
                target += "?" + endpoint.query
            connection.request("POST", target, body=body,
                               headers={"Content-Type": "application/octet-stream"})
            response = connection.getresponse()
            # Bound the response retained in memory; connections are never reused.
            payload = response.read(65537)
            result = {
                "outcome": "SUCCESS" if 200 <= response.status < 300 else "HTTP_ERROR",
                "status_code": response.status,
                "body_base64": base64.b64encode(payload[:65536]).decode("ascii"),
                "body_truncated": len(payload) > 65536,
            }
        except (OSError, http.client.HTTPException) as exc:
            result = {"outcome": "TRANSPORT_ERROR", "error_type": type(exc).__name__}
        finally:
            if connection is not None:
                connection.close()
        return {**decision, "dispatch_attempted": True, "http": result}
