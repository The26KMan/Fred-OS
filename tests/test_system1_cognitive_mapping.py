from fred_os.systems.system1_cognitive_mapping import CognitiveMapper, System1CognitiveMappingPlugin
from fred_os.systems.system1_neural_overlay import System1NeuralOverlay


class RuntimeConfigStub:
    values = {
        "systems.s1.max_concepts": 12,
        "systems.s1.min_phrase_chars": 3,
        "systems.s1.max_ngram": 3,
        "systems.s1.max_edges_per_node": 5,
        "systems.s1.emergence_threshold": 0.48,
        "systems.s1.completeness_retrieval_floor": 0.75,
        "systems.s1.neural_overlay_enabled": True,
    }

    def get(self, key, default=None):
        return self.values.get(key, default)


class MemoryStub:
    class Receipt:
        hits = ({"deeplink": "deeplink://kamahni/fred-os/test@r1-a#f1-b", "authority": "implementation"},)

    def recall(self, query, limit=3):
        return self.Receipt()


def test_non_repetitive_prompt_produces_concepts_without_exception():
    result = CognitiveMapper().process("How can System-OS use a semantic memory lake and DeepLinks to preserve evidence?")
    assert result["enriched_concepts"]
    assert result["uncertainty"]["score"] < 1
    assert result["mermaid"].startswith("graph TD")


def test_empty_input_returns_safe_no_concept_result():
    result = CognitiveMapper().process("")
    assert result["enriched_concepts"] == []
    assert result["uncertainty"]["score"] == 1.0
    assert "No concepts" in result["uncertainty"]["gaps"][0]


def test_cross_domain_map_emits_kpi_and_reasoning_paths():
    result = CognitiveMapper().process("What happens when we divide by zero and compare it to quantum superposition before measurement?")
    domains = set(result["kpi_signals"]["domains_covered"])
    assert {"mathematics", "physics"} <= domains
    assert result["kpi_signals"]["trajectory_fit_contribution"] >= 0
    assert result["multi_hop_connections"]


def test_plugin_retrieves_context_but_never_auto_writes_memory():
    plugin = System1CognitiveMappingPlugin(RuntimeConfigStub())
    plugin.initialize()
    result = plugin.process({"text": "Design semantic memory provenance with DeepLinks."}, {"memory": MemoryStub()})
    assert result["memory_context"][0]["deeplink"].startswith("deeplink://")
    assert result["memory_write_candidate"]["status"] == "candidate_only"
    assert result["neural_telemetry"]["model"] == "bounded_neurodynamic_telemetry"


def test_overlay_stays_bounded_and_adjustable():
    overlay = System1NeuralOverlay()
    for _ in range(100):
        frame = overlay.update(kpi_signals={"completeness_contribution": 1.0, "trajectory_fit_contribution": 0.2}, uncertainty={"score": 0.0})
    overlay.apply_field_adjustment({"leak_delta": 0.2, "channel_scales": [{"from_system": "S2", "scale": 0.5}]})
    assert 0.0 <= frame["potential"] <= 1.0
    assert 0.0 <= overlay.state.leak <= 1.0
