"""Bootable owner of the explicit FRED OS vNext transactional runtime graph."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import time
from typing import Any, Callable
import uuid

from .config import ConfigLoader, RuntimeConfig
from .contracts import (
    CommandEnvelope,
    CommandResult,
    ExecutionReceipt,
    StateDelta,
    canonical_hash,
    normalize_for_hash,
)
from .governance import GovernanceLayer
from .journal import RuntimeJournal
from .observability import ObservabilityStack
from .registry import SystemRegistry
from .routing import Router
from .state import StateCapsule, StateStore, capture_temporal_state, hydrate_temporal_state
from fred_os.semantic_memory import SemanticMemoryLake
from fred_os.systems.adapters import default_plugins
from fred_os.temporal import TemporalSphere, TemporalSphereConfig


@dataclass
class RuntimeKernel:
    config: RuntimeConfig
    governance: GovernanceLayer
    observability: ObservabilityStack
    memory: SemanticMemoryLake
    temporal: TemporalSphere
    registry: SystemRegistry
    router: Router
    state_store: StateStore
    journal: RuntimeJournal
    current_capsule: StateCapsule
    booted_at: float
    status: str = "READY"

    @classmethod
    def boot(
        cls,
        *,
        root_dir: str | Path = ".",
        profile: str = "development",
        state_store_path: str | Path | None = None,
        journal_path: str | Path | None = None,
        session_id: str | None = None,
    ) -> "RuntimeKernel":
        root = Path(root_dir).resolve()
        config = ConfigLoader.build(root_dir=root, profile=profile)
        governance = GovernanceLayer(config)
        observability = ObservabilityStack(config)
        observability.emit("GLOBAL_INIT_OK", {"profile": profile, "config_hash": config.config_hash})

        memory = SemanticMemoryLake(
            config.resolve_path("memory.repository_path"),
            str(config.get("meta.tenant_id")),
            str(config.get("meta.project_id")),
        )
        observability.emit("MEMORY_READY", {})

        configured_state = config.get("runtime.state_store_path", "data/runtime_state.jsonl")
        configured_journal = config.get("runtime.journal_path", "data/runtime.wal.jsonl")
        state_store = StateStore(state_store_path or (root / str(configured_state)))
        journal = RuntimeJournal(journal_path or (root / str(configured_journal)))

        temporal_config = TemporalSphereConfig.from_runtime(config)
        committed_ids = journal.committed_capsule_ids()
        latest = state_store.latest_committed(committed_ids)
        if latest is not None:
            if latest.config_hash != config.config_hash:
                memory.close()
                raise RuntimeError(
                    f"Committed StateCapsule config hash {latest.config_hash} does not match active config {config.config_hash}"
                )
            if session_id is not None and latest.session_id != session_id:
                memory.close()
                raise RuntimeError(
                    f"Requested session {session_id} does not match committed runtime session {latest.session_id}"
                )
            temporal = hydrate_temporal_state(latest.temporal_state, temporal_config)
            current_capsule = latest
            observability.emit(
                "STATE_HYDRATED",
                {"capsule_id": latest.capsule_id, "sequence": latest.sequence, "session_id": latest.session_id},
            )
        else:
            temporal = TemporalSphere(temporal_config)
            if session_id is not None:
                temporal.session_id = session_id
            current_capsule = StateCapsule.genesis(
                session_id=temporal.session_id,
                config_hash=config.config_hash,
                temporal_state=capture_temporal_state(temporal),
                memory_state=cls._memory_state(config),
                repository_state=cls._repository_state(config),
            )
            state_store.append(current_capsule)
            journal.append_entry(
                "GENESIS_COMMIT",
                {
                    "capsule_id": current_capsule.capsule_id,
                    "sequence": current_capsule.sequence,
                    "logical_state_hash": current_capsule.logical_state_hash,
                },
            )
            observability.emit(
                "STATE_GENESIS",
                {"capsule_id": current_capsule.capsule_id, "session_id": current_capsule.session_id},
            )

        observability.emit("TEMPORAL_READY", {"session_id": temporal.session_id, "turn": temporal.current_turn})
        registry = SystemRegistry(config)
        for plugin in default_plugins():
            registry.register(plugin)
        order = registry.resolve()
        registry.instantiate()
        checks = registry.health_check_all()
        router = Router(config)

        kernel = cls(
            config=config,
            governance=governance,
            observability=observability,
            memory=memory,
            temporal=temporal,
            registry=registry,
            router=router,
            state_store=state_store,
            journal=journal,
            current_capsule=current_capsule,
            booted_at=time.time(),
            status="READY",
        )
        kernel.reconcile_wal()
        kernel.reconcile_committed_derivations()
        observability.emit(
            "SYSTEM_READY",
            {"systems": len(checks), "boot_order": order, "capsule_id": current_capsule.capsule_id},
        )
        return kernel

    @staticmethod
    def _memory_state(config: RuntimeConfig) -> dict[str, Any]:
        return {
            "repository_path": str(config.get("memory.repository_path")),
            "tenant_id": str(config.get("meta.tenant_id")),
            "project_id": str(config.get("meta.project_id")),
        }

    @staticmethod
    def _repository_state(config: RuntimeConfig) -> dict[str, Any]:
        return {
            "engine": "sqlite_artifact_store",
            "repository_path": str(config.get("memory.repository_path")),
        }

    def get_current_capsule(self) -> StateCapsule:
        return self.current_capsule

    def list_capabilities(self) -> tuple[dict[str, Any], ...]:
        return (
            {
                "name": "runtime.process_turn",
                "version": "0.1.0",
                "description": "Route one governed FRED OS turn through S1 and configured downstream Systems.",
                "required_permissions": (),
                "input_schema": {"type": "object", "required": ["input"], "properties": {"input": {"type": "string"}}},
            },
            {
                "name": "s1.cognitive_map",
                "version": "0.1.0",
                "description": "Invoke the transactional turn path with System-1 cognitive mapping as the routing anchor.",
                "required_permissions": (),
                "input_schema": {"type": "object", "required": ["input"], "properties": {"input": {"type": "string"}}},
            },
        )

    def process_turn(self, raw_input: str) -> dict[str, Any]:
        """Compatibility surface; the authoritative execution path is transactional dispatch()."""
        command_id = f"cmd-{uuid.uuid4().hex}"
        result = self.dispatch(
            CommandEnvelope(
                command_id=command_id,
                target_capability="runtime.process_turn",
                payload={"input": raw_input},
                session_id=self.current_capsule.session_id,
                idempotency_key=command_id,
            )
        )
        return result.outputs

    def dispatch(self, envelope: CommandEnvelope) -> CommandResult:
        if self.status != "READY":
            raise RuntimeError(f"RuntimeKernel is not READY: {self.status}")
        if envelope.session_id != self.current_capsule.session_id:
            raise ValueError(
                f"Command session {envelope.session_id} does not match runtime session {self.current_capsule.session_id}"
            )
        if envelope.target_capability not in {"runtime.process_turn", "s1.cognitive_map"}:
            raise ValueError(f"Unsupported capability: {envelope.target_capability}")

        raw_input = str(envelope.payload.get("input", envelope.payload.get("text", "")))
        before = self.current_capsule
        self.journal.append_entry(
            "TX_START",
            {
                "command_id": envelope.command_id,
                "idempotency_key": envelope.idempotency_key,
                "target_capability": envelope.target_capability,
                "before_capsule_id": before.capsule_id,
                "command_hash": canonical_hash(envelope),
            },
        )

        try:
            outputs, receipts = self._execute_turn(raw_input, envelope.command_id)
            temporal_state = capture_temporal_state(self.temporal)
            receipt_hashes = tuple(receipt.compute_hash() for receipt in receipts)
            candidate = StateCapsule.next(
                previous=before,
                command_id=envelope.command_id,
                temporal_state=temporal_state,
                memory_state=self._memory_state(self.config),
                repository_state=self._repository_state(self.config),
                receipt_hashes=receipt_hashes,
            )
            delta = self._build_delta(before, candidate, envelope.command_id, outputs)
            self.journal.append_entry("STATE_DELTA", normalize_for_hash(asdict(delta)))

            # Candidate first, commit marker second. A crash between these writes leaves
            # a non-authoritative capsule that boot() will ignore.
            self.state_store.append(candidate)
            self.journal.append_entry(
                "TX_COMMIT",
                {
                    "command_id": envelope.command_id,
                    "idempotency_key": envelope.idempotency_key,
                    "capsule_id": candidate.capsule_id,
                    "capsule_sequence": candidate.sequence,
                    "delta_id": delta.delta_id,
                    "receipt_hashes": list(receipt_hashes),
                    "logical_state_hash": candidate.logical_state_hash,
                },
            )
            self.current_capsule = candidate

            # DeepLink↔TSC rows are a rebuildable materialized index derived from the
            # committed capsule. They are synchronized only after TX_COMMIT and are
            # reconciled again during boot if a crash interrupts this post-commit step.
            linked = self.reconcile_committed_derivations()
            temporal_receipt = outputs.get("temporal")
            if isinstance(temporal_receipt, dict):
                shard_id = str(temporal_receipt.get("shard_id", ""))
                temporal_receipt["linked_sources"] = linked.get(shard_id, [])

            status = "REJECTED" if outputs.get("verdict") and getattr(outputs["verdict"], "decision", "") == "BLOCK" else "SUCCESS"
            self.observability.emit(
                "TX_COMMITTED",
                {
                    "command_id": envelope.command_id,
                    "capsule_id": candidate.capsule_id,
                    "sequence": candidate.sequence,
                    "receipt_count": len(receipts),
                },
            )
            return CommandResult(
                command_id=envelope.command_id,
                status=status,
                outputs=outputs,
                receipts=tuple(receipts),
                delta=delta,
                state_capsule_id=candidate.capsule_id,
            )
        except Exception as exc:
            self.temporal = hydrate_temporal_state(before.temporal_state, TemporalSphereConfig.from_runtime(self.config))
            self.journal.append_entry(
                "TX_ABORT",
                {"command_id": envelope.command_id, "before_capsule_id": before.capsule_id, "error": repr(exc)},
            )
            self.observability.emit("TX_ABORTED", {"command_id": envelope.command_id, "error": repr(exc)})
            raise

    def _execute_turn(self, raw_input: str, command_id: str) -> tuple[dict[str, Any], list[ExecutionReceipt]]:
        receipts: list[ExecutionReceipt] = []

        def execute(component: str, action: str, inputs: Any, function: Callable[[], Any]) -> Any:
            started = time.perf_counter()
            parent = receipts[-1].receipt_id if receipts else None
            try:
                output = function()
            except Exception as exc:
                receipts.append(
                    ExecutionReceipt.create(
                        command_id=command_id,
                        sequence=len(receipts) + 1,
                        component=component,
                        action=action,
                        inputs=inputs,
                        outputs={"error": repr(exc)},
                        execution_time_ms=(time.perf_counter() - started) * 1000.0,
                        status="ERROR",
                        parent_receipt_id=parent,
                    )
                )
                raise
            receipts.append(
                ExecutionReceipt.create(
                    command_id=command_id,
                    sequence=len(receipts) + 1,
                    component=component,
                    action=action,
                    inputs=inputs,
                    outputs=output,
                    execution_time_ms=(time.perf_counter() - started) * 1000.0,
                    status="OK",
                    parent_receipt_id=parent,
                )
            )
            return output

        verdict = execute("Governance", "pre_scan", {"input": raw_input}, lambda: self.governance.pre_scan(raw_input))
        if verdict.decision == "BLOCK":
            self.observability.emit("GOVERNANCE_BLOCK", {"reason": verdict.rationale})
            return {"verdict": verdict, "response": "The runtime blocked this request for safe handling."}, receipts

        s1 = execute(
            "S1",
            "cognitive_map",
            {"text": raw_input, "temporal_turn": self.temporal.current_turn},
            lambda: self.registry.get("S1").process(
                {"text": raw_input},
                {"memory": self.memory, "temporal": self.temporal, "governance": verdict},
            ),
        )

        # S1 currently owns retrieval calls internally. This receipt exposes the
        # Memory Lake evidence actually returned without pretending it was a second recall.
        memory_context = list(s1.get("memory_context", []))
        receipts.append(
            ExecutionReceipt.create(
                command_id=command_id,
                sequence=len(receipts) + 1,
                component="MemoryLake",
                action="recall_context_observed_by_s1",
                inputs={"query": raw_input},
                outputs=memory_context,
                execution_time_ms=0.0,
                status="OK",
                parent_receipt_id=receipts[-1].receipt_id if receipts else None,
            )
        )

        route = execute(
            "Router",
            "choose_route",
            {"task_class": s1["task_class"], "governance": verdict.decision},
            lambda: self.router.choose(s1["task_class"], verdict.decision),
        )
        context = {"s1": s1, "governance": verdict, "temporal": self.temporal, "memory": self.memory}
        outputs: dict[str, Any] = {"S1": s1}
        for system_id in route.systems:
            if system_id in {"S1", "S8"} or system_id not in self.config.get("systems.enabled"):
                continue
            value = execute(
                system_id,
                "process",
                {"text": raw_input, "route": route.name},
                lambda system_id=system_id: self.registry.get(system_id).process({"text": raw_input}, context),
            )
            outputs[system_id] = value
            context[system_id.lower()] = value

        shard = execute(
            "TSC",
            "record_turn",
            {"text": raw_input, "systems": list(outputs)},
            lambda: self.temporal.record_turn(raw_input, s1, outputs),
        )
        temporal_receipt = {
            "shard_id": shard.shard_id,
            "turn": shard.turn,
            "source_deeplinks": list(shard.source_deeplinks),
            "linked_sources": [],
            "temporal_entropy": self.temporal.temporal_entropy(),
            "coherence": self.temporal.coherence(),
            "projections": self.temporal.project_next_steps(raw_input),
        }
        self.observability.emit(
            "TURN_COMPLETED",
            {
                "route": route.name,
                "systems": list(outputs),
                "s1_recall_hits": len(memory_context),
                "tsc_shard_id": shard.shard_id,
                "linked_sources": 0,
            },
        )
        return {"verdict": verdict, "route": route, "outputs": outputs, "temporal": temporal_receipt}, receipts

    def _build_delta(
        self,
        before: StateCapsule,
        after: StateCapsule,
        command_id: str,
        outputs: dict[str, Any],
    ) -> StateDelta:
        before_tsc = before.temporal_state
        after_tsc = after.temporal_state
        before_shards = {str(item.get("shard_id")) for item in before_tsc.get("working_memory", ())}
        after_shards = {str(item.get("shard_id")) for item in after_tsc.get("working_memory", ())}
        before_commitments = set(dict(before_tsc.get("commitments", {})))
        after_commitments = set(dict(after_tsc.get("commitments", {})))
        temporal_receipt = outputs.get("temporal", {}) if isinstance(outputs.get("temporal"), dict) else {}
        source_deeplinks = list(temporal_receipt.get("source_deeplinks", ()))
        tsc_mutations = {
            "current_turn": {"before": int(before_tsc.get("current_turn", 0)), "after": int(after_tsc.get("current_turn", 0))},
            "added_shard_ids": sorted(after_shards - before_shards),
            "added_commitment_keys": sorted(after_commitments - before_commitments),
        }
        memory_mutations = {
            "materialized_link_sources": source_deeplinks,
            "authority": "derived_from_committed_tsc_shard",
        }
        repository_mutations = {
            "semantic_artifacts": "unchanged",
            "derived_temporal_link_count": len(source_deeplinks),
        }
        body = {
            "command_id": command_id,
            "tsc_mutations": tsc_mutations,
            "memory_mutations": memory_mutations,
            "repository_mutations": repository_mutations,
            "prev_capsule_id": before.capsule_id,
            "next_capsule_id": after.capsule_id,
            "before_state_hash": before.logical_state_hash,
            "after_state_hash": after.logical_state_hash,
        }
        return StateDelta(delta_id=f"delta-{canonical_hash(body)[:20]}", **body)

    def reconcile_wal(self) -> list[dict[str, Any]]:
        interrupted = self.journal.uncommitted_transactions()
        if interrupted:
            self.observability.emit(
                "WAL_UNCOMMITTED_IGNORED",
                {
                    "count": len(interrupted),
                    "commands": [item["command_id"] for item in interrupted],
                    "authoritative_capsule_id": self.current_capsule.capsule_id,
                },
            )
        return interrupted

    def reconcile_committed_derivations(self) -> dict[str, list[str]]:
        linked_by_shard: dict[str, list[str]] = {}
        for shard in self.current_capsule.temporal_state.get("working_memory", ()):
            shard_id = str(shard.get("shard_id", ""))
            if not shard_id:
                continue
            for deeplink in shard.get("source_deeplinks", ()):
                link = str(deeplink)
                if not link.startswith("deeplink://"):
                    continue
                if self.memory.link_tsc_shard(link, shard_id, relation="recall_context"):
                    linked_by_shard.setdefault(shard_id, []).append(link)
        return linked_by_shard

    def shutdown(self) -> None:
        if self.status == "CLOSED":
            return
        self.observability.emit(
            "RUNTIME_SHUTDOWN",
            {"capsule_id": self.current_capsule.capsule_id, "sequence": self.current_capsule.sequence},
        )
        self.memory.close()
        self.status = "CLOSED"

    def close(self) -> None:
        self.shutdown()
