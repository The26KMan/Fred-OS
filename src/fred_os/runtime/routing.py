"""Configuration-led route selection for a single System-OS runtime turn."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .config import ConfigError, RuntimeConfig


@dataclass(frozen=True)
class Route:
    """A declared protocol route resolved from frozen runtime configuration."""

    key: str
    name: str
    systems: tuple[str, ...]
    reason: str
    hard_gate_systems: tuple[str, ...] = ()
    optional_systems: tuple[str, ...] = ()


class Router:
    """Choose routes from configuration; code contains no route membership policy."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def _route_key(self, task_class: str, decision: str) -> str:
        normalized_decision = decision.lower()
        if normalized_decision in {"block", "review"}:
            return str(self.config.get(f"protocol.route_policy.{normalized_decision}"))
        return str(
            self.config.get(
                f"protocol.task_class_routes.{task_class}",
                self.config.get("protocol.route_policy.default"),
            )
        )

    def _definition(self, route_key: str) -> Mapping[str, Any]:
        route = self.config.get(f"protocol.routes.{route_key}")
        if not isinstance(route, Mapping):
            raise ConfigError(f"I-ROUTE-01: protocol route '{route_key}' must be a table")
        required = ("name", "systems", "hard_gate_systems", "optional_systems", "reason")
        missing = [field for field in required if field not in route]
        if missing:
            raise ConfigError(
                f"I-ROUTE-02: route '{route_key}' missing required fields: {', '.join(missing)}"
            )
        return route

    def choose(self, task_class: str, decision: str) -> Route:
        route_key = self._route_key(task_class, decision)
        definition = self._definition(route_key)
        return Route(
            key=route_key,
            name=str(definition["name"]),
            systems=tuple(str(system_id) for system_id in definition["systems"]),
            reason=str(definition["reason"]),
            hard_gate_systems=tuple(str(system_id) for system_id in definition["hard_gate_systems"]),
            optional_systems=tuple(str(system_id) for system_id in definition["optional_systems"]),
        )
