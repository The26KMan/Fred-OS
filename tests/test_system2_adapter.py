"""System-2 adapter integration: reference S1 graph envelope -> association overlay."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from fred_os.runtime.config import ConfigLoader
from fred_os.runtime.contracts import CommandEnvelope
from fred_os.runtime.kernel import RuntimeKernel
from fred_os.systems.graph_envelope import build_graph_envelope, validate_graph_envelope
from fred_os.systems.system2_adapter import System2ConceptAssociation

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "system2"


def _config():
    return ConfigLoader.build(root_dir=ROOT, profile="development")


def _s1_output() -> dict:
    return {
        "enriched_concepts": [
            {"normalized_concept": "cognitive mapping", "semantic_domain": "logic", "abstraction_level": 2, "emergence_potential": 0.7},
            {"normalized_concept": "memory of loci", "semantic_domain": "psychology", "abstraction_level": 2, "emergence_potential": 0.6},
            {"normalized_concept": "model context", "semantic_domain": "logic", "abstraction_level": 2, "emergence_potential": 0.5},
        ],
        "multi_hop_connections": [
            {"source": "memory of loci", "target": "cognitive mapping", "weight": 0.9, "reasoning_type": "direct", "hops": 1},
            {"source": "cognitive mapping", "target": "model context", "weight": 0.85, "reasoning_type": "direct", "hops": 1},
        ],
        "uncertainty": {"score": 0.4},
        "kpi_signals": {"missing_facets": ["analogies"]},
        "gaps": [{"type": "missing_facet"}],
    }


# --- graph envelope bridge -------------------------------------------------------


def test_graph_envelope_is_valid_and_typed():
    envelope = build_graph_envelope(_s1_output(), source_id="test")
    assert validate_graph_envelope(envelope) == []
    assert envelope["payload_schema"] == "schema://S1/context-graph/1.0"
    assert envelope["producer"]["system"] == "S1"
    assert {n["id"] for n in envelope["payload"]["nodes"]} == {"cognitive-mapping", "memory-of-loci", "model-context"}
    assert {e["relation"] for e in envelope["payload"]["edges"]} == {"associated-with"}


def test_graph_envelope_detects_digest_tampering():
    envelope = build_graph_envelope(_s1_output(), source_id="test")
    envelope["payload"]["nodes"].append({"id": "extra", "label": "Extra", "type": "concept", "epistemic_state": "source", "salience": 0.1, "activation": 0.0, "confidence": {"value": 0.1, "method": "rule-derived"}, "provenance": [], "domains": ["general"], "attributes": {}})
    codes = {v["code"] for v in validate_graph_envelope(envelope)}
    assert "DIGEST_MISMATCH" in codes


# --- adapter pipeline ------------------------------------------------------------


def test_adapter_emits_inferred_overlay_without_mutating_source():
    adapter = System2ConceptAssociation(_config())
    adapter.initialize()
    envelope = build_graph_envelope(_s1_output(), source_id="test")
    before = copy.deepcopy(envelope)
    result = adapter.process({"graph_envelope": envelope}, {})
    assert envelope == before
    assert result["status"] == "association_overlay"
    assert result["source_graph_mutated"] is False
    assert result["admitted_count"] >= 1
    edge = result["association_overlay"]["edges"][0]
    assert edge["epistemic_state"] == "inferred"
    assert edge["relation"] == "association-reach"
    assert abs(edge["weight"] - 0.65025) < 1e-4


def test_adapter_bridges_live_s1_output_from_context():
    adapter = System2ConceptAssociation(_config())
    adapter.initialize()
    result = adapter.process({"text": "x"}, {"s1": _s1_output()})
    assert result["status"] == "association_overlay"
    assert result["source_graph_ref"]["graph_id"].startswith("graph-s1-turn-")


def test_adapter_accepts_reference_handoff_envelope():
    adapter = System2ConceptAssociation(_config())
    adapter.initialize()
    envelope = json.loads((FIXTURES / "s1_subject_graph_handoff.json").read_text())
    assert validate_graph_envelope(envelope) == []
    result = adapter.process({"graph_envelope": envelope}, {})
    assert result["status"] == "association_overlay"
    assert result["source_graph_mutated"] is False


def test_adapter_rejects_invalid_envelope():
    adapter = System2ConceptAssociation(_config())
    adapter.initialize()
    result = adapter.process({"graph_envelope": {"graph_id": "broken"}}, {})
    assert result["status"] == "invalid_source_graph"
    assert result["violations"]


def test_adapter_handles_missing_source_graph():
    adapter = System2ConceptAssociation(_config())
    adapter.initialize()
    result = adapter.process({}, {})
    assert result["status"] == "no_source_graph"
    assert result["association_overlay"] is None


def test_adapter_field_state_advances_and_accepts_s1_coupling():
    adapter = System2ConceptAssociation(_config())
    adapter.initialize()
    first = adapter.process({"text": "x"}, {"s1": _s1_output()})
    second = adapter.process({"text": "x"}, {"s1": _s1_output()})
    assert first["field_control"]["step"] == 1
    assert second["field_control"]["step"] == 2
    signals = first["field_control"]["accepted_signals"]
    assert any(s["signal_type"] == "association_demand" and s["source_system"] == "S1" for s in signals)


# --- kernel integration ----------------------------------------------------------


def test_kernel_turn_produces_s2_association_overlay():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        result = kernel.process_turn("Design a semantic memory migration with DeepLinks and evidence provenance.")
        s2 = result["outputs"]["S2"]
        assert s2["system_id"] == "S2"
        assert s2["status"] == "association_overlay"
        assert s2["association_overlay"]["source_graph_ref"]["schema_uri"] == "schema://S1/context-graph/1.0"
        assert s2["source_graph_mutated"] is False
    finally:
        kernel.close()


def test_kernel_exposes_s2_capability():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        names = {c["name"] for c in kernel.list_capabilities()}
        assert "s2.concept_association" in names
        result = kernel.dispatch(
            CommandEnvelope(
                command_id="cmd-s2-test",
                target_capability="s2.concept_association",
                payload={"input": "Design a semantic memory migration with evidence provenance."},
                session_id=kernel.current_capsule.session_id,
                idempotency_key="ik-s2-test",
            )
        )
        assert result.outputs["outputs"]["S2"]["status"] == "association_overlay"
    finally:
        kernel.close()
