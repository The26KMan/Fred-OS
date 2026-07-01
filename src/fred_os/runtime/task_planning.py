"""Inspectable Task Analysis and Competency Mapping for the vNext runtime.

This module preserves the useful intent of the legacy three-expert flow:
understand the task, map the capabilities it needs, and synthesize an executable
plan. It is deliberately deterministic and evidence-aware. It does not simulate
hidden specialists or claim that a declared adapter is implementation-ready.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .config import RuntimeConfig
from .governance import GovernanceVerdict
from .routing import Route


TemporalState = Literal["ask", "constrain", "state", "decide"]
EvidencePosture = Literal["none", "supporting", "strict"]
Criticality = Literal["required", "hard_gate", "optional"]


@dataclass(frozen=True)
class TaskFrame:
    """Normalized current-turn task representation for downstream routing."""

    intent: str
    task_class: str
    objective: str
    temporal_state: TemporalState
    constraints: tuple[str, ...]
    open_questions: tuple[str, ...]
    required_facets: tuple[str, ...]
    evidence_posture: EvidencePosture
    risk_tier: str
    complexity: int


@dataclass(frozen=True)
class CompetencyRequirement:
    """One declared capability requirement and its actual runtime availability."""

    competency: str
    system_id: str
    rationale: str
    criticality: Criticality
    available: bool
    maturity: str
    reasons: tuple[str, ...]


class TaskCompetencyPlanner:
    """Build a task frame, capability map, and execution preconditions.

    Routing remains configuration-led. The planner makes the reason for a selected
    route and any capability limitation inspectable before execution. Cue sets and
    thresholds are read from frozen ``task_planning`` configuration rather than
    hidden runtime defaults.
    """

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def plan(
        self,
        *,
        raw_input: str,
        s1_output: dict[str, Any],
        governance_verdict: GovernanceVerdict,
        route: Route,
        capability_report: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce a serialization-safe planning receipt for a single turn."""
        frame = self._analyze_task(raw_input, s1_output, governance_verdict)
        competencies = self._map_competencies(route, capability_report)
        return {
            "task_analysis": asdict(frame),
            "competency_map": [asdict(item) for item in competencies],
            "execution_plan": self._synthesize_execution(route, capability_report, competencies),
        }

    def _analyze_task(
        self,
        raw_input: str,
        s1_output: dict[str, Any],
        governance_verdict: GovernanceVerdict,
    ) -> TaskFrame:
        text = " ".join(raw_input.strip().split())
        lowered = text.lower()
        task_class = str(s1_output.get("task_class", "general"))
        intent = self._intent(lowered)
        constraints = self._constraints(text)
        temporal_state = self._temporal_state(text, constraints)
        evidence_posture = self._evidence_posture(lowered, task_class, governance_verdict)
        open_questions = self._open_questions(text, intent, governance_verdict, evidence_posture)
        required_facets = self._required_facets(lowered, constraints, evidence_posture)
        complexity = self._complexity(lowered, task_class, constraints, governance_verdict)
        risk_tier = "high" if governance_verdict.decision == "REVIEW" else "standard"
        return TaskFrame(
            intent=intent,
            task_class=task_class,
            objective=self._objective(text),
            temporal_state=temporal_state,
            constraints=constraints,
            open_questions=open_questions,
            required_facets=required_facets,
            evidence_posture=evidence_posture,
            risk_tier=risk_tier,
            complexity=complexity,
        )

    def _map_competencies(
        self,
        route: Route,
        capability_report: dict[str, Any],
    ) -> tuple[CompetencyRequirement, ...]:
        requirements: list[tuple[str, str, str, Criticality]] = [
            ("contextual_mapping", "S1", "Build the current-turn situation and task frame.", "required"),
        ]
        for system_id in route.systems:
            if system_id != "S1":
                requirements.append(
                    self._system_requirement(
                        system_id,
                        "hard_gate" if system_id in route.hard_gate_systems else "required",
                    )
                )
        for system_id in route.optional_systems:
            requirements.append(self._system_requirement(system_id, "optional"))

        seen: set[tuple[str, str]] = set()
        mapped: list[CompetencyRequirement] = []
        for competency, system_id, rationale, criticality in requirements:
            key = (competency, system_id)
            if key in seen:
                continue
            seen.add(key)
            status = capability_report.get("systems", {}).get(system_id, {})
            readiness_key = "hard_gate_ready" if criticality == "hard_gate" else "execution_ready"
            mapped.append(
                CompetencyRequirement(
                    competency=competency,
                    system_id=system_id,
                    rationale=rationale,
                    criticality=criticality,
                    available=bool(status.get(readiness_key, False)),
                    maturity=str(status.get("maturity", "undeclared")),
                    reasons=tuple(status.get("reasons", ())),
                )
            )
        return tuple(mapped)

    @staticmethod
    def _synthesize_execution(
        route: Route,
        capability_report: dict[str, Any],
        competencies: tuple[CompetencyRequirement, ...],
    ) -> dict[str, Any]:
        blocked = list(capability_report.get("hard_gate_missing", ())) + list(
            capability_report.get("required_missing", ())
        )
        optional = list(capability_report.get("optional_unavailable", ()))
        disposition = "blocked" if blocked else "ready_with_optional_gaps" if optional else "ready"
        return {
            "route": route.name,
            "reason": route.reason,
            "disposition": disposition,
            "required_systems": list(route.systems),
            "hard_gate_systems": list(route.hard_gate_systems),
            "optional_systems": list(route.optional_systems),
            "blocked_by": list(dict.fromkeys(blocked)),
            "optional_gaps": optional,
            "ready_competencies": [item.competency for item in competencies if item.available],
            "unavailable_competencies": [item.competency for item in competencies if not item.available],
        }

    def _intent(self, lowered: str) -> str:
        for intent, cues in self.config.get("task_planning.intent_cues").items():
            if any(str(cue) in lowered for cue in cues):
                return str(intent)
        return "general_request"

    def _constraints(self, text: str) -> tuple[str, ...]:
        markers = self._cues("constraint_markers")
        sentences = re.split(r"(?<=[.!?;])\s+", text)
        constrained = [sentence.strip() for sentence in sentences if any(marker in sentence.lower() for marker in markers)]
        return tuple(constrained[: int(self.config.get("task_planning.max_constraints"))])

    def _temporal_state(self, text: str, constraints: tuple[str, ...]) -> TemporalState:
        lowered = text.lower()
        if any(cue in lowered for cue in self._cues("decision_markers")):
            return "decide"
        if constraints:
            return "constrain"
        starters = "|".join(re.escape(cue) for cue in self._cues("question_starters"))
        if "?" in text or re.match(rf"^({starters})\b", lowered):
            return "ask"
        return "state"

    def _evidence_posture(
        self,
        lowered: str,
        task_class: str,
        governance_verdict: GovernanceVerdict,
    ) -> EvidencePosture:
        if governance_verdict.decision == "REVIEW":
            return "strict"
        if task_class == "systemic" or any(cue in lowered for cue in self._cues("evidence_markers")):
            return "supporting"
        return "none"

    def _open_questions(
        self,
        text: str,
        intent: str,
        governance_verdict: GovernanceVerdict,
        evidence_posture: EvidencePosture,
    ) -> tuple[str, ...]:
        questions: list[str] = []
        if len(re.findall(r"\w+", text)) < int(self.config.get("task_planning.short_input_tokens")):
            questions.append("scope")
        if intent == "design_or_implementation" and not any(
            cue in text.lower() for cue in self._cues("validation_markers")
        ):
            questions.append("validation_criteria")
        if evidence_posture == "strict":
            questions.append("authoritative_evidence")
        if any(marker in text.lower() for marker in self._cues("temporal_markers")):
            questions.append("temporal_context")
        if governance_verdict.decision == "REVIEW":
            questions.append("risk_boundary")
        return tuple(dict.fromkeys(questions))

    def _required_facets(
        self,
        lowered: str,
        constraints: tuple[str, ...],
        evidence_posture: EvidencePosture,
    ) -> tuple[str, ...]:
        facets = ["intent", "scope", "execution_route"]
        if constraints:
            facets.append("constraints")
        if evidence_posture != "none":
            facets.append("evidence")
        if any(marker in lowered for marker in self._cues("temporal_markers")):
            facets.append("temporal_context")
        return tuple(facets)

    def _complexity(
        self,
        lowered: str,
        task_class: str,
        constraints: tuple[str, ...],
        governance_verdict: GovernanceVerdict,
    ) -> int:
        score = 1
        if task_class == "systemic":
            score += int(self.config.get("task_planning.systemic_complexity_bonus"))
        if task_class in {"creative", "artistic"}:
            score += int(self.config.get("task_planning.creative_complexity_bonus"))
        if len(re.findall(r"\w+", lowered)) >= int(self.config.get("task_planning.long_input_tokens")):
            score += 1
        if constraints:
            score += int(self.config.get("task_planning.constraint_complexity_bonus"))
        if governance_verdict.decision == "REVIEW":
            score += int(self.config.get("task_planning.review_complexity_bonus"))
        return min(score, int(self.config.get("task_planning.complexity_ceiling")))

    def _objective(self, text: str) -> str:
        if not text:
            return "No user objective was supplied."
        first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
        return first_sentence[: int(self.config.get("task_planning.max_objective_chars"))]

    def _cues(self, name: str) -> tuple[str, ...]:
        return tuple(str(value).lower() for value in self.config.get(f"task_planning.cues.{name}"))

    @staticmethod
    def _system_requirement(system_id: str, criticality: Criticality) -> tuple[str, str, str, Criticality]:
        labels = {
            "S2": ("concept_association", "Relate concepts and identify relevant semantic bridges."),
            "S5": ("emotional_ethical_framing", "Assess affect, dignity, and ethical tone."),
            "S6": ("influence_mapping", "Trace directional relationships and dependency paths."),
            "S7": ("metacognitive_quality_control", "Assess uncertainty and decide whether deeper review is needed."),
            "S8": ("ethical_governance", "Apply the required governance gate before execution."),
            "S9": ("purpose_alignment", "Check goal and value alignment."),
            "S10": ("artistic_synthesis", "Provide optional multimodal or stylistic composition support."),
            "S11": ("bounded_learning_review", "Evaluate versioned learning or adjustment evidence."),
            "S12": ("system_health_monitoring", "Check system stability and remediation posture."),
            "S13": ("qesae_verification", "Verify high-stakes decisions before execution."),
        }
        competency, rationale = labels.get(
            system_id,
            ("declared_system_capability", "Execute the declared system contract."),
        )
        return competency, system_id, rationale, criticality
