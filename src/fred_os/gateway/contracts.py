"""Boundary contracts for the M1 FRED OS Command Gateway."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from fred_os.runtime.contracts import CommandResult, ExecutionReceipt, StateDelta, normalize_for_hash


class GatewayError(RuntimeError):
    """Base class for deterministic gateway failures."""


class AuthenticationError(GatewayError):
    pass


class AuthorizationError(GatewayError):
    pass


class SchemaValidationError(GatewayError):
    pass


class CapabilityNotFoundError(GatewayError):
    pass


class IdempotencyConflictError(GatewayError):
    pass


class IdempotencyInProgressError(GatewayError):
    """Another live gateway worker owns the same logical request."""


@dataclass(frozen=True)
class GatewayPrincipal:
    caller_id: str
    permissions: tuple[str, ...]


@dataclass(frozen=True)
class TokenRecord:
    token_hash: str
    caller_id: str
    permissions: tuple[str, ...]


@dataclass(frozen=True)
class GatewayRequest:
    target_capability: str
    payload: dict[str, Any]
    idempotency_key: str
    token: str
    session_id: str | None = None
    command_id: str | None = None


@dataclass(frozen=True)
class IdempotencyRecord:
    caller_id: str
    idempotency_key: str
    request_hash: str
    status: str
    command_id: str | None = None
    result_json: str | None = None
    owner_token: str | None = None
    lease_expires_at: float | None = None


@dataclass(frozen=True)
class GatewayResponse:
    caller_id: str
    replayed: bool
    result: CommandResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller_id": self.caller_id,
            "replayed": self.replayed,
            "result": serialize_command_result(self.result),
        }


def serialize_command_result(result: CommandResult) -> dict[str, Any]:
    return {
        "command_id": result.command_id,
        "status": result.status,
        "outputs": normalize_for_hash(result.outputs),
        "receipts": [normalize_for_hash(asdict(receipt)) for receipt in result.receipts],
        "delta": normalize_for_hash(asdict(result.delta)) if result.delta is not None else None,
        "state_capsule_id": result.state_capsule_id,
    }


def deserialize_command_result(payload: dict[str, Any]) -> CommandResult:
    receipts = tuple(ExecutionReceipt(**dict(item)) for item in payload.get("receipts", ()))
    delta_payload = payload.get("delta")
    delta = StateDelta(**dict(delta_payload)) if isinstance(delta_payload, dict) else None
    return CommandResult(
        command_id=str(payload["command_id"]),
        status=str(payload["status"]),
        outputs=dict(payload.get("outputs", {})),
        receipts=receipts,
        delta=delta,
        state_capsule_id=str(payload["state_capsule_id"]),
    )
