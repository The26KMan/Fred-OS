"""Configuration-led route selection for a single runtime turn."""
from dataclasses import dataclass
from .config import RuntimeConfig

@dataclass(frozen=True)
class Route:
    name: str
    systems: tuple[str, ...]
    reason: str

class Router:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def choose(self, task_class: str, decision: str) -> Route:
        if decision == 'BLOCK':
            return Route('safety', ('S8',), 'governance blocked route')
        if decision == 'REVIEW':
            return Route('deep_review', ('S1','S2','S5','S7','S8','S9','S13'), 'elevated evidence review')
        if task_class in {'creative','artistic'}:
            return Route('creative', ('S1','S5','S9','S10'), 'creative task class')
        return Route(str(self.config.get('protocol.default_mode')), ('S1','S2','S6','S7','S8'), 'default configuration')
