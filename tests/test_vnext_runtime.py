from pathlib import Path

from fred_os.provenance import Authority
from fred_os.runtime.kernel import RuntimeKernel


ROOT = Path(__file__).resolve().parents[1]


def test_boot_and_route():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        result = kernel.process_turn("Design a semantic memory migration with DeepLinks.")
        assert result["verdict"].decision == "PASS"
        assert result["outputs"]["S1"]["task_class"] == "systemic"
        assert "S2" in result["outputs"]
        assert result["outputs"]["S8"]["status"] == "kernel_governance_pre_scan"
        assert result["capability_report"]["ready"] is True
    finally:
        kernel.close()


def test_high_stakes_route_fails_closed_without_implemented_qesae():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        result = kernel.process_turn("Provide legal advice for a complex contract dispute.")
        assert result["governance_verdict"].decision == "REVIEW"
        assert result["verdict"].decision == "BLOCK"
        assert result["route"].name == "deep_review"
        assert result["capability_report"]["hard_gate_missing"] == ["S13"]
        assert result["capability_report"]["systems"]["S13"]["maturity"] == "candidate"
        assert "S13" not in result["outputs"]
    finally:
        kernel.close()


def test_candidate_optional_system_is_skipped_without_blocking_creative_route():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        result = kernel.process_turn("Create a warm artistic metaphor for a resilient friendship.")
        assert result["verdict"].decision == "PASS"
        assert result["route"].name == "creative"
        assert result["capability_report"]["optional_unavailable"] == ["S10"]
        assert "S10" not in result["outputs"]
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
