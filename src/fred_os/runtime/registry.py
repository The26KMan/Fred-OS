"""Topological registry and capability ledger for explicit System-OS adapters."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from .config import RuntimeConfig
from .contracts import HealthResult, SystemPlugin


@dataclass(frozen=True)
class CapabilityStatus:
    """Inspectable availability posture for a single declared System-OS provider."""

    system_id: str
    maturity: str
    enabled: bool
    registered: bool
    initialized: bool
    healthy: bool
    execution_ready: bool
    hard_gate_ready: bool
    reasons: tuple[str, ...]


class SystemRegistry:
    """Resolve, instantiate, and audit explicitly declared runtime providers.

    Registration is intentionally not treated as implementation evidence. A route can
    use only an initialized and healthy provider with an allowed maturity label; a
    hard gate is stricter and accepts only concrete implementation or kernel-owned
    governance. This prevents a candidate adapter from satisfying an ethical gate.
    """

    EXECUTION_MATURITIES = frozenset(
        {"implemented_adapter", "tested_prototype_adapter", "kernel_governance"}
    )
    HARD_GATE_MATURITIES = frozenset({"implemented_adapter", "kernel_governance"})

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.classes: dict[str, type[SystemPlugin]] = {}
        self.instances: dict[str, SystemPlugin] = {}
        self.boot_order: list[str] = []

    def register(self, plugin_class: type[SystemPlugin]) -> None:
        system_id = plugin_class.SYSTEM_ID
        if system_id in self.classes:
            raise ValueError(f"Duplicate system plugin: {system_id}")
        self.classes[system_id] = plugin_class

    def resolve(self) -> list[str]:
        enabled = list(self.config.get("systems.enabled"))
        missing = set(enabled) - set(self.classes)
        if missing:
            raise ValueError(f"Enabled systems are not registered: {sorted(missing)}")
        visiting, visited, ordered = set(), set(), []

        def visit(system_id: str) -> None:
            if system_id in visited:
                return
            if system_id in visiting:
                raise ValueError(f"Hard dependency cycle at {system_id}")
            visiting.add(system_id)
            for dependency in self.classes[system_id].HARD_DEPENDENCIES:
                if dependency in enabled:
                    visit(dependency)
            visiting.remove(system_id)
            visited.add(system_id)
            ordered.append(system_id)

        for system_id in enabled:
            visit(system_id)
        self.boot_order = ordered
        return list(ordered)

    def instantiate(self) -> None:
        for system_id in self.boot_order:
            plugin = self.classes[system_id](self.config)
            plugin.initialize()
            self.instances[system_id] = plugin

    def health_check_all(self) -> dict[str, HealthResult]:
        checks = {system_id: plugin.healthcheck() for system_id, plugin in self.instances.items()}
        failed = [item for item in checks.values() if not item.ok]
        if failed:
            raise RuntimeError(f"System health failures: {failed}")
        return checks

    def capability(self, system_id: str) -> CapabilityStatus:
        enabled = system_id in self.config.get("systems.enabled")
        registered = system_id in self.classes
        instance = self.instances.get(system_id)
        initialized = bool(instance and instance.initialized)
        health = instance.healthcheck() if instance else HealthResult(False, system_id, "not instantiated")
        healthy = bool(health.ok)
        maturity = str(self.config.get(f"systems.maturity.{system_id}", "undeclared"))

        reasons: list[str] = []
        if not enabled:
            reasons.append("disabled_in_configuration")
        if not registered:
            reasons.append("provider_not_registered")
        if not initialized:
            reasons.append("provider_not_initialized")
        if not healthy:
            reasons.append(f"healthcheck_failed:{health.reason or 'unknown'}")
        if maturity not in self.EXECUTION_MATURITIES:
            reasons.append(f"maturity_not_executable:{maturity}")

        base_available = enabled and registered and initialized and healthy
        execution_ready = base_available and maturity in self.EXECUTION_MATURITIES
        hard_gate_ready = base_available and maturity in self.HARD_GATE_MATURITIES
        if not hard_gate_ready:
            reasons.append(f"maturity_not_hard_gate_ready:{maturity}")

        return CapabilityStatus(
            system_id=system_id,
            maturity=maturity,
            enabled=enabled,
            registered=registered,
            initialized=initialized,
            healthy=healthy,
            execution_ready=execution_ready,
            hard_gate_ready=hard_gate_ready,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def assess_route(
        self,
        required_systems: tuple[str, ...],
        hard_gate_systems: tuple[str, ...] = (),
        optional_systems: tuple[str, ...] = (),
    ) -> dict[str, object]:
        """Return a serializable, fail-closed capability report for one route."""
        requested = tuple(dict.fromkeys(required_systems + hard_gate_systems + optional_systems))
        statuses = {system_id: self.capability(system_id) for system_id in requested}
        required_missing = [
            system_id for system_id in required_systems if not statuses[system_id].execution_ready
        ]
        hard_gate_missing = [
            system_id for system_id in hard_gate_systems if not statuses[system_id].hard_gate_ready
        ]
        optional_unavailable = [
            system_id for system_id in optional_systems if not statuses[system_id].execution_ready
        ]
        return {
            "ready": not required_missing and not hard_gate_missing,
            "required_missing": required_missing,
            "hard_gate_missing": hard_gate_missing,
            "optional_unavailable": optional_unavailable,
            "systems": {system_id: asdict(status) for system_id, status in statuses.items()},
        }

    def get(self, system_id: str) -> SystemPlugin:
        return self.instances[system_id]
