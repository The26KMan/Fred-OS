from __future__ import annotations

import pytest

from systemos.repository_pipeline import (
    ArtifactKind,
    ContextMap,
    EvidenceState,
    IssueSeverity,
    RefinementRequest,
    RepositoryArtifact,
    RepositoryRefinementPipeline,
    SourceKind,
    SourceRecord,
    ValidationIssue,
    ValidationReport,
)


class PassingAdapter:
    def map_context(self, request, sources):
        return ContextMap(
            entities=("Fred-OS", "RepositoryRefinementPipeline"),
            claims=("Retrieved data must retain provenance.",),
            constraints=request.constraints,
            dependencies=("source closure", "validation receipt"),
            ambiguities=(),
            source_ids=tuple(source.source_id for source in sources),
        )

    def refine(self, request, context_map, sources):
        return (
            RepositoryArtifact(
                path="docs/refinement.md",
                kind=ArtifactKind.DOCUMENTATION,
                content="# Refinement\n\nSource-closed repository guidance.",
                rationale="Document the governed pipeline.",
                source_ids=tuple(source.source_id for source in sources),
                evidence_state=EvidenceState.STRUCTURALLY_SPECIFIED,
            ),
        )

    def critique(self, request, context_map, artifacts, sources):
        return ValidationReport(approved=True)


class RuntimeClaimAdapter(PassingAdapter):
    def refine(self, request, context_map, sources):
        return (
            RepositoryArtifact(
                path="src/runtime_claim.py",
                kind=ArtifactKind.SOURCE_CODE,
                content="ENFORCED = True\n",
                rationale="Exercise evidence-state enforcement.",
                source_ids=(sources[0].source_id,),
                evidence_state=EvidenceState.RUNTIME_ENFORCED,
            ),
        )


class CritiqueFailureAdapter(PassingAdapter):
    def critique(self, request, context_map, artifacts, sources):
        return ValidationReport(
            approved=False,
            issues=(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "Purpose alignment failed.",
                    artifact_path=artifacts[0].path,
                ),
            ),
        )


def make_request() -> RefinementRequest:
    return RefinementRequest(
        objective="Formalize retrieval into repository artifacts.",
        target_repository="The26KMan/Fred-OS",
        target_branch="agent/repository-refinement",
        constraints=("preserve provenance", "do not commit credentials"),
    )


def make_source(source_id: str = "source-1") -> SourceRecord:
    return SourceRecord.from_text(
        source_id=source_id,
        kind=SourceKind.LIBRARY_FILE,
        uri="library://system-os-architecture",
        content="Architecture source.  \n",
        evidence_state=EvidenceState.TOOL_SUPPORTED,
        revision="1",
        fragment="lines:1-20",
    )


def test_pipeline_emits_source_closed_artifact_and_trace() -> None:
    result = RepositoryRefinementPipeline(PassingAdapter()).run(
        make_request(), (make_source(),)
    )

    assert result.validation.approved is True
    assert result.receipt.succeeded is True
    assert result.receipt.artifact_paths == ("docs/refinement.md",)
    assert result.receipt.source_digests["source-1"] == make_source().digest
    assert result.context_map.source_ids == ("source-1",)


def test_runtime_enforced_claim_requires_validator_receipt() -> None:
    result = RepositoryRefinementPipeline(RuntimeClaimAdapter()).run(
        make_request(), (make_source(),)
    )

    assert result.validation.approved is False
    assert result.artifacts == ()
    assert any(
        issue.message == "RUNTIME_ENFORCED requires a validator receipt."
        for issue in result.validation.issues
    )


def test_adapter_critique_can_withhold_artifacts() -> None:
    result = RepositoryRefinementPipeline(CritiqueFailureAdapter()).run(
        make_request(), (make_source(),)
    )

    assert result.receipt.succeeded is False
    assert result.receipt.artifact_paths == ()


def test_repository_artifact_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="unsafe repository path"):
        RepositoryArtifact(
            path="../secrets.json",
            kind=ArtifactKind.CONFIGURATION,
            content="{}",
            rationale="Invalid path test.",
            source_ids=("source-1",),
        )


def test_context_map_rejects_unknown_sources() -> None:
    class UnknownSourceAdapter(PassingAdapter):
        def map_context(self, request, sources):
            return ContextMap(source_ids=("missing",))

    with pytest.raises(ValueError, match="unknown sources"):
        RepositoryRefinementPipeline(UnknownSourceAdapter()).run(
            make_request(), (make_source(),)
        )
