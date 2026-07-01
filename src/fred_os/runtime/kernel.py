"""Bootable owner of the explicit Fred-OS vNext runtime graph."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fred_os.semantic_memory import SemanticMemoryLake
from fred_os.systems.adapters import default_plugins
from .config import ConfigLoader, RuntimeConfig
from .governance import GovernanceLayer, GovernanceVerdict
from .observability import ObservabilityStack
from .registry import SystemRegistry
from .routing import Route, Router
from .task_competency import TaskCompetencyOrchestrator
from .task_planning import TaskCompetencyPlanner


@dataclass
class RuntimeKernel:
    config: RuntimeConfig
    governance: GovernanceLayer
    observability: ObservabilityStack
    memory: SemanticMemoryLake
    registry: SystemRegistry
    router: Router
    task_planner: TaskCompetencyPlanner
    task_competency: TaskCompetencyOrchestrator
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
        kernel = cls(
            config,
            governance,
            observability,
            memory,
            registry,
            Router(config),
            TaskCompetencyPlanner(config),
            TaskCompetencyOrchestrator(config),
            time.time(),
        )
        observability.emit("SYSTEM_READY", {"systems": len(checks), "boot_order": order})
        return kernel

    def _stop(
        self,
        route: Route,
        governance_verdict: GovernanceVerdict,
        capability_report: dict[str, Any],
        assessment: dict[str, Any],
        outputs: dict[str, Any],
    ) -> dict[str, Any]:
        competency_map = assessment["competency_map"]
        gaps = list(dict.fromkeys(
            list(competency_map["missing_hard_gates"])
            + list(competency_map["missing_required"])
            + list(capability_report["hard_gate_missing"])
            + list(capability_report["required_missing"])
        ))
        rationale = f"Route '{route.name}' has unresolved required capabilities: {', '.join(gaps)}."
        verdict = GovernanceVerdict("BLOCK", rationale, 0.0)
        self.observability.emit(
            "CAPABILITY_GAP",
            {
                "route": route.name,
                "route_key": route.key,
                "authorization": assessment["execution_authorization"],
                "capability_report": capability_report,
                "competency_map": competency_map,
            },
        )
        return {
            "verdict": verdict,
            "governance_verdict": governance_verdict,
            "route": route,
            "capability_report": capability_report,
            "task_competency": assessment,
            "outputs": outputs,
            "response": "Execution was stopped because declared required capabilities are not ready.",
        }

    def process_turn(self, raw_input: str) -> dict[str, Any]:
        governance_verdict = self.governance.pre_scan(raw_input)
        if governance_verdict.decision == "BLOCK":
            self.observability.emit("GOVERNANCE_BLOCK", {"reason": governance_verdict.rationale})
            return {"verdict": governance_verdict, "response": "The runtime blocked this request for safe handling."}

        s1 = self.registry.get("S1").process({"text": raw_input}, {})
        route = self.router.choose(s1["task_class"], governance_verdict.decision)
        capability_report = self.registry.assess_route(
            route.systems, route.hard_gate_systems, route.optional_systems
        )
        planning = self.task_planner.plan(
            raw_input=raw_input,
            s1_output=s1,
            governance_verdict=governance_verdict,
            route=route,
            capability_report=capability_report,
        )
        assessment = self.task_competency.assess(
            raw_input,
            s1,
            {
                "decision": governance_verdict.decision,
                "rationale": governance_verdict.rationale,
                "score": governance_verdict.score,
            },
            route,
            capability_report,
        )
        outputs: dict[str, Any] = {"S1": s1, "TASK_PLANNING": planning, "TASK_COMPETENCY": assessment}
        context: dict[str, Any] = {"s1": s1, "task_planning": planning, "task_competency": assessment}
        self.observability.emit("TASK_ANALYZED", planning["task_analysis"])
        self.observability.emit("TCOL_ASSESSED", assessment["audit_receipt"])
        if not capability_report["ready"] or assessment["execution_authorization"]["status"] == "BLOCKED":
            return self._stop(route, governance_verdict, capability_report, assessment, outputs)

        governance_system_id = str(self.config.get("governance.kernel_system_id"))
        for system_id in route.systems:
            if system_id == "S1":
                continue
            if system_id == governance_system_id:
                output = {
                    "system_id": governance_system_id,
                    "status": "kernel_governance_pre_scan",
                    "decision": governance_verdict.decision,
                    "rationale": governance_verdict.rationale,
                    "score": governance_verdict.score,
                }
            else:
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
            decision = outputs.get("S13", {}).get("verified_ethical_decision", {})
            if not isinstance(decision, dict) or decision.get("approved") is not True:
                assessment["execution_authorization"] = {
                    "status": "BLOCKED",
                    "reason": "qesae_verification_incomplete",
                    "gaps": ["ethical_adaptation"],
                }
                return self._stop(route, governance_verdict, capability_report, assessment, outputs)
            self.observability.emit("QESAE_GATE_APPROVED", {"route": route.name, "audit_id": decision.get("audit_id")})

        self.observability.emit(
            "TURN_COMPLETED",
            {
                "route": route.name,
                "route_key": route.key,
                "systems": list(outputs),
                "authorization": assessment["execution_authorization"]["status"],
            },
        )
        return {
            "verdict": governance_verdict,
            "route": route,
            "capability_report": capability_report,
            "task_competency": assessment,
            "outputs": outputs,
        }

    def close(self) -> None:
        self.memory.close()
