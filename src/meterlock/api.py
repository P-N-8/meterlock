from __future__ import annotations

import hmac
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
import httpx

from .config import CONFIG, NANODOLLARS_PER_DOLLAR
from .ledger import InsufficientAllowance, LockUnavailable, SQLiteLedger
from .provider import OpenAIProvider
from .service import MeterLockService, UnsupportedAlphaRequest

DB_PATH = Path(os.environ.get("METERLOCK_DB", "./meterlock-alpha.db"))
ADMIN_TOKEN = os.environ.get("METERLOCK_ADMIN_TOKEN", "")
ledger = SQLiteLedger(DB_PATH)
provider = OpenAIProvider()
service = MeterLockService(ledger=ledger, provider=provider)

app = FastAPI(title="MeterLock External Developer Alpha", version="0.3.0a1")


def _require_admin(authorization: str | None) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="METERLOCK_ADMIN_TOKEN is not configured")
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if not hmac.compare_digest(supplied, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="invalid admin token")


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="MeterLock bearer key required")
    return authorization[7:]


def _to_nd(value: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail="budget_usd must be decimal text") from exc
    if amount <= 0:
        raise HTTPException(status_code=400, detail="budget_usd must be positive")
    return int((amount * NANODOLLARS_PER_DOLLAR).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _state_payload(state):
    return {
        "lock_id": state.lock_id,
        "label": state.label,
        "status": state.status,
        "budget_nd": state.budget_nd,
        "spent_nd": state.spent_nd,
        "reserved_nd": state.reserved_nd,
        "remaining_nd": state.available_nd,
        "expires_at": state.expires_at,
    }


@app.post("/_meterlock/admin/locks")
def create_lock(body: dict, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    label = body.get("label")
    if not isinstance(label, str) or not label.strip():
        raise HTTPException(status_code=400, detail="label is required")
    budget_nd = _to_nd(str(body.get("budget_usd", "")))
    if budget_nd < CONFIG.minimum_budget_nd:
        raise HTTPException(status_code=400, detail="budget is below alpha minimum")
    minutes = body.get("expires_in_minutes")
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 1 or minutes > 10080:
        raise HTTPException(status_code=400, detail="expires_in_minutes must be 1..10080")
    lock_id, raw_key = ledger.create_lock(label, budget_nd, time.time() + minutes * 60)
    return {
        "lock": _state_payload(ledger.state(lock_id)),
        "meterlock_key": raw_key,
        "warning": "This scoped key is returned once. Store it securely.",
    }


@app.get("/_meterlock/admin/locks")
def list_locks(authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    return {"locks": [_state_payload(s) for s in ledger.list_states()]}


@app.get("/_meterlock/admin/locks/{lock_id}")
def lock_state(lock_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    try:
        return _state_payload(ledger.state(lock_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="lock not found")


@app.post("/_meterlock/admin/locks/{lock_id}/pause")
def pause_lock(lock_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    try:
        ledger.set_paused(lock_id, True)
        return _state_payload(ledger.state(lock_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="lock not found")


@app.post("/_meterlock/admin/locks/{lock_id}/resume")
def resume_lock(lock_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    try:
        ledger.set_paused(lock_id, False)
        return _state_payload(ledger.state(lock_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="lock not found")


@app.post("/_meterlock/admin/locks/{lock_id}/revoke")
def revoke_lock(lock_id: str, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    try:
        ledger.revoke(lock_id)
        return _state_payload(ledger.state(lock_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="lock not found")


@app.get("/_meterlock/me")
def my_state(authorization: str | None = Header(default=None)):
    try:
        state = ledger.authenticate_key(_bearer(authorization))
        return _state_payload(state)
    except LockUnavailable as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": str(exc)})


@app.post("/v1/responses")
def responses(body: dict, authorization: str | None = Header(default=None)):
    try:
        state = ledger.authenticate_key(_bearer(authorization))
        result = service.execute(state.lock_id, body)
        meta = result["meterlock"]
        # Preserve the provider response body so OpenAI-compatible clients do not
        # need to understand a MeterLock wrapper. Accounting is returned in headers.
        return JSONResponse(
            content=result["provider_response"],
            headers={
                "X-MeterLock-Lock-ID": str(meta["lock_id"]),
                "X-MeterLock-Actual-Cost-ND": str(meta["actual_cost_nd"]),
                "X-MeterLock-Remaining-ND": str(meta["remaining_nd"]),
            },
        )
    except InsufficientAllowance as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "meterlock_allowance_exhausted",
                "message": "Request rejected before provider generation dispatch: insufficient locked allowance.",
                "remaining_nd": exc.remaining_nd,
                "required_reservation_nd": exc.requested_nd,
            },
        )
    except LockUnavailable as exc:
        code = 401 if exc.code == "invalid_key" else 423
        raise HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})
    except UnsupportedAlphaRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_provider_rejected_request",
                "provider_status": exc.response.status_code,
                "message": "OpenAI rejected the forwarded request. MeterLock retained the full reservation conservatively.",
            },
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_provider_transport_error",
                "message": "OpenAI transport failed after authorization. MeterLock retained the full reservation conservatively.",
            },
        )
