"""Boot-time invariants for the explicit Fred-OS runtime."""
from .config import ConfigError, RuntimeConfig

class InvariantChecker:
    REQUIRED = (
        'meta.schema_version', 'meta.revision', 'meta.tenant_id', 'meta.project_id',
        'runtime.active', 'governance.pass_floor', 'governance.review_floor',
        'governance.block_ceiling', 'memory.repository_path', 'observability.event_log_path',
        'systems.enabled', 'protocol.default_mode',
    )

    @classmethod
    def check(cls, config: RuntimeConfig) -> None:
        for path in cls.REQUIRED:
            config.get(path)
        if not config.get('runtime.active'):
            raise ConfigError('I-RUNTIME-01: runtime.active must be true to boot')
        block = float(config.get('governance.block_ceiling'))
        review = float(config.get('governance.review_floor'))
        passed = float(config.get('governance.pass_floor'))
        if not (0 <= block <= review <= passed <= 1):
            raise ConfigError('I-GOV-01: thresholds must satisfy 0<=block<=review<=pass<=1')
        enabled = config.get('systems.enabled')
        if not enabled or 'S8' not in enabled:
            raise ConfigError('I-GOV-02: S8 must remain enabled as the governance anchor')
        if len(set(enabled)) != len(enabled):
            raise ConfigError('I-SYS-01: systems.enabled contains duplicates')
        if config.get('memory.working_limit') <= 0:
            raise ConfigError('I-MEM-01: working memory limit must be positive')
