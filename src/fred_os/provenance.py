"""Versioned source locators and evidence authority labels."""
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote, unquote

class Authority(str, Enum):
    IMPLEMENTATION = 'implementation'
    TESTED_PROTOTYPE = 'tested_prototype'
    GOVERNANCE_POLICY = 'governance_policy'
    DESIGN_SPEC = 'design_spec'
    HISTORICAL_LINEAGE = 'historical_lineage'
    REFLECTION = 'reflection'
    UNVERIFIED = 'unverified'

    @property
    def score(self) -> int:
        return {'implementation':100, 'tested_prototype':85, 'governance_policy':80, 'design_spec':65, 'historical_lineage':35, 'reflection':25, 'unverified':10}[self.value]

class Lifecycle(str, Enum):
    CURRENT = 'current'
    SUPERSEDED = 'superseded'
    HISTORICAL = 'historical'
    CANDIDATE = 'candidate'

def slug(value: str, fallback: str) -> str:
    return re.sub(r'[^a-z0-9_-]+', '-', value.lower()).strip('-') or fallback

@dataclass(frozen=True)
class SourceLocator:
    tenant_id: str
    project_id: str
    artifact_id: str
    revision_id: str
    fragment_id: str

    @property
    def canonical(self) -> str:
        return f"deeplink://{quote(self.tenant_id)}/{quote(self.project_id)}/{quote(self.artifact_id)}@{quote(self.revision_id)}#{quote(self.fragment_id)}"

    @classmethod
    def parse(cls, value: str) -> 'SourceLocator':
        if not value.startswith('deeplink://') or '@' not in value or '#' not in value:
            raise ValueError('Invalid versioned source locator')
        body, fragment = value[len('deeplink://'):].split('#', 1)
        parts = body.split('/')
        artifact, revision = parts[2].rsplit('@', 1)
        return cls(unquote(parts[0]), unquote(parts[1]), unquote(artifact), unquote(revision), unquote(fragment))
