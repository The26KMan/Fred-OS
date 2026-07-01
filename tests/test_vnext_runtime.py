from pathlib import Path

from fred_os.provenance import Authority
from fred_os.runtime.kernel import RuntimeKernel


ROOT = Path(__file__).resolve().parents[1]


def test_boot_and_route_authorizes_declared_default_competencies():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        result = kernel.process_turn("Design a semantic memory migration with DeepLinks.")
        assert result["verdict"].decision == "PASS"
        assert result["route"].key == "default"
        assert result["route"].name == "CHAINING"
        assert result["outputs"]["S1"]["task_class"] == "systemic"
        assert "S2" in result["outputs"]
        assert result["outputs"]["S8"]["status"] == "kernel_governance_pre_scan"
        assert result["capability_report"]["ready"] is True
        assert result["task_competency"]["execution_authorization"]["status"] == "AUTHORIZED"
        assert "design" in result["task_competency"]["task_contract"]["objectives"]
        assert not result["task_competency"]["competency_map"]["missing_required"]
    finally:
        kernel.close()


def test_high_stakes_route_fails_closed_without_implemented_qesae():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        result = kernel.process_turn("Provide legal advice for a complex contract dispute.")
        assert result["governance_verdict"].decision == "REVIEW"
        assert result["verdict"].decision == "BLOCK"
        assert result["route"].key == "deep_review"
        assert result["route"].name == "deep_review"
        assert result["capability_report"]["hard_gate_missing"] == ["S13"]
        assert result["capability_report"]["systems"]["S13"]["maturity"] == "candidate"
        assert result["task_competency"]["execution_authorization"]["status"] == "BLOCKED"
        assert result["task_competency"]["execution_authorization"]["reason"] == "hard_gate_competency_gap"
        assert result["task_competency"]["execution_authorization"]["gaps"] == ["ethical_adaptation"]
        assert "S13" not in result["outputs"]
    finally:
        kernel.close()


def test_candidate_optional_system_is_skipped_without_blocking_creative_route():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        result = kernel.process_turn("Create a warm artistic metaphor for a resilient friendship.")
        assert result["verdict"].decision == "PASS"
        assert result["route"].key == "creative"
        assert result["route"].name == "creative"
        assert result["capability_report"]["optional_unavailable"] == ["S10"]
        assert result["task_competency"]["execution_authorization"]["status"] == "AUTHORIZED"
        assert "S10" not in result["outputs"]
    finally:
        kernel.close()


def test_candidate_provider_cannot_satisfy_hard_gate_readiness():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        candidate = kernel.registry.capability("S13")
        governance = kernel.registry.capability("S8")
        assert candidate.execution_ready is False
        assert candidate.hard_gate_ready is False
        assert governance.execution_ready is True
        assert governance.hard_gate_ready is True
    finally:
        kernel.close()


def test_versioned_memory_returns_locator():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        receipt = kernel.memory.ingest(
            "test-note",
            "Test Note",
            "DeepLinks resolve immutable evidence fragments.",
            Authority.IMPLEMENTATION,
        )
        result = kernel.memory.recall("immutable evidence")
        assert receipt["deeplinks"][0].startswith("deeplink://")
        assert result.hits[0]["deeplink"].startswith("deeplink://")
    finally:
        kernel.close()
