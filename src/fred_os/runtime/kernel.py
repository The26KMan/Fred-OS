"""Bootable owner of the explicit Fred-OS vNext runtime graph."""
from __future__ import annotations
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .config import ConfigLoader, RuntimeConfig
from .governance import GovernanceLayer
from .observability import ObservabilityStack
from .registry import SystemRegistry
from .routing import Router
from fred_os.semantic_memory import SemanticMemoryLake
from fred_os.systems.adapters import default_plugins

@dataclass
class RuntimeKernel:
    config: RuntimeConfig
    governance: GovernanceLayer
    observability: ObservabilityStack
    memory: SemanticMemoryLake
    registry: SystemRegistry
    router: Router
    booted_at: float

    @classmethod
    def boot(cls, *, root_dir: str | Path='.', profile: str='development') -> 'RuntimeKernel':
        root=Path(root_dir).resolve()
        config=ConfigLoader.build(root_dir=root,profile=profile)
        governance=GovernanceLayer(config)
        obs=ObservabilityStack(config); obs.emit('GLOBAL_INIT_OK',{'profile':profile})
        memory=SemanticMemoryLake(config.resolve_path('memory.repository_path'),str(config.get('meta.tenant_id')),str(config.get('meta.project_id')))
        obs.emit('MEMORY_READY',{})
        registry=SystemRegistry(config)
        for plugin in default_plugins(): registry.register(plugin)
        order=registry.resolve(); registry.instantiate(); checks=registry.health_check_all()
        router=Router(config)
        kernel=cls(config,governance,obs,memory,registry,router,time.time())
        obs.emit('SYSTEM_READY',{'systems':len(checks),'boot_order':order})
        return kernel

    def process_turn(self, raw_input: str) -> dict[str, Any]:
        verdict=self.governance.pre_scan(raw_input)
        if verdict.decision == 'BLOCK':
            self.observability.emit('GOVERNANCE_BLOCK',{'reason':verdict.rationale})
            return {'verdict':verdict,'response':'The runtime blocked this request for safe handling.'}
        s1=self.registry.get('S1').process({'text':raw_input},{})
        route=self.router.choose(s1['task_class'],verdict.decision)
        context={'s1':s1}; outputs={'S1':s1}
        for system_id in route.systems:
            if system_id in {'S1','S8'} or system_id not in self.config.get('systems.enabled'): continue
            outputs[system_id]=self.registry.get(system_id).process({'text':raw_input},context)
            context[system_id.lower()]=outputs[system_id]
        self.observability.emit('TURN_COMPLETED',{'route':route.name,'systems':list(outputs)})
        return {'verdict':verdict,'route':route,'outputs':outputs}

    def close(self) -> None:
        self.memory.close()
