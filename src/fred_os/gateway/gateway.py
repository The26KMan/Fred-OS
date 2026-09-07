"""Thin deterministic M1 entrance to the M0/M0.1 RuntimeKernel."""
from __future__ import annotations

from collections.abc import Mapping
import time
import uuid
from typing import Any

from fred_os.runtime.contracts import CommandEnvelope, canonical_hash
from fred_os.runtime.kernel import RuntimeKernel

from .auth import TokenAuthenticator
from .contracts import (
    CapabilityNotFoundError,
    GatewayError,
    GatewayRequest,
    GatewayResponse,
    IdempotencyInProgressError,
    IdempotencyRecord,
    SchemaValidationError,
    deserialize_command_result,
    serialize_command_result,
)
from .idempotency import IdempotencyStore


class IdempotencyRecoveryError(GatewayError):
    """A prior authoritative outcome exists but its full boundary result is unavailable."""


class CommandGateway:
    """Authenticate, validate, deduplicate, and dispatch without owning cognitive semantics."""

    def __init__(
        self,
        kernel: RuntimeKernel,
        authenticator: TokenAuthenticator,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self.kernel = kernel
        self.authenticator = authenticator
        self.idempotency_store = idempotency_store

    def execute(self, request: GatewayRequest) -> GatewayResponse:
        principal = self.authenticator.authenticate(request.token)
        descriptor = self._capability_descriptor(request.target_capability)
        self.authenticator.authorize(
            principal,
            request.target_capability,
            descriptor.get("required_permissions", ()),
        )
        self._validate_payload(request.payload, descriptor.get("input_schema", {}))

        session_id = request.session_id or self.kernel.get_current_capsule().session_id
        request_hash = canonical_hash(
            {
                "caller_id": principal.caller_id,
                "session_id": session_id,
                "target_capability": request.target_capability,
                "payload": request.payload,
            }
        )
        command_id = request.command_id or f"cmd-{uuid.uuid4().hex}"
        owner_token = self.idempotency_store.new_owner_token()

        while True:
            existing = self.idempotency_store.get(principal.caller_id, request.idempotency_key)
            if existing is None:
                record, acquired = self.idempotency_store.reserve_owned(
                    principal.caller_id,
                    request.idempotency_key,
                    request_hash,
                    command_id,
                    owner_token,
                )
                if acquired:
                    break
                existing = record

            self.idempotency_store._assert_same_request(existing, request_hash)
            if existing.status == "COMPLETE":
                result = deserialize_command_result(self.idempotency_store.decode_result(existing))
                return GatewayResponse(principal.caller_id, True, result)

            # A live worker owns this logical request. Wait for its result rather
            # than deleting or stealing the reservation. A dead worker's lease
            # expires and may then be recovered/reclaimed deterministically.
            observed = self.idempotency_store.wait_for_change(
                principal.caller_id,
                request.idempotency_key,
                request_hash,
            )
            if observed is None:
                continue
            if observed.status == "COMPLETE":
                result = deserialize_command_result(self.idempotency_store.decode_result(observed))
                return GatewayResponse(principal.caller_id, True, result)

            lease_expired = (observed.lease_expires_at or 0.0) <= time.time()
            if not lease_expired:
                raise IdempotencyInProgressError(
                    f"idempotency key {request.idempotency_key!r} is still owned by another live worker"
                )

            recovered = self._recover_pending(observed)
            if recovered is not None:
                return GatewayResponse(principal.caller_id, True, recovered)
            if self.idempotency_store.claim_if_expired(
                principal.caller_id,
                request.idempotency_key,
                request_hash,
                command_id,
                owner_token,
            ):
                break
            # Another waiter won the expired lease race; observe the new owner.

        envelope = CommandEnvelope(
            command_id=command_id,
            target_capability=request.target_capability,
            payload=dict(request.payload),
            session_id=session_id,
            idempotency_key=request.idempotency_key,
            caller_id=principal.caller_id,
            request_fingerprint=request_hash,
        )
        try:
            with self.idempotency_store.lease_guard(
                principal.caller_id,
                request.idempotency_key,
                request_hash,
                owner_token,
            ):
                runtime_result = self.kernel.dispatch(envelope)
        except Exception:
            self.idempotency_store.release_owned(
                principal.caller_id,
                request.idempotency_key,
                request_hash,
                owner_token,
            )
            raise

        result_payload = serialize_command_result(runtime_result)
        self.idempotency_store.finalize_owned(
            principal.caller_id,
            request.idempotency_key,
            request_hash,
            owner_token,
            result_payload,
        )
        normalized = deserialize_command_result(result_payload)
        return GatewayResponse(principal.caller_id, False, normalized)

    def _recover_pending(self, record: IdempotencyRecord):
        """Recover journal-embedded results, or refuse duplicate execution after a known commit."""
        for entry in reversed(self.kernel.journal.entries()):
            payload = entry.payload
            if str(payload.get("command_id", "")) != str(record.command_id or ""):
                continue
            if str(payload.get("idempotency_key", "")) != record.idempotency_key:
                continue
            result_payload = payload.get("command_result")
            if entry.entry_type in {"TX_COMMIT", "TX_ABORT"} and isinstance(result_payload, Mapping):
                packed = dict(result_payload)
                self.idempotency_store.finalize(record.caller_id, record.idempotency_key, record.request_hash, packed)
                return deserialize_command_result(packed)
            if entry.entry_type == "TX_COMMIT":
                raise IdempotencyRecoveryError(
                    "runtime commit exists for this idempotency key but the full cached CommandResult is unavailable; "
                    "duplicate execution was refused"
                )
            if entry.entry_type == "TX_ABORT":
                return None
        return None

    def _capability_descriptor(self, capability: str) -> dict[str, Any]:
        for descriptor in self.kernel.list_capabilities():
            if str(descriptor.get("name")) == capability:
                return dict(descriptor)
        raise CapabilityNotFoundError(f"unknown capability: {capability}")

    @classmethod
    def _validate_payload(cls, payload: Any, schema: Any) -> None:
        if not isinstance(payload, dict):
            raise SchemaValidationError("gateway payload must be an object")
        if not isinstance(schema, Mapping):
            return
        if schema.get("type") == "object":
            for key in schema.get("required", ()):
                if key not in payload:
                    raise SchemaValidationError(f"missing required payload field: {key}")
            properties = schema.get("properties", {})
            if isinstance(properties, Mapping):
                for key, value in payload.items():
                    declared = properties.get(key)
                    if isinstance(declared, Mapping):
                        cls._validate_type(value, declared.get("type"), key)

    @staticmethod
    def _validate_type(value: Any, expected: Any, field_name: str) -> None:
        if expected is None:
            return
        mapping = {
            "string": str,
            "object": dict,
            "array": list,
            "boolean": bool,
            "integer": int,
            "number": (int, float),
        }
        python_type = mapping.get(str(expected))
        if python_type is not None and not isinstance(value, python_type):
            raise SchemaValidationError(f"payload field {field_name!r} must be {expected}")

    def close(self) -> None:
        self.idempotency_store.close()
