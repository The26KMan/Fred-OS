"""Dream Protocol: bounded engineering-roadmap exploration for Fred-OS.

Dream reviews an explicit project inventory and returns a deterministic roadmap.
It does not execute project changes, mutate runtime state, or claim background
planning. See specs/protocols/dream_protocol.md.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class Status(str, Enum):
    IMPLEMENTED = "implemented"
    IMPLEMENTED_UNWIRED = "implemented_unwired"
    TESTED_PROTOTYPE = "tested_prototype"
    DOCUMENTED = "documented"
    CANDIDATE = "candidate"
    PLACEHOLDER = "placeholder"
    BLOCKED = "blocked"


_STATUS_SCORE = {
    Status.IMPLEMENTED: 1.00,
    Status.TESTED_PROTOTYPE: 0.78,
    Status.IMPLEMENTED_UNWIRED: 0.62,
    Status.DOCUMENTED: 0.42,
    Status.CANDIDATE: 0.22,
    Status.PLACEHOLDER: 0.12,
    Status.BLOCKED: 0.00,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class Component:
    identifier: str
    label: str
    status: Status
    dependencies: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    risk: float = 0.20
    effort: float = 0.50
    unlock_value: float = 0.50
    notes: str = ""

    @property
    def readiness(self) -> float:
        evidence_factor = min(1.0, 0.35 + 0.15 * len(self.evidence))
        return round(_clamp(_STATUS_SCORE[self.status] * evidence_factor), 4)


@dataclass(frozen=True)
class Constraint:
    identifier: str
    severity: str
    description: str
    affected: tuple[str, ...]
    required_before_progress: bool = True


@dataclass(frozen=True)
class WorkItem:
    identifier: str
    label: str
    component_id: str
    depends_on: tuple[str, ...] = ()
    effort: float = 0.50
    unlock_value: float = 0.50


@dataclass
class CandidatePath:
    identifier: str
    label: str
    work: list[WorkItem]
    order: list[str] = field(default_factory=list)
    score: float = 0.0
    blocked_by: list[str] = field(default_factory=list)
    rationale: str = ""


class DreamEngine:
    """Deterministic planning model; it does not execute project changes."""

    def review(self, components: Iterable[Component], constraints: Iterable[Constraint]) -> dict[str, Any]:
        catalog = {item.identifier: item for item in components}
        constraints = list(constraints)
        if not catalog:
            raise ValueError("Dream review requires at least one component")
        paths = self._candidate_paths()
        critical = self._critical_blockers(catalog, constraints)
        for path in paths:
            path.order = self._topological_order(path.work)
            path.blocked_by = self._path_blockers(path, catalog, critical)
            path.score = self._score(path, catalog)
        eligible = [path for path in paths if not path.blocked_by]
        selected = max(eligible or paths, key=lambda item: item.score)
        return {
            "protocol": "DREAM_REVIEW",
            "inventory_digest": self._digest(catalog, constraints),
            "evidence_boundary": [
                "Statuses reflect supplied inventory and explicit repository inspection.",
                "Specs and prototypes are not treated as proof of runtime integration.",
                "Dream generates a plan only; it does not write code, memory, or configuration.",
            ],
            "readiness": {key: value.readiness for key, value in catalog.items()},
            "blockers": [
                {"id": item.identifier, "severity": item.severity, "description": item.description,
                 "affected": list(item.affected), "required_before_progress": item.required_before_progress}
                for item in constraints if item.identifier in critical or item.severity.lower() == "critical"
            ],
            "candidate_paths": [self._serialize_path(path) for path in paths],
            "recommended_path": self._serialize_path(selected),
            "staged_plan": self._stage_plan(selected, catalog),
            "assumptions": [
                "Only declared dependencies are ordered automatically.",
                "A component marked implemented_unwired needs an integration test before downstream reliance.",
                "A component marked candidate or placeholder cannot satisfy a runtime dependency.",
            ],
            "rejection_log": self._rejections(paths, selected),
        }

    @staticmethod
    def _candidate_paths() -> list[CandidatePath]:
        def item(identifier: str, label: str, component: str, depends: tuple[str, ...] = (), effort: float = .5, unlock: float = .5) -> WorkItem:
            return WorkItem(identifier, label, component, depends, effort, unlock)
        return [
            CandidatePath("integration_first", "Integration-first vertical slice", [
                item("wire_s1_runtime", "Wire System-1 runtime adapter into registry", "s1_runtime_adapter", (), .25, .78),
                item("wire_tsc_kernel", "Instantiate TSC and pass temporal context through kernel", "temporal_sphere", ("wire_s1_runtime",), .34, .88),
                item("restore_tsc_memory_contract", "Implement bidirectional TSC and Memory Lake references", "memory_tsc_contract", ("wire_tsc_kernel",), .38, .90),
                item("integration_tests", "Add boot-to-turn integration tests and repository checks", "test_harness", ("restore_tsc_memory_contract",), .32, .86),
                item("complete_s2", "Port System-2 over the integrated S1/TSC contract", "system2", ("integration_tests",), .60, .85),
            ], rationale="Closes the gap between modules that exist and modules the runtime actually invokes."),
            CandidatePath("memory_temporal_first", "Memory-temporal consolidation", [
                item("wire_tsc_kernel", "Instantiate TSC and pass temporal context through kernel", "temporal_sphere", (), .34, .88),
                item("restore_tsc_memory_contract", "Implement bidirectional TSC and Memory Lake references", "memory_tsc_contract", ("wire_tsc_kernel",), .38, .90),
                item("snapshot_restore", "Add durable snapshot restore and migration checks", "temporal_sphere", ("restore_tsc_memory_contract",), .42, .72),
                item("integration_tests", "Add memory-temporal integration tests", "test_harness", ("snapshot_restore",), .32, .82),
            ], rationale="Prioritizes durable continuity before broader reasoning layers."),
            CandidatePath("vertical_slice_s1_s2", "Association-layer first", [
                item("complete_s2", "Port System-2 association engine", "system2", (), .60, .85),
                item("s1_s2_contract_tests", "Add S1-to-S2 schema and uncertainty tests", "test_harness", ("complete_s2",), .30, .76),
                item("s6_handoff", "Connect association output to S6 influence mapping", "system6", ("s1_s2_contract_tests",), .48, .72),
            ], rationale="Builds association capability quickly but assumes S1 and temporal integration are operational."),
            CandidatePath("breadth_first", "Parallel subsystem breadth", [
                item("port_s3", "Port System-3 NLP", "system3", (), .70, .58),
                item("port_s4", "Port System-4 QTE adapter", "system4", (), .75, .54),
                item("port_s5_s9", "Port Systems 5 and 9", "system5", (), .65, .60),
                item("port_s7", "Port System-7 adaptation controller", "system7", (), .68, .60),
            ], rationale="Increases surface area but leaves core integration gaps unresolved."),
        ]

    @staticmethod
    def _critical_blockers(catalog: dict[str, Component], constraints: list[Constraint]) -> set[str]:
        result = {item.identifier for item in constraints if item.severity.lower() == "critical"}
        result.update(f"status:{item.identifier}" for item in catalog.values() if item.status == Status.BLOCKED)
        return result

    def _path_blockers(self, path: CandidatePath, catalog: dict[str, Component], critical: set[str]) -> list[str]:
        blockers: list[str] = []
        work_components = {item.component_id for item in path.work}
        for item in path.work:
            component = catalog.get(item.component_id)
            if component is None:
                blockers.append(f"missing_component:{item.component_id}")
                continue
            if component.status == Status.BLOCKED:
                blockers.append(f"blocked_component:{item.component_id}")
            for dependency in component.dependencies:
                if dependency not in work_components:
                    upstream = catalog.get(dependency)
                    if upstream is None or upstream.status not in {Status.IMPLEMENTED, Status.TESTED_PROTOTYPE}:
                        blockers.append(f"unsatisfied_dependency:{item.component_id}->{dependency}")
        core = {"kernel_tsc_unwired", "s1_adapter_unwired", "tsc_memory_bidirectional_missing"}
        if path.identifier in {"vertical_slice_s1_s2", "breadth_first"}:
            blockers.extend(sorted(critical & core))
        return sorted(set(blockers))

    @staticmethod
    def _topological_order(work: list[WorkItem]) -> list[str]:
        by_id = {item.identifier: item for item in work}
        ordered: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(identifier: str) -> None:
            if identifier in visited:
                return
            if identifier in visiting:
                raise ValueError(f"Dream work cycle: {identifier}")
            visiting.add(identifier)
            for dependency in by_id[identifier].depends_on:
                if dependency not in by_id:
                    raise ValueError(f"Unknown Dream work dependency: {dependency}")
                visit(dependency)
            visiting.remove(identifier)
            visited.add(identifier)
            ordered.append(identifier)
        for item in work:
            visit(item.identifier)
        return ordered

    def _score(self, path: CandidatePath, catalog: dict[str, Component]) -> float:
        components = [catalog[item.component_id] for item in path.work if item.component_id in catalog]
        if not components:
            return 0.0
        readiness = sum(item.readiness for item in components) / len(components)
        evidence = sum(min(1.0, .20 * len(item.evidence)) for item in components) / len(components)
        unlock = sum(item.unlock_value for item in path.work) / len(path.work)
        reversibility = 1.0 - sum(item.effort for item in path.work) / len(path.work) * .35
        risk = sum(item.risk for item in components) / len(components)
        integration_bonus = .18 if path.identifier == "integration_first" else .10 if path.identifier == "memory_temporal_first" else .0
        return round(_clamp(.30 * readiness + .25 * (.8 + integration_bonus) + .20 * evidence + .20 * unlock + .05 * reversibility - .20 * risk), 4)

    @staticmethod
    def _serialize_path(path: CandidatePath) -> dict[str, Any]:
        by_id = {item.identifier: item for item in path.work}
        return {"id": path.identifier, "label": path.label, "score": path.score, "blocked_by": path.blocked_by,
                "rationale": path.rationale, "order": path.order,
                "work": [{"id": by_id[key].identifier, "label": by_id[key].label, "component": by_id[key].component_id,
                          "depends_on": list(by_id[key].depends_on), "effort": by_id[key].effort,
                          "unlock_value": by_id[key].unlock_value} for key in path.order]}

    @staticmethod
    def _stage_plan(selected: CandidatePath, catalog: dict[str, Component]) -> list[dict[str, Any]]:
        by_id = {item.identifier: item for item in selected.work}
        stages = []
        for index, work_id in enumerate(selected.order, 1):
            item = by_id[work_id]
            component = catalog.get(item.component_id)
            stages.append({"stage": index, "work_id": item.identifier, "objective": item.label,
                           "component": item.component_id, "entry_status": component.status.value if component else "missing",
                           "verification_gates": ["unit tests pass", "input/output contract is validated",
                                                  "provenance or configuration effects are inspectable",
                                                  "migration status is updated without overstating maturity"]})
        return stages

    @staticmethod
    def _rejections(paths: list[CandidatePath], selected: CandidatePath) -> list[dict[str, str]]:
        return [{"path": path.identifier, "reason": "blocked: " + ", ".join(path.blocked_by) if path.blocked_by else "lower validated score"}
                for path in paths if path.identifier != selected.identifier]

    @staticmethod
    def _digest(catalog: dict[str, Component], constraints: list[Constraint]) -> str:
        payload = {"components": {key: {"status": value.status.value, "dependencies": value.dependencies, "evidence": value.evidence}
                                  for key, value in sorted(catalog.items())}, "constraints": [asdict(item) for item in constraints]}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
