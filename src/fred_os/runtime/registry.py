"""Topological registry for explicit System-OS adapters."""
from __future__ import annotations
from .config import RuntimeConfig
from .contracts import HealthResult, SystemPlugin

class SystemRegistry:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.classes: dict[str, type[SystemPlugin]] = {}
        self.instances: dict[str, SystemPlugin] = {}
        self.boot_order: list[str] = []

    def register(self, plugin_class: type[SystemPlugin]) -> None:
        system_id = plugin_class.SYSTEM_ID
        if system_id in self.classes:
            raise ValueError(f'Duplicate system plugin: {system_id}')
        self.classes[system_id] = plugin_class

    def resolve(self) -> list[str]:
        enabled = list(self.config.get('systems.enabled'))
        missing = set(enabled) - set(self.classes)
        if missing:
            raise ValueError(f'Enabled systems are not registered: {sorted(missing)}')
        visiting, visited, ordered = set(), set(), []
        def visit(system_id: str) -> None:
            if system_id in visited:
                return
            if system_id in visiting:
                raise ValueError(f'Hard dependency cycle at {system_id}')
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
            raise RuntimeError(f'System health failures: {failed}')
        return checks

    def get(self, system_id: str) -> SystemPlugin:
        return self.instances[system_id]
