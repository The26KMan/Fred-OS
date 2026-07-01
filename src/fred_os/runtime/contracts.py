"""Contracts shared by registered System-OS adapters."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar
from .config import RuntimeConfig

@dataclass(frozen=True)
class HealthResult:
    ok: bool
    system_id: str
    reason: str = ''

class SystemPlugin(ABC):
    SYSTEM_ID: ClassVar[str]
    SYSTEM_NAME: ClassVar[str]
    HARD_DEPENDENCIES: ClassVar[tuple[str, ...]] = ()

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True

    def healthcheck(self) -> HealthResult:
        return HealthResult(self.initialized, self.SYSTEM_ID, 'adapter initialized')

    @abstractmethod
    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
