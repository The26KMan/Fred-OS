"""Inspectable System-OS migration adapters.

Registration describes actual callable adapters. Configuration maturity labels
remain the authoritative declaration of implementation depth.
"""
from __future__ import annotations

from typing import Any, ClassVar

from fred_os.runtime.contracts import SystemPlugin
from .system1_runtime_adapter import System1RuntimeAdapter


class DeclaredAdapter(SystemPlugin):
    SYSTEM_NAME: ClassVar[str] = "Declared System Adapter"

    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "system_id": self.SYSTEM_ID,
            "system_name": self.SYSTEM_NAME,
            "maturity": self.config.get(f"systems.maturity.{self.SYSTEM_ID}", "candidate"),
            "status": "processed_adapter",
            "payload": payload,
        }


class S2(DeclaredAdapter):
    SYSTEM_ID = "S2"
    SYSTEM_NAME = "Concept Association"
    HARD_DEPENDENCIES = ("S1",)

    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        nodes = list(context.get("s1", {}).get("entities", []))
        return {
            "system_id": self.SYSTEM_ID,
            "edges": [{"source": left, "target": right, "relation": "co_present"} for index, left in enumerate(nodes) for right in nodes[index + 1:]][:30],
            "input_node_count": len(nodes),
        }


class S5(DeclaredAdapter): SYSTEM_ID = "S5"; SYSTEM_NAME = "Emotional-Ethical"; HARD_DEPENDENCIES = ("S1",)
class S6(DeclaredAdapter): SYSTEM_ID = "S6"; SYSTEM_NAME = "Influence Flower"; HARD_DEPENDENCIES = ("S1", "S2")
class S7(DeclaredAdapter): SYSTEM_ID = "S7"; SYSTEM_NAME = "Metacognition"; HARD_DEPENDENCIES = ("S1", "S2")
class S8(DeclaredAdapter): SYSTEM_ID = "S8"; SYSTEM_NAME = "Ethical Governance"
class S9(DeclaredAdapter): SYSTEM_ID = "S9"; SYSTEM_NAME = "Purpose Alignment"; HARD_DEPENDENCIES = ("S1", "S5", "S8")
class S10(DeclaredAdapter): SYSTEM_ID = "S10"; SYSTEM_NAME = "Artistic Intelligence"; HARD_DEPENDENCIES = ("S1", "S2", "S9")
class S11(DeclaredAdapter): SYSTEM_ID = "S11"; SYSTEM_NAME = "Evolutionary Adaptation"
class S12(DeclaredAdapter): SYSTEM_ID = "S12"; SYSTEM_NAME = "System Healing"
class S13(DeclaredAdapter): SYSTEM_ID = "S13"; SYSTEM_NAME = "Ethical Adaptation"; HARD_DEPENDENCIES = ("S8", "S11", "S7")


def default_plugins() -> list[type[SystemPlugin]]:
    return [System1RuntimeAdapter, S2, S5, S6, S7, S8, S9, S10, S11, S12, S13]
