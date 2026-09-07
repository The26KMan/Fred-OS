"""Authoritative runtime StateCapsule persistence and Temporal Sphere hydration."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable, Mapping

from .contracts import canonical_logical_hash, normalize_for_hash


class StateStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StateCapsule:
    capsule_id: str
    sequence: int
    parent_capsule_id: str | None
    command_id: str
    session_id: str
    config_hash: str
    temporal_state: dict[str, Any]
    memory_state: dict[str, Any]
    repository_state: dict[str, Any]
    receipt_hashes: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)
    host_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def logical_state_hash(self) -> str:
        return canonical_logical_hash({
            "session_id": self.session_id,
            "config_hash": self.config_hash,
            "temporal_state": self.temporal_state,
            "memory_state": self.memory_state,
            "repository_state": self.repository_state,
        })

    def to_dict(self) -> dict[str, Any]:
        return normalize_for_hash(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateCapsule":
        return cls(
            capsule_id=str(value["capsule_id"]),
            sequence=int(value["sequence"]),
            parent_capsule_id=value.get("parent_capsule_id"),
            command_id=str(value.get("command_id", "")),
            session_id=str(value["session_id"]),
            config_hash=str(value["config_hash"]),
            temporal_state=dict(value.get("temporal_state", {})),
            memory_state=dict(value.get("memory_state", {})),
            repository_state=dict(value.get("repository_state", {})),
            receipt_hashes=tuple(str(item) for item in value.get("receipt_hashes", ())),
            created_at=float(value.get("created_at", 0.0)),
            host_metadata=dict(value.get("host_metadata", {})),
        )

    def to_normalized_dict(self, exclude_keys: Iterable[str] = ()) -> dict[str, Any]:
        excluded = set(exclude_keys)
        return {key: value for key, value in self.to_dict().items() if key not in excluded}

    @classmethod
    def genesis(
        cls,
        *,
        session_id: str,
        config_hash: str,
        temporal_state: dict[str, Any],
        memory_state: dict[str, Any],
        repository_state: dict[str, Any],
    ) -> "StateCapsule":
        identity = canonical_logical_hash({
            "kind": "GENESIS",
            "session_id": session_id,
            "config_hash": config_hash,
            "temporal_state": temporal_state,
            "memory_state": memory_state,
            "repository_state": repository_state,
        })
        return cls(
            capsule_id=f"capsule-{identity[:20]}",
            sequence=0,
            parent_capsule_id=None,
            command_id="GENESIS",
            session_id=session_id,
            config_hash=config_hash,
            temporal_state=temporal_state,
            memory_state=memory_state,
            repository_state=repository_state,
        )

    @classmethod
    def next(
        cls,
        *,
        previous: "StateCapsule",
        command_id: str,
        temporal_state: dict[str, Any],
        memory_state: dict[str, Any],
        repository_state: dict[str, Any],
        receipt_hashes: tuple[str, ...],
    ) -> "StateCapsule":
        sequence = previous.sequence + 1
        logical = {
            "parent_capsule_id": previous.capsule_id,
            "sequence": sequence,
            "command_id": command_id,
            "session_id": previous.session_id,
            "config_hash": previous.config_hash,
            "temporal_state": temporal_state,
            "memory_state": memory_state,
            "repository_state": repository_state,
            "receipt_hashes": receipt_hashes,
        }
        identity = canonical_logical_hash(logical)
        return cls(
            capsule_id=f"capsule-{identity[:20]}",
            sequence=sequence,
            parent_capsule_id=previous.capsule_id,
            command_id=command_id,
            session_id=previous.session_id,
            config_hash=previous.config_hash,
            temporal_state=temporal_state,
            memory_state=memory_state,
            repository_state=repository_state,
            receipt_hashes=receipt_hashes,
        )


class StateStore:
    """Append-only capsule store. Journal commit markers decide authority."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, capsule: StateCapsule) -> None:
        record = json.dumps(capsule.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def all(self) -> list[StateCapsule]:
        if not self.path.exists():
            return []
        capsules: list[StateCapsule] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    capsules.append(StateCapsule.from_dict(json.loads(text)))
                except Exception as exc:
                    raise StateStoreError(f"Invalid StateCapsule record at line {line_number}: {exc}") from exc
        return capsules

    def get(self, capsule_id: str) -> StateCapsule | None:
        for capsule in reversed(self.all()):
            if capsule.capsule_id == capsule_id:
                return capsule
        return None

    def latest_committed(self, committed_capsule_ids: set[str]) -> StateCapsule | None:
        candidates = [capsule for capsule in self.all() if capsule.capsule_id in committed_capsule_ids]
        return max(candidates, key=lambda item: item.sequence) if candidates else None


def capture_temporal_state(temporal: Any) -> dict[str, Any]:
    """Capture public TSC state plus private deterministic continuation state."""
    snapshot = dict(temporal.snapshot())
    snapshot["_runtime"] = {
        "uncertainty_history": list(getattr(temporal, "_uncertainty_history", ())),
        "signature_evidence": {
            str(signature): [asdict(shard) for shard in shards]
            for signature, shards in getattr(temporal, "_signature_evidence", {}).items()
        },
    }
    return snapshot


def hydrate_temporal_state(snapshot: Mapping[str, Any], config: Any) -> Any:
    """Reconstruct a TemporalSphere without requiring model-internal persistence."""
    from fred_os.temporal.temporal_sphere import ContextSegment, EpisodicPattern, TemporalShard, TemporalSphere

    temporal = TemporalSphere(config)
    temporal.session_id = str(snapshot.get("session_id", temporal.session_id))
    temporal.current_turn = int(snapshot.get("current_turn", 0))
    temporal.working_memory = deque(
        (TemporalShard(**dict(item)) for item in snapshot.get("working_memory", ())),
        maxlen=config.working_capacity,
    )
    temporal.micro_segments = [ContextSegment(**dict(item)) for item in snapshot.get("micro_segments", ())]
    temporal.meso_segments = [ContextSegment(**dict(item)) for item in snapshot.get("meso_segments", ())]
    temporal.episodic_patterns = [EpisodicPattern(**dict(item)) for item in snapshot.get("episodic_patterns", ())]
    temporal.commitments = {str(key): dict(value) for key, value in dict(snapshot.get("commitments", {})).items()}

    runtime = dict(snapshot.get("_runtime", {}))
    uncertainty = runtime.get("uncertainty_history")
    if uncertainty is None:
        uncertainty = [shard.uncertainty for shard in temporal.working_memory]
    temporal._uncertainty_history = deque((float(item) for item in uncertainty), maxlen=20)

    evidence = runtime.get("signature_evidence", {})
    if evidence:
        temporal._signature_evidence = {
            str(signature): [TemporalShard(**dict(item)) for item in shards]
            for signature, shards in dict(evidence).items()
        }
    else:
        temporal._signature_evidence = {}
        for shard in temporal.working_memory:
            signature = "|".join(sorted(set(shard.objectives + shard.temporal_state.split()))) or "state"
            temporal._signature_evidence.setdefault(signature, []).append(shard)
    return temporal
