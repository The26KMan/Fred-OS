"""Kernel-level governance gate; it returns explicit verdicts, not hidden actions."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .config import RuntimeConfig

@dataclass(frozen=True)
class GovernanceVerdict:
    decision: str
    rationale: str
    score: float
    escalate_to_genius: bool = False

class GovernanceLayer:
    HIGH_RISK_CUES = {'medical', 'legal', 'financial', 'self-harm', 'violence', 'housing eviction'}
    BLOCKED_CUES = {'malware', 'credential theft', 'exploit a vulnerability'}

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def pre_scan(self, raw_input: str, context: dict[str, Any] | None = None) -> GovernanceVerdict:
        normalized = raw_input.lower()
        if any(cue in normalized for cue in self.BLOCKED_CUES):
            return GovernanceVerdict('BLOCK', 'Request matched a restricted-risk cue; require safe handling.', 0.0)
        if any(cue in normalized for cue in self.HIGH_RISK_CUES):
            return GovernanceVerdict('REVIEW', 'High-stakes domain detected; use evidence-aware routing and cautious response.', 0.60, True)
        return GovernanceVerdict('PASS', 'No elevated governance condition was detected by configured pre-scan.', 0.90)

    def validate_memory_write(self, evidence_count: int, authority: str) -> GovernanceVerdict:
        if evidence_count <= 0 and authority not in {'historical_lineage', 'reflection'}:
            return GovernanceVerdict('REVIEW', 'Memory write lacks evidence; retain only as explicit candidate or reflection.', 0.55, True)
        return GovernanceVerdict('PASS', 'Memory write has an allowed evidence/authority posture.', 0.85)
