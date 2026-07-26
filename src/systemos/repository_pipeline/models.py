from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence
from uuid import uuid4


class EvidenceState(str, Enum):
    """How strongly a claim or artifact is supported."""

    DECLARED = "DECLARED"
    STRUCTURALLY_SPECIFIED = "STRUCTURALLY_SPECIFIED"
    MODEL_INTERPRETED = "MODEL_INTERPRETED"
    EMPIRICALLY_OBSERVED = "EMPIRICALLY_OBSERVED"
    TOOL_SUPPORTED = "TOOL_SUPPORTED"
    RUNTIME_ENFORCED = "RUNTIME_ENFORCED"
    COUNTERFACTUALLY_VALIDATED = "COUNTERFACTUALLY_VALIDATED"


class SourceKind(str, Enum):
    USER_INPUT = "USER_INPUT"
    CONVERSATION = "CONVERSATION"
    LIBRARY_FILE = "LIBRARY_FILE"
    REPOSITORY_FILE = "REPOSITORY_FILE"
    WEB_DOCUMENT = "WEB_DOCUMENT"
    API_RESPONSE = "API_RESPONSE"
    TOOL_RESULT = "TOOL_RESULT"


class ArtifactKind(str, Enum):
    DOCUMENTATION = "DOCUMENTATION"
    SPECIFICATION = "SPECIFICATION"
    SOURCE_CODE = "SOURCE_CODE"
    TEST = "TEST"
    SCHEMA = "SCHEMA"
    CONFIGURATION = "CONFIGURATION"
    SKILL = "SKILL"
    DIAGRAM = "DIAGRAM"


class PipelineStage(str, Enum):
    RECEIVE = "RECEIVE"
    RETRIEVE = "RETRIEVE"
    NORMALIZE = "NORMALIZE"
    MAP = "MAP"
    REFINE = "REFINE"
    VALIDATE = "VALIDATE"
    EMIT = "EMIT"
    TRACE = "TRACE"


class IssueSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class RefinementRequest:
    objective: str
    target_repository: str
    target_branch: str
    constraints: tuple[str, ...] = ()
    requested_artifacts: tuple[ArtifactKind, ...] = ()
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.objective.strip():
            raise ValueError("objective must not be blank")
        if not self.target_repository.strip():
            raise ValueError("target_repository must not be blank")
        if not self.target_branch.strip():
            raise ValueError("target_branch must not be blank")


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    kind: SourceKind
    uri: str
    content: str
    digest: str
    fetched_at: datetime
    evidence_state: EvidenceState
    revision: str | None = None
    fragment: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        *,
        kind: SourceKind,
        uri: str,
        content: str,
        evidence_state: EvidenceState,
        revision: str | None = None,
        fragment: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        source_id: str | None = None,
    ) -> "SourceRecord":
        normalized_bytes = content.encode("utf-8")
        return cls(
            source_id=source_id or str(uuid4()),
            kind=kind,
            uri=uri,
            content=content,
            digest=sha256(normalized_bytes).hexdigest(),
            fetched_at=datetime.now(timezone.utc),
            evidence_state=evidence_state,
            revision=revision,
            fragment=fragment,
            metadata=metadata or {},
        )


@dataclass(frozen=True, slots=True)
class ContextMap:
    entities: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepositoryArtifact:
    path: str
    kind: ArtifactKind
    content: str
    rationale: str
    source_ids: tuple[str, ...]
    evidence_state: EvidenceState = EvidenceState.STRUCTURALLY_SPECIFIED
    validation_receipts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe repository path: {self.path}")
        if not self.content.strip():
            raise ValueError(f"artifact content must not be blank: {self.path}")
        if not self.rationale.strip():
            raise ValueError(f"artifact rationale must not be blank: {self.path}")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: IssueSeverity
    message: str
    artifact_path: str | None = None
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    approved: bool
    issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class TraceEvent:
    stage: PipelineStage
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TraceReceipt:
    request_id: str
    succeeded: bool
    events: tuple[TraceEvent, ...]
    artifact_paths: tuple[str, ...]
    source_digests: Mapping[str, str]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PipelineResult:
    request: RefinementRequest
    context_map: ContextMap
    artifacts: tuple[RepositoryArtifact, ...]
    validation: ValidationReport
    receipt: TraceReceipt


def highest_evidence_state(states: Sequence[EvidenceState]) -> EvidenceState:
    ranking = list(EvidenceState)
    if not states:
        return EvidenceState.DECLARED
    return max(states, key=ranking.index)
