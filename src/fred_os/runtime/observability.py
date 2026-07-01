"""Structured events carrying the active configuration hash."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass
from typing import Any
from .config import RuntimeConfig

@dataclass(frozen=True)
class Event:
    event_type: str
    payload: dict[str, Any]
    timestamp: float
    config_hash: str
    revision: str

class ObservabilityStack:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.path = config.resolve_path('observability.event_log_path')
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> Event:
        event = Event(event_type, dict(payload or {}), time.time(), self.config.config_hash, str(self.config.get('meta.revision')))
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(event.__dict__, sort_keys=True, default=str) + '\n')
        return event
