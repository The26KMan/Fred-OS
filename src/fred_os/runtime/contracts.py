"""Contracts shared by FRED OS runtime components and registered adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import time
from typing import Any, ClassVar, Mapping

from .config import RuntimeConfig


_LOGICAL_VOLATILE_KEYS = {"created_at", "execution_time_ms", "booted_at", "host_metadata"}


def normalize_for_hash(value: Any) -> Any:
    """Convert runtime values into a deterministic JSON-compatible structure."""
    if is_dataclass(value):
        return normalize_for_hash(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): normalize_for_hash(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [normalize_for_hash(item) for item in value]
    if isinstance(value, set):
        return sorted(normalize_for_hash(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict"):
        return normalize_for_hash(value.to_dict())
    return repr(value)


def normalize_for_logical_hash(value: Any) -> Any:
    """Normalize logical state while excluding runtime-only timing/host metadata."""
    if is_dataclass(value):
        return normalize_for_logical_hash(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): normalize_for_logical_hash(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _LOGICAL_VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [normalize_for_logical_hash(item) for item in value]
    if isinstance(value, set):
        return sorted(normalize_for_logical_hash(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict"):
        return normalize_for_logical_hash(value.to_dict())
    return repr(value)


def canonical_json(value: Any) -> str:
    return json.dumps(normalize_for_hash(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_logical_hash(value: Any) -> str:
    packed = json.dumps(
        normalize_for_logical_hash(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: str
    target_capability: str
    payload: dict[str, Any]
    session_id: str
    idempotency_key: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str
    version: str
    description: str
    required_permissions: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionReceipt:
    receipt_id: str
    command_id: str
    sequence: int
    component: str
    action: str
    inputs_hash: str
    outputs_hash: str
    execution_time_ms: float
    status: str
    parent_receipt_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        command_id: str,
        sequence: int,
        component: str,
        action: str,
        inputs: Any,
        outputs: Any,
        execution_time_ms: float,
        status: str = "OK",
        parent_receipt_id: str | None = None,
    ) -> "ExecutionReceipt":
        inputs_hash = canonical_logical_hash(inputs)
        outputs_hash = canonical_logical_hash(outputs)
        identity = canonical_logical_hash({
            "command_id": command_id,
            "sequence": sequence,
            "component": component,
            "action": action,
            "inputs_hash": inputs_hash,
            "outputs_hash": outputs_hash,
            "status": status,
            "parent_receipt_id": parent_receipt_id,
        })
        return cls(
            receipt_id=f"rcpt-{identity[:20]}",
            command_id=command_id,
            sequence=sequence,
            component=component,
            action=action,
            inputs_hash=inputs_hash,
            outputs_hash=outputs_hash,
            execution_time_ms=round(float(execution_time_ms), 4),
            status=status,
            parent_receipt_id=parent_receipt_id,
        )

    def compute_hash(self) -> str:
        """Hash logical receipt contents, excluding non-deterministic timing metadata."""
        return canonical_logical_hash({
            "receipt_id": self.receipt_id,
            "command_id": self.command_id,
            "sequence": self.sequence,
            "component": self.component,
            "action": self.action,
            "inputs_hash": self.inputs_hash,
            "outputs_hash": self.outputs_hash,
            "status": self.status,
            "parent_receipt_id": self.parent_receipt_id,
        })


@dataclass(frozen=True)
class StateDelta:
    delta_id: str
    command_id: str
    tsc_mutations: dict[str, Any]
    memory_mutations: dict[str, Any]
    repository_mutations: dict[str, Any]
    prev_capsule_id: str
    next_capsule_id: str
    before_state_hash: str
    after_state_hash: str


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    status: str
    outputs: dict[str, Any]
    receipts: tuple[ExecutionReceipt, ...]
    delta: StateDelta | None
    state_capsule_id: str


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    system_id: str
    reason: str = ""


class SystemPlugin(ABC):
    SYSTEM_ID: ClassVar[str]
    SYSTEM_NAME: ClassVar[str]
    HARD_DEPENDENCIES: ClassVar[tuple[str, ...]] = ()

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True

    def healthcheck(self) -> HealthResult:
        return HealthResult(self.initialized, self.SYSTEM_ID, "adapter initialized")

    @abstractmethod
    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
