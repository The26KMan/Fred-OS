from __future__ import annotations

from dataclasses import replace
from typing import Protocol, Sequence

from .models import (
    ContextMap,
    EvidenceState,
    IssueSeverity,
    PipelineResult,
    PipelineStage,
    RefinementRequest,
    RepositoryArtifact,
    SourceRecord,
    TraceEvent,
    TraceReceipt,
    ValidationIssue,
    ValidationReport,
)


class RefinementAdapter(Protocol):
    """Semantic adapter used by the governed pipeline.

    An implementation may call a hosted model, local model, rules engine, or
    human-in-the-loop workflow. The pipeline remains provider-agnostic.
    """

    def map_context(
        self, request: RefinementRequest, sources: Sequence[SourceRecord]
    ) -> ContextMap: ...

    def refine(
        self,
        request: RefinementRequest,
        context_map: ContextMap,
        sources: Sequence[SourceRecord],
    ) -> Sequence[RepositoryArtifact]: ...

    def critique(
        self,
        request: RefinementRequest,
        context_map: ContextMap,
        artifacts: Sequence[RepositoryArtifact],
        sources: Sequence[SourceRecord],
    ) -> ValidationReport: ...


class RepositoryRefinementPipeline:
    """Evidence-governed conversion of retrieved context into repo artifacts."""

    def __init__(self, adapter: RefinementAdapter) -> None:
        self._adapter = adapter

    def run(
        self, request: RefinementRequest, sources: Sequence[SourceRecord]
    ) -> PipelineResult:
        events: list[TraceEvent] = [
            TraceEvent(
                PipelineStage.RECEIVE,
                "Accepted refinement request.",
                {"request_id": request.request_id},
            )
        ]

        if not sources:
            raise ValueError("at least one source is required")
        self._assert_unique_source_ids(sources)
        events.append(
            TraceEvent(
                PipelineStage.RETRIEVE,
                "Bound immutable source records to the request.",
                {"source_count": len(sources)},
            )
        )

        normalized_sources = tuple(self._normalize_source(source) for source in sources)
        events.append(
            TraceEvent(
                PipelineStage.NORMALIZE,
                "Normalized source text without changing source identity or digest.",
            )
        )

        context_map = self._adapter.map_context(request, normalized_sources)
        self._validate_context_map(context_map, normalized_sources)
        events.append(
            TraceEvent(
                PipelineStage.MAP,
                "Constructed a source-closed context map.",
                {
                    "entity_count": len(context_map.entities),
                    "ambiguity_count": len(context_map.ambiguities),
                },
            )
        )

        artifacts = tuple(
            self._adapter.refine(request, context_map, normalized_sources)
        )
        events.append(
            TraceEvent(
                PipelineStage.REFINE,
                "Produced candidate repository artifacts.",
                {"artifact_count": len(artifacts)},
            )
        )

        structural_report = self._validate_artifacts(artifacts, normalized_sources)
        adapter_report = self._adapter.critique(
            request, context_map, artifacts, normalized_sources
        )
        validation = self._combine_reports(structural_report, adapter_report)
        events.append(
            TraceEvent(
                PipelineStage.VALIDATE,
                "Validated paths, source closure, evidence states, and adapter critique.",
                {
                    "approved": validation.approved,
                    "issue_count": len(validation.issues),
                },
            )
        )

        approved_artifacts = artifacts if validation.approved else ()
        events.append(
            TraceEvent(
                PipelineStage.EMIT,
                "Released artifacts for repository writing."
                if validation.approved
                else "Withheld artifacts because validation failed.",
                {"released_count": len(approved_artifacts)},
            )
        )

        warnings = tuple(
            issue.message
            for issue in validation.issues
            if issue.severity is IssueSeverity.WARNING
        )
        events.append(TraceEvent(PipelineStage.TRACE, "Created trace receipt."))
        receipt = TraceReceipt(
            request_id=request.request_id,
            succeeded=validation.approved,
            events=tuple(events),
            artifact_paths=tuple(artifact.path for artifact in approved_artifacts),
            source_digests={source.source_id: source.digest for source in sources},
            warnings=warnings,
        )

        return PipelineResult(
            request=request,
            context_map=context_map,
            artifacts=approved_artifacts,
            validation=validation,
            receipt=receipt,
        )

    @staticmethod
    def _assert_unique_source_ids(sources: Sequence[SourceRecord]) -> None:
        ids = [source.source_id for source in sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source_id values must be unique")

    @staticmethod
    def _normalize_source(source: SourceRecord) -> SourceRecord:
        # Normalization is a working projection. The original digest remains the
        # provenance anchor so transformations do not impersonate the source.
        normalized = "\n".join(line.rstrip() for line in source.content.splitlines()).strip()
        return replace(source, content=normalized)

    @staticmethod
    def _validate_context_map(
        context_map: ContextMap, sources: Sequence[SourceRecord]
    ) -> None:
        source_ids = {source.source_id for source in sources}
        unknown = set(context_map.source_ids) - source_ids
        if unknown:
            raise ValueError(f"context map references unknown sources: {sorted(unknown)}")

    @staticmethod
    def _validate_artifacts(
        artifacts: Sequence[RepositoryArtifact], sources: Sequence[SourceRecord]
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        known_source_ids = {source.source_id for source in sources}
        seen_paths: set[str] = set()

        if not artifacts:
            issues.append(
                ValidationIssue(IssueSeverity.ERROR, "No repository artifacts were produced.")
            )

        for artifact in artifacts:
            if artifact.path in seen_paths:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "Duplicate artifact path.",
                        artifact_path=artifact.path,
                    )
                )
            seen_paths.add(artifact.path)

            if not artifact.source_ids:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "Artifact has no provenance sources.",
                        artifact_path=artifact.path,
                    )
                )

            for source_id in artifact.source_ids:
                if source_id not in known_source_ids:
                    issues.append(
                        ValidationIssue(
                            IssueSeverity.ERROR,
                            "Artifact references an unknown source.",
                            artifact_path=artifact.path,
                            source_id=source_id,
                        )
                    )

            if artifact.evidence_state is EvidenceState.RUNTIME_ENFORCED:
                if not any(
                    receipt.startswith("validator:")
                    for receipt in artifact.validation_receipts
                ):
                    issues.append(
                        ValidationIssue(
                            IssueSeverity.ERROR,
                            "RUNTIME_ENFORCED requires a validator receipt.",
                            artifact_path=artifact.path,
                        )
                    )

            if artifact.evidence_state is EvidenceState.COUNTERFACTUALLY_VALIDATED:
                if not any(
                    receipt.startswith("counterfactual:")
                    for receipt in artifact.validation_receipts
                ):
                    issues.append(
                        ValidationIssue(
                            IssueSeverity.ERROR,
                            "COUNTERFACTUALLY_VALIDATED requires a counterfactual receipt.",
                            artifact_path=artifact.path,
                        )
                    )

        approved = not any(issue.severity is IssueSeverity.ERROR for issue in issues)
        return ValidationReport(approved=approved, issues=tuple(issues))

    @staticmethod
    def _combine_reports(
        first: ValidationReport, second: ValidationReport
    ) -> ValidationReport:
        issues = first.issues + second.issues
        approved = (
            first.approved
            and second.approved
            and not any(issue.severity is IssueSeverity.ERROR for issue in issues)
        )
        return ValidationReport(approved=approved, issues=issues)
