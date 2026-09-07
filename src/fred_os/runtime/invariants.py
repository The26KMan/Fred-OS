"""Boot-time invariants for the explicit FRED OS runtime."""
from __future__ import annotations

from collections.abc import Mapping

from .config import ConfigError, RuntimeConfig


class InvariantChecker:
    """Validate the stable core plus optional v2.1 orchestration policy when present."""

    REQUIRED = (
        "meta.schema_version",
        "meta.revision",
        "meta.tenant_id",
        "meta.project_id",
        "runtime.active",
        "governance.pass_floor",
        "governance.review_floor",
        "governance.block_ceiling",
        "memory.repository_path",
        "observability.event_log_path",
        "systems.enabled",
        "protocol.default_mode",
    )

    @classmethod
    def check(cls, config: RuntimeConfig) -> None:
        for path in cls.REQUIRED:
            config.get(path)
        if not config.get("runtime.active"):
            raise ConfigError("I-RUNTIME-01: runtime.active must be true to boot")

        block = float(config.get("governance.block_ceiling"))
        review = float(config.get("governance.review_floor"))
        passed = float(config.get("governance.pass_floor"))
        if not (0 <= block <= review <= passed <= 1):
            raise ConfigError("I-GOV-01: thresholds must satisfy 0<=block<=review<=pass<=1")

        enabled = tuple(str(system_id) for system_id in config.get("systems.enabled"))
        governance_system = str(config.get("governance.kernel_system_id", "S8"))
        if not enabled or governance_system not in enabled:
            raise ConfigError("I-GOV-02: configured governance anchor must remain enabled")
        if len(set(enabled)) != len(enabled):
            raise ConfigError("I-SYS-01: systems.enabled contains duplicates")
        if config.get("memory.working_limit") <= 0:
            raise ConfigError("I-MEM-01: working memory limit must be positive")

        maturities = config.get("systems.maturity", None)
        if isinstance(maturities, Mapping):
            missing_maturity = [system_id for system_id in enabled if system_id not in maturities]
            if missing_maturity:
                raise ConfigError(f"I-SYS-02: enabled systems lack maturity declarations: {missing_maturity}")

        capability_policy = config.get("capability_policy", None)
        if isinstance(capability_policy, Mapping):
            execution_maturities = set(config.get("capability_policy.execution_maturities", ()))
            hard_gate_maturities = set(config.get("capability_policy.hard_gate_maturities", ()))
            if not execution_maturities or not hard_gate_maturities:
                raise ConfigError("I-CAP-01: capability maturity policies must be non-empty")
            if not hard_gate_maturities.issubset(execution_maturities):
                raise ConfigError("I-CAP-02: hard-gate maturities must also be execution maturities")

        routes = config.get("protocol.routes", None)
        if isinstance(routes, Mapping):
            cls._check_routes(config, enabled)

        task_planning = config.get("task_planning", None)
        if isinstance(task_planning, Mapping):
            if config.get("task_planning.short_input_tokens", 1) <= 0:
                raise ConfigError("I-PLAN-01: task planning short_input_tokens must be positive")
            if config.get("task_planning.long_input_tokens", 1) < config.get("task_planning.short_input_tokens", 1):
                raise ConfigError("I-PLAN-02: long_input_tokens must be at least short_input_tokens")
            if config.get("task_planning.complexity_ceiling", 1) < 1:
                raise ConfigError("I-PLAN-03: task planning complexity_ceiling must be positive")

        task_competency = config.get("task_competency", None)
        if isinstance(task_competency, Mapping):
            cls._check_task_competency(config)

    @staticmethod
    def _check_routes(config: RuntimeConfig, enabled: tuple[str, ...]) -> None:
        routes = config.get("protocol.routes")
        policy = config.get("protocol.route_policy", {})
        if not isinstance(routes, Mapping) or not isinstance(policy, Mapping):
            raise ConfigError("I-ROUTE-01: route policy and route declarations must be tables")
        for policy_key in ("block", "review", "default"):
            route_key = str(policy.get(policy_key, ""))
            if route_key not in routes:
                raise ConfigError(f"I-ROUTE-02: route policy '{policy_key}' references missing route '{route_key}'")
        for route_key, definition in routes.items():
            required_fields = {"name", "systems", "hard_gate_systems", "optional_systems", "reason"}
            if not isinstance(definition, Mapping) or not required_fields.issubset(definition):
                raise ConfigError(f"I-ROUTE-03: route '{route_key}' is incomplete")
            systems = tuple(str(system_id) for system_id in definition["systems"])
            hard_gates = tuple(str(system_id) for system_id in definition["hard_gate_systems"])
            optional = tuple(str(system_id) for system_id in definition["optional_systems"])
            if len(set(systems)) != len(systems):
                raise ConfigError(f"I-ROUTE-04: route '{route_key}' has duplicate systems")
            if not set(hard_gates).issubset(systems):
                raise ConfigError(f"I-ROUTE-05: hard gates must be required systems in route '{route_key}'")
            if set(systems).intersection(optional):
                raise ConfigError(f"I-ROUTE-06: optional systems overlap required systems in route '{route_key}'")
            unknown = (set(systems) | set(optional)) - set(enabled)
            if unknown:
                raise ConfigError(f"I-ROUTE-07: route '{route_key}' references disabled systems: {sorted(unknown)}")

    @staticmethod
    def _check_task_competency(config: RuntimeConfig) -> None:
        threshold = float(config.get("task_competency.uncertainty_review_threshold", 1.0))
        if not 0 <= threshold <= 1:
            raise ConfigError("I-TCOL-01: uncertainty_review_threshold must be in [0, 1]")
        routes = config.get("protocol.routes", {})
        route_competencies = config.get("task_competency.route_competencies", {})
        providers = config.get("task_competency.competency_providers", {})
        if routes:
            missing_route_policies = [route_key for route_key in routes if route_key not in route_competencies]
            if missing_route_policies:
                raise ConfigError(f"I-TCOL-02: routes lack competency policies: {missing_route_policies}")
        for route_key, competencies in route_competencies.items():
            for competency in competencies:
                if competency not in providers or not providers[competency]:
                    raise ConfigError(
                        f"I-TCOL-03: competency '{competency}' in route '{route_key}' lacks provider mapping"
                    )
