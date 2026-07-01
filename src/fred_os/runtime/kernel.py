"""Bootable owner of the explicit Fred-OS vNext runtime graph."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ConfigLoader, RuntimeConfig
from .governance import GovernanceLayer, GovernanceVerdict
from .observability import ObservabilityStack
from .registry import SystemRegistry
from .routing import Route, Router
from fred_os.semantic_memory import SemanticMemoryLake
from fred_os.systems.adapters import default_plugins


@dataclass
class RuntimeKernel:
    config: RuntimeConfig
    governance: GovernanceLayer
    observability: ObservabilityStack
    memory: SemanticMemoryLake
    registry: SystemRegistry
    router: Router
    booted_at: float

    @classmethod
    def boot(cls, *, root_dir: str | Path = ".", profile: str = "development") -> "RuntimeKernel":
        root = Path(root_dir).resolve()
        config = ConfigLoader.build(root_dir=root, profile=profile)
        governance = GovernanceLayer(config)
        observability = ObservabilityStack(config)
        observability.emit("GLOBAL_INIT_OK", {"profile": profile})
        memory = SemanticMemoryLake(
            config.resolve_path("memory.repository_path"),
            str(config.get("meta.tenant_id")),
            str(config.get("meta.project_id")),
        )
        observability.emit("MEMORY_READY", {})
        registry = SystemRegistry(config)
        for plugin in default_plugins():
            registry.register(plugin)
        order = registry.resolve()
        registry.instantiate()
        checks = registry.health_check_all()
        router = Router(config)
        kernel = cls(config, governance, observability, memory, registry, router, time.time())
        observability.emit("SYSTEM_READY", {"systems": len(checks), "boot_order": order})
        return kernel

    def _capability_block(
        self,
        *,
        route: Route,
        governance_verdict: GovernanceVerdict,
        capability_report: dict[str, Any],
        outputs: dict[str, Any],
    ) -> dict[str, Any]:
        missing = capability_report["hard_gate_missing"] or capability_report["required_missing"]
        rationale = (
            f"Route '{route.name}' cannot execute because required System-OS capabilities "
            f"are unavailable or not implementation-ready: {', '.join(missing)}."
        )
        execution_verdict = GovernanceVerdict("BLOCK", rationale, 0.0)
        self.observability.emit(
            "CAPABILITY_GAP",
            {
                "route": route.name,
                "required_missing": capability_report["required_missing"],
                "hard_gate_missing": capability_report["hard_gate_missing"],
                "systems": capability_report["systems"],
            },
        )
        return {
            "verdict": execution_verdict,
            "governance_verdict": governance_verdict,
            "route": route,
            "capability_report": capability_report,
            "outputs": outputs,
            "response": "The runtime did not execute this route because its required governance capability is not ready.",
        }

    def _qesae_block(
        self,
        *,
        route: Route,
        governance_verdict: GovernanceVerdict,
        capability_report: dict[str, Any],
        outputs: dict[str, Any],
    ) -> dict[str, Any]:
        qesae_output = outputs.get("S13", {})
        verified = qesae_output.get("verified_ethical_decision")
        rationale = (
            "The QESAE hard gate denied execution because System-13 did not return an "
            "approved verified_ethical_decision with auditable rationale."
        )
        self.observability.emit(
            "QESAE_GATE_DENIED",
            {
                "route": route.name,
                "qesae_output": qesae_output,
                "required_contract": {
                    "verified_ethical_decision": {"approved": True, "rationale": "...", "audit_id": "..."}
                },
            },
        )
        return {
            "verdict": GovernanceVerdict("BLOCK", rationale, 0.0),
            "governance_verdict": governance_verdict,
            "route": route,
            "capability_report": capability_report,
            "outputs": outputs,
            "qesae_verification": verified,
            "response": "The runtime did not execute this high-stakes route because QESAE verification was incomplete.",
        }

    def process_turn(self, raw_input: str) -> dict[str, Any]:
        governance_verdict = self.governance.pre_scan(raw_input)
        if governance_verdict.decision == "BLOCK":
            self.observability.emit("GOVERNANCE_BLOCK", {"reason": governance_verdict.rationale})
            return {
                "verdict": governance_verdict,
                "response": "The runtime blocked this request for safe handling.",
            }

        s1 = self.registry.get("S1").process({"text": raw_input}, {})
        route = self.router.choose(s1["task_class"], governance_verdict.decision)
        outputs: dict[str, Any] = {"S1": s1}
        context: dict[str, Any] = {"s1": s1}
        capability_report = self.registry.assess_route(
            route.systems,
            route.hard_gate_systems,
            route.optional_systems,
        )
        if not capability_report["ready"]:
            return self._capability_block(
                route=route,
                governance_verdict=governance_verdict,
                capability_report=capability_report,
                outputs=outputs,
            )

        for system_id in route.systems:
            if system_id == "S1":
                continue
            if system_id == "S8":
                outputs["S8"] = {
                    "system_id": "S8",
                    "status": "kernel_governance_pre_scan",
                    "decision": governance_verdict.decision,
                    "rationale": governance_verdict.rationale,
                    "score": governance_verdict.score,
                }
                context["s8"] = outputs["S8"]
                continue
            output = self.registry.get(system_id).process({"text": raw_input}, context)
            outputs[system_id] = output
            context[system_id.lower()] = output

        for system_id in route.optional_systems:
            status = capability_report["systems"][system_id]
            if status["execution_ready"]:
                output = self.registry.get(system_id).process({"text": raw_input}, context)
                outputs[system_id] = output
                context[system_id.lower()] = output
            else:
                self.observability.emit(
                    "OPTIONAL_CAPABILITY_SKIPPED",
                    {"route": route.name, "system_id": system_id, "reasons": status["reasons"]},
                )

        if "S13" in route.hard_gate_systems:
            qesae = outputs.get("S13", {}).get("verified_ethical_decision", {})
            if not isinstance(qesae, dict) or qesae.get("approved") is not True:
                return self._qesae_block(
                    route=route,
                    governance_verdict=governance_verdict,
                    capability_report=capability_report,
                    outputs=outputs,
                )
            self.observability.emit(
                "QESAE_GATE_APPROVED",
                {"route": route.name, "audit_id": qesae.get("audit_id"), "rationale": qesae.get("rationale")},
            )

        self.observability.emit(
            "TURN_COMPLETED",
            {
                "route": route.name,
                "systems": list(outputs),
                "optional_unavailable": capability_report["optional_unavailable"],
            },
        )
        return {
            "verdict": governance_verdict,
            "route": route,
            "capability_report": capability_report,
            "outputs": outputs,
        }

    def close(self) -> None:
        self.memory.close()
