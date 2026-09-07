"""Pure MCP <-> M1 gateway translation helpers.

This module owns protocol-shape conversion only. It does not route, govern,
select Systems, or mutate runtime state.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping
import uuid

from fred_os.gateway import GatewayRequest, GatewayResponse


def derive_idempotency_key(tool_call_id: str | None) -> str:
    """Map a host/MCP request identity to the M1 idempotency boundary.

    A request identifier is preferred because intentionally repeated calls may
    have identical arguments. If a non-conforming host provides no request id,
    create a fresh key rather than accidentally deduplicating legitimate work.
    """
    if tool_call_id:
        return f"mcp:{tool_call_id}"
    return f"mcp:anonymous:{uuid.uuid4().hex}"


def mcp_call_to_gateway_request(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    token: str,
    tool_call_id: str | None = None,
    session_id: str | None = None,
) -> GatewayRequest:
    """Translate one MCP tool call into the canonical M1 request."""
    return GatewayRequest(
        target_capability=tool_name,
        payload=dict(arguments),
        idempotency_key=derive_idempotency_key(tool_call_id),
        token=token,
        session_id=session_id,
    )


def _receipt_proofs(response: GatewayResponse) -> list[dict[str, Any]]:
    return [
        {
            "receipt_id": receipt.receipt_id,
            "sequence": receipt.sequence,
            "component": receipt.component,
            "action": receipt.action,
            "status": receipt.status,
            "proof_hash": receipt.compute_hash(),
            "parent_receipt_id": receipt.parent_receipt_id,
        }
        for receipt in response.result.receipts
    ]


def _delta_summary(response: GatewayResponse) -> dict[str, Any] | None:
    delta = response.result.delta
    if delta is None:
        return None
    return {
        "delta_id": delta.delta_id,
        "prev_capsule_id": delta.prev_capsule_id,
        "next_capsule_id": delta.next_capsule_id,
        "before_state_hash": delta.before_state_hash,
        "after_state_hash": delta.after_state_hash,
        "tsc_mutation_keys": sorted(delta.tsc_mutations),
        "memory_mutation_keys": sorted(delta.memory_mutations),
        "repository_mutation_keys": sorted(delta.repository_mutations),
    }


def format_gateway_response_for_mcp(response: GatewayResponse) -> dict[str, Any]:
    """Return a context-bounded forensic projection of CommandResult.

    Full internal graphs, embeddings, thermal values, and temporal micro-state are
    intentionally not transported. The host receives proof identifiers, state
    transition hashes, the explicit rejection taxonomy, and a compact response.
    """
    outputs = response.result.outputs
    rejection = outputs.get("rejection") if isinstance(outputs, Mapping) else None
    ambiguity: Any = None
    s1 = outputs.get("s1") if isinstance(outputs, Mapping) else None
    if isinstance(s1, Mapping):
        ambiguity = s1.get("ambiguity") or s1.get("ambiguities")

    payload: dict[str, Any] = {
        "status": response.result.status,
        "caller_id": response.caller_id,
        "replayed": response.replayed,
        "command_id": response.result.command_id,
        "state_capsule_id": response.result.state_capsule_id,
        "receipts": _receipt_proofs(response),
        "state_delta": _delta_summary(response),
    }
    if isinstance(rejection, Mapping):
        payload["rejection"] = dict(rejection)
    if ambiguity:
        payload["ambiguity"] = ambiguity
    if isinstance(outputs, Mapping):
        for key in ("response", "route", "capability_assessment", "task_competency"):
            if key in outputs:
                value = outputs[key]
                if hasattr(value, "__dataclass_fields__"):
                    value = asdict(value)
                payload[key] = value
    return payload
