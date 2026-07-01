"""Inspectable System-OS migration adapters.

Each adapter retains an explicit maturity label in configuration. Registration
is a runtime contract, not a claim that every historical system specification is
fully implemented.
"""
from __future__ import annotations
import re
from typing import Any, ClassVar
from fred_os.runtime.contracts import SystemPlugin

class DeclaredAdapter(SystemPlugin):
    SYSTEM_NAME: ClassVar[str] = 'Declared System Adapter'
    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {'system_id':self.SYSTEM_ID,'system_name':self.SYSTEM_NAME,'maturity':self.config.get(f'systems.maturity.{self.SYSTEM_ID}','candidate'),'status':'processed_adapter','payload':payload}

class S1(DeclaredAdapter):
    SYSTEM_ID='S1'; SYSTEM_NAME='Cognitive Mapping'
    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        text=str(payload.get('text','')); lower=text.lower()
        entities=sorted(set(re.findall(r'\b[A-Z][A-Za-z0-9_-]{2,}\b',text)))[:20]
        task='systemic' if any(word in lower for word in ('build','design','implement','migrate','architecture')) else 'creative' if any(word in lower for word in ('feel','relationship','creative','art')) else 'general'
        return {'system_id':'S1','entities':entities,'task_class':task,'uncertainty':0.25 if text.strip() else 0.9}

class S2(DeclaredAdapter):
    SYSTEM_ID='S2'; SYSTEM_NAME='Concept Association'; HARD_DEPENDENCIES=('S1',)
    def process(self,payload:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
        nodes=context.get('s1',{}).get('entities',[])
        return {'system_id':'S2','edges':[{'source':a,'target':b,'relation':'co_present'} for i,a in enumerate(nodes) for b in nodes[i+1:]][:30]}

class S5(DeclaredAdapter): SYSTEM_ID='S5'; SYSTEM_NAME='Emotional-Ethical'; HARD_DEPENDENCIES=('S1',)
class S6(DeclaredAdapter): SYSTEM_ID='S6'; SYSTEM_NAME='Influence Flower'; HARD_DEPENDENCIES=('S1','S2')
class S7(DeclaredAdapter): SYSTEM_ID='S7'; SYSTEM_NAME='Metacognition'; HARD_DEPENDENCIES=('S1','S2')
class S8(DeclaredAdapter): SYSTEM_ID='S8'; SYSTEM_NAME='Ethical Governance'
class S9(DeclaredAdapter): SYSTEM_ID='S9'; SYSTEM_NAME='Purpose Alignment'; HARD_DEPENDENCIES=('S1','S5','S8')
class S10(DeclaredAdapter): SYSTEM_ID='S10'; SYSTEM_NAME='Artistic Intelligence'; HARD_DEPENDENCIES=('S1','S2','S9')
class S11(DeclaredAdapter): SYSTEM_ID='S11'; SYSTEM_NAME='Evolutionary Adaptation'
class S12(DeclaredAdapter): SYSTEM_ID='S12'; SYSTEM_NAME='System Healing'
class S13(DeclaredAdapter): SYSTEM_ID='S13'; SYSTEM_NAME='Ethical Adaptation'; HARD_DEPENDENCIES=('S8','S11','S7')

def default_plugins() -> list[type[SystemPlugin]]:
    return [S1,S2,S5,S6,S7,S8,S9,S10,S11,S12,S13]
