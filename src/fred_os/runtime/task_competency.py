"""Task–Competency Orchestration Layer for the vNext migration slice."""
from __future__ import annotations

import re
from typing import Any, Mapping

from .config import RuntimeConfig
from .routing import Route


class TaskCompetencyOrchestrator:
    """Convert task state and provider evidence into an execution authorization.

    The layer preserves the Task Understanding → Competency Mapping →
    Integration/Synthesis pattern as explicit, config-driven runtime data. It never
    invokes providers and never overrides the kernel GovernanceLayer.
    """

    _SYSTEM_ID = re.compile(r"\bS(?:1[0-3]|[1-9])\b")

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def _configured_terms(self, name: str) -> tuple[str, ...]:
        return tuple(str(term).lower() for term in self.config.get(f"task_competency.{name}", ()))

    def _match_terms(self, text: str, name: str) -> list[str]:
        return [term for term in self._configured_terms(name) if term in text]

    def analyze_task(
        self,
        raw_input: str,
        s1_state: Mapping[str, Any],
        governance_verdict: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = raw_input.lower()
        task_class = str(s1_state.get("task_class", "general"))
        uncertainty_value = s1_state.get("uncertainty", 0.0)
        if isinstance(uncertainty_value, Mapping):
            uncertainty_value = uncertainty_value.get("score", 0.0)
        uncertainty = min(1.0, max(0.0, float(uncertainty_value)))
        objectives = self._match_terms(normalized, "objective_terms")
        constraints = self._match_terms(normalized, "constraint_terms")
        explicit_systems = sorted(set(self._SYSTEM_ID.findall(raw_input)))
        required_classes = set(self.config.get("task_competency.objective_required_task_classes", ()))
        gaps: list[str] = []
        if task_class in required_classes and not objectives:
            gaps.append("objective_not_detected")

        context_graph = s1_state.get("context_graph", {})
        ambiguities = context_graph.get("ambiguities", ()) if isinstance(context_graph, Mapping) else ()
        if ambiguities:
            gaps.append("contradictory_constraints")

        threshold = float(self.config.get("task_competency.uncertainty_review_threshold", 1.0))
        review_reasons: list[str] = []
        if str(governance_verdict["decision"]) == "REVIEW":
            review_reasons.append("governance_review_route")
        if uncertainty >= threshold:
            review_reasons.append("high_uncertainty")
        if ambiguities:
            review_reasons.append("structured_ambiguity")

        return {
            "task_class": task_class,
            "objectives": objectives,
            "constraints": constraints,
            "explicit_systems": explicit_systems,
            "uncertainty": uncertainty,
            "requires_review": bool(review_reasons),
            "review_reasons": review_reasons,
            "ambiguities": list(ambiguities),
            "gaps": list(dict.fromkeys(gaps)),
        }

    def map_competencies(
        self,
        route: Route,
        capability_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        route_key = getattr(route, "key", route.name)
        competencies = self.config.get(f"task_competency.route_competencies.{route_key}", ())
        providers_by_competency = self.config.get("task_competency.competency_providers", {})
        statuses = capability_report["systems"]
        resolutions: list[dict[str, Any]] = []
        missing_required: list[str] = []
        missing_hard_gates: list[str] = []

        for competency in competencies:
            providers = tuple(str(provider) for provider in providers_by_competency.get(str(competency), ()))
            hard_gate = any(provider in getattr(route, "hard_gate_systems", ()) for provider in providers)
            selected: list[str] = []
            for provider in providers:
                status = statuses.get(provider)
                if not status:
                    continue
                readiness_key = "hard_gate_ready" if hard_gate else "execution_ready"
                if status[readiness_key]:
                    selected.append(provider)
            resolution = {
                "competency": str(competency),
                "providers": list(providers),
                "selected_providers": selected,
                "hard_gate": hard_gate,
                "status": "READY" if selected else "GAP",
            }
            resolutions.append(resolution)
            if not selected:
                (missing_hard_gates if hard_gate else missing_required).append(str(competency))

        return {
            "route_key": route_key,
            "resolutions": resolutions,
            "missing_required": missing_required,
            "missing_hard_gates": missing_hard_gates,
        }

    @staticmethod
    def authorize(
        task_contract: Mapping[str, Any],
        competency_map: Mapping[str, Any],
        governance_verdict: Mapping[str, Any],
    ) -> dict[str, Any]:
        if str(governance_verdict["decision"]) == "BLOCK":
            return {"status": "BLOCKED", "reason": "governance_block", "gaps": []}
        if competency_map["missing_hard_gates"]:
            return {
                "status": "BLOCKED",
                "reason": "hard_gate_competency_gap",
                "gaps": list(competency_map["missing_hard_gates"]),
            }
        if competency_map["missing_required"]:
            return {
                "status": "BLOCKED",
                "reason": "required_competency_gap",
                "gaps": list(competency_map["missing_required"]),
            }
        if task_contract["gaps"]:
            return {
                "status": "REVIEW",
                "reason": "task_contract_incomplete",
                "gaps": list(task_contract["gaps"]),
            }

        review_reasons = set(task_contract.get("review_reasons", ()))
        execution_barriers = review_reasons - {"governance_review_route"}
        if execution_barriers:
            return {
                "status": "REVIEW",
                "reason": "uncertainty_or_ambiguity_review",
                "gaps": sorted(execution_barriers),
            }
        return {"status": "AUTHORIZED", "reason": "required_competencies_resolved", "gaps": []}

    def assess(
        self,
        raw_input: str,
        s1_state: Mapping[str, Any],
        governance_verdict: Mapping[str, Any],
        route: Route,
        capability_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        task_contract = self.analyze_task(raw_input, s1_state, governance_verdict)
        competency_map = self.map_competencies(route, capability_report)
        authorization = self.authorize(task_contract, competency_map, governance_verdict)
        return {
            "task_contract": task_contract,
            "competency_map": competency_map,
            "execution_authorization": authorization,
            "audit_receipt": {
                "event": "TCOL_ASSESSED",
                "route_key": getattr(route, "key", route.name),
                "route_name": route.name,
                "requested_systems": list(route.systems),
                "hard_gate_systems": list(getattr(route, "hard_gate_systems", ())),
                "authorization_status": authorization["status"],
            },
        }
