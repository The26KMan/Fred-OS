"""Configuration-led route selection for a single System-OS runtime turn."""
from __future__ import annotations

from dataclasses import dataclass

from .config import RuntimeConfig


@dataclass(frozen=True)
class Route:
    """A declarative protocol route with explicit capability posture."""

    name: str
    systems: tuple[str, ...]
    reason: str
    hard_gate_systems: tuple[str, ...] = ()
    optional_systems: tuple[str, ...] = ()


class Router:
    """Choose a protocol route without treating declared adapters as available."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def choose(self, task_class: str, decision: str) -> Route:
        if decision == "BLOCK":
            return Route(
                "safety",
                ("S8",),
                "governance blocked route",
                hard_gate_systems=("S8",),
            )
        if decision == "REVIEW":
            return Route(
                "deep_review",
                ("S1", "S2", "S5", "S7", "S8", "S9", "S13"),
                "elevated evidence review requires QESAE verification",
                hard_gate_systems=("S8", "S13"),
            )
        if task_class in {"creative", "artistic"}:
            return Route(
                "creative",
                ("S1", "S5", "S8", "S9"),
                "creative task class with governance baseline",
                hard_gate_systems=("S8",),
                optional_systems=("S10",),
            )
        return Route(
            str(self.config.get("protocol.default_mode")),
            ("S1", "S2", "S6", "S7", "S8"),
            "default configuration",
            hard_gate_systems=("S8",),
        )
