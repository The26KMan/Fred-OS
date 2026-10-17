"""System-2 Concept Association reference runtime tests.

Ported from the S2 draft.5 unified bundle. These cover the bounded, non-mutating
association runtime, Color Algebraics, external-neighbor admission, BPT sparse
selection, typed path composition, and the explicit-state field controller.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from fred_os.systems.system2_concept_association import (
    AssociationConfig,
    DEFAULT_CHANNELS,
    NeurodynamicConfig,
    accept_field_adjustment,
    admit,
    apply_association_control_policy,
    association_control_policy,
    build_overlay,
    canonical_digest,
    evaluate_color_algebraics,
    expand_external_neighbors,
    propose,
    select_explanatory_associations,
    update_neurodynamic_state,
    update_neurodynamic_state_explicit,
)

FIXTURES = Path(__file__).parent / "fixtures" / "system2"
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas" / "system2"


def _envelope() -> dict:
    return {
        "graph_id": "g",
        "graph_revision": 1,
        "payload_schema": "schema://S1/context-graph/1.0",
        "content_digest": "sha256:" + "1" * 64,
        "payload": {
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {"id": "e1", "source": "a", "target": "b", "confidence": {"value": 0.9}},
                {"id": "e2", "source": "b", "target": "c", "confidence": {"value": 0.9}},
            ],
        },
    }


def _color(signature_id: str, coordinates: list[float], uncertainty: float = 0.1, space: str = "CIELAB-D65") -> dict:
    return {
        "signature_id": signature_id,
        "space": space,
        "coordinates": coordinates,
        "producer": {"system": "S4", "operation": "COLOR.ENCODE", "version": "1"},
        "normalization": {"method": "declared"},
        "uncertainty": uncertainty,
    }


# --- bounded association runtime -------------------------------------------------


def test_nonmutation_and_inference():
    envelope = _envelope()
    before = copy.deepcopy(envelope)
    candidate_set = propose(envelope, AssociationConfig(association_threshold=0.5))
    assert envelope == before
    assert candidate_set["candidates"][0]["epistemic_state"] == "inferred"


def test_admission_and_overlay():
    config = AssociationConfig(association_threshold=0.5)
    ledger = admit(propose(_envelope(), config), config)
    overlay = build_overlay(ledger, "o1")
    assert overlay["edges"][0]["source"] == "a"
    assert overlay["edges"][0]["target"] == "c"


def test_bounded_reject():
    config = AssociationConfig(association_threshold=0.99)
    candidate_set = propose(_envelope(), config)
    ledger = admit(candidate_set, config)
    assert ledger["admitted"] == []
    assert len(ledger["admission_records"]) == len(candidate_set["candidates"])


def test_feedback_penalty_and_typing():
    graph = {
        "graph_id": "g",
        "graph_revision": 1,
        "payload_schema": "s",
        "content_digest": "sha256:" + "1" * 64,
        "payload": {
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {"id": "e1", "source": "a", "target": "b", "relation": "part-of", "confidence": {"value": 1}},
                {"id": "e2", "source": "b", "target": "c", "relation": "refers-to", "confidence": {"value": 1}},
            ],
        },
    }
    candidate = propose(graph, AssociationConfig(association_threshold=0.1))["candidates"][0]
    assert candidate["relation"] == "provenance-feedback"
    assert abs(candidate["score"] - 0.5525) < 1e-9


def test_reference_handoff_depth_and_neighbors():
    graph = json.loads((FIXTURES / "s1_subject_graph_handoff.json").read_text())
    config = AssociationConfig(association_threshold=0.55, min_path_confidence=0.25)
    closed = propose(graph, config)["candidates"]
    assert any(c["relation"] == "mnemonic-reach" and c["target"] == "node_context_graph" for c in closed)
    assert any(c["support"]["feedback_path"] for c in closed)
    proposals = [
        {"proposal_id": "spatial", "label": "Spatial Retrieval", "origin": {"type": "model-prior", "source_ref": None}, "anchors": ["node_memory_of_loci", "node_model_context"], "relation_hypotheses": [{"source": "node_memory_of_loci", "target": "spatial", "relation": "enables"}], "score": 0.86, "novelty": 0.82, "explanatory_gain": 0.92, "estimated_token_cost": 18},
        {"proposal_id": "compress", "label": "Semantic Compression", "origin": {"type": "model-prior", "source_ref": None}, "anchors": ["node_cognitive_mapping", "node_model_context"], "relation_hypotheses": [{"source": "node_cognitive_mapping", "target": "compress", "relation": "enables"}], "score": 0.81, "novelty": 0.74, "explanatory_gain": 0.88, "estimated_token_cost": 16},
        {"proposal_id": "lineage", "label": "Evidence Lineage", "origin": {"type": "retrieved-source", "source_ref": "spec://S1/cognitive-mapping/0.3.0-draft.6"}, "anchors": ["node_source_graph", "node_graph_envelope"], "relation_hypotheses": [{"source": "node_source_graph", "target": "lineage", "relation": "supports"}], "score": 0.91, "novelty": 0.71, "explanatory_gain": 0.95, "estimated_token_cost": 14},
        {"proposal_id": "bitemporal", "label": "Bitemporal Identity", "origin": {"type": "cross-graph", "source_ref": "spec://TSC/temporal-sphere/0.3.0-draft.1"}, "anchors": ["node_temporal_anchor", "node_graph_envelope"], "relation_hypotheses": [{"source": "node_temporal_anchor", "target": "bitemporal", "relation": "supports"}], "score": 0.89, "novelty": 0.86, "explanatory_gain": 0.94, "estimated_token_cost": 20},
    ]
    external = expand_external_neighbors(graph, proposals, config)
    assert len(external["external_candidates"]) == 4
    selected = select_explanatory_associations(external["external_candidates"], 3)
    assert len(selected["selected"]) == 3
    assert len(selected["deferred"]) == 1


# --- Color Algebraics ------------------------------------------------------------


def test_color_identity_distance():
    relation = evaluate_color_algebraics(_color("a", [50, 10, -5]), _color("b", [50, 10, -5]))
    assert relation["delta_e"] == 0
    assert relation["harmony"] == 1
    assert relation["semantic_identity_claimed"] is False


def test_color_distance_and_uncertainty():
    relation = evaluate_color_algebraics(_color("a", [50, 0, 0], 0.2), _color("b", [60, 0, 0], 0.3), 10)
    assert relation["delta_e"] == 10
    assert abs(relation["uncertainty"] - 0.44) < 1e-9


def test_color_space_mismatch_fails_closed():
    import pytest

    with pytest.raises(ValueError, match="COLOR_SPACE_CONVERSION_REQUIRED"):
        evaluate_color_algebraics(_color("a", [0, 0, 0]), _color("b", [0, 0, 0], space="sRGB"))


# --- external neighbors ----------------------------------------------------------


def test_external_neighbor_admitted_without_mutation():
    graph = json.loads((FIXTURES / "core_subjects_graph.json").read_text())
    before = copy.deepcopy(graph)
    proposal = {"proposal_id": "p1", "label": "Spatial Retrieval", "origin": {"type": "model-prior", "source_ref": None}, "anchors": ["memory_of_loci", "model_context"], "relation_hypotheses": [{"source": "memory_of_loci", "target": "p1", "relation": "enables"}], "score": 0.85, "novelty": 0.8, "explanatory_gain": 0.9, "estimated_token_cost": 20}
    result = expand_external_neighbors(graph, [proposal], AssociationConfig())
    assert graph == before
    assert len(result["external_candidates"]) == 1
    assert result["external_candidates"][0]["epistemic_state"] == "inferred"


def test_retrieved_source_requires_reference():
    graph = json.loads((FIXTURES / "core_subjects_graph.json").read_text())
    proposal = {"label": "X", "origin": {"type": "retrieved-source"}, "anchors": ["model_context"], "score": 0.9, "novelty": 0.9}
    result = expand_external_neighbors(graph, [proposal], AssociationConfig())
    assert result["external_candidates"] == []
    assert "MISSING_SOURCE_REF" in result["admission_records"][0]["reason_codes"]


def test_duplicate_and_invalid_anchor_rejected():
    graph = json.loads((FIXTURES / "core_subjects_graph.json").read_text())
    proposals = [
        {"label": "Model Context", "origin": {"type": "model-prior"}, "anchors": ["model_context"], "score": 0.9, "novelty": 0.9},
        {"label": "X", "origin": {"type": "model-prior"}, "anchors": ["missing"], "score": 0.9, "novelty": 0.9},
    ]
    result = expand_external_neighbors(graph, proposals, AssociationConfig())
    assert len(result["external_candidates"]) == 0


def test_bpt_selection_prefers_cheaper_explanatory_gain():
    candidates = [
        {"candidate_id": "a", "score": 0.9, "novelty": 0.9, "explanatory_gain": 0.9, "estimated_token_cost": 30},
        {"candidate_id": "b", "score": 0.8, "novelty": 0.8, "explanatory_gain": 0.8, "estimated_token_cost": 10},
    ]
    result = select_explanatory_associations(candidates, 1)
    assert result["selected"][0]["candidate_id"] == "b"


# --- controller ------------------------------------------------------------------


def test_critical_policy_disables_external_expansion():
    config = apply_association_control_policy(AssociationConfig(), association_control_policy(0.95))
    graph = {"graph_id": "g", "graph_revision": 0, "content_digest": "sha256:" + "1" * 64, "payload_schema": "schema://S1/context-graph/1.0", "payload": {"nodes": [{"id": "a", "label": "A"}], "edges": []}}
    proposals = [{"proposal_id": f"p{i}", "label": f"X{i}", "anchors": ["a"], "origin": {"type": "model-prior"}, "score": 0.9, "novelty": 0.9} for i in range(3)]
    result = expand_external_neighbors(graph, proposals, config)
    assert config.max_external_neighbors == 0
    assert result["external_candidates"] == []
    assert all("FIELD_POLICY_EXTERNAL_EXPANSION_DISABLED" in r["reason_codes"] for r in result["admission_records"])


def test_explicit_field_long_horizon_no_boundary_clamp():
    state = None
    history = []
    load = {"overload": 0.32, "ambiguity": 0.82, "novelty": 0.88, "redundancy": 0.18, "governance_restriction": 0.22, "association_demand": 0.92}
    for _ in range(500):
        result = update_neurodynamic_state_explicit({"field_state": state, "load_metrics": load})
        state = result["field_state"]
        history.append(state["voltage"])
    assert state["step"] == 500
    assert sum(v in (0, 1) for v in history) == 0
    assert max(history[-25:]) - min(history[-25:]) < 0.002
    assert 0.18 < history[-1] < 0.82


def test_capsule_dynamic_values_are_bounded():
    capsule = update_neurodynamic_state(
        0.73,
        DEFAULT_CHANNELS,
        {"overload": 0.8, "ambiguity": 0.9, "novelty": 0.7, "redundancy": 0.6, "governance_restriction": 0.4, "association_demand": 1.0},
    )
    assert 0.0 <= capsule["neural_state"]["V"] <= 1.0
    assert capsule["model_semantics"]["biological_fidelity_claimed"] is False
    for channel in capsule["channels"]:
        assert 0.0 <= channel["a"] <= 1.0
        assert 0.0 <= channel["g"] <= 1.0


def test_overload_closes_exploration_channels():
    low = update_neurodynamic_state(0.65, DEFAULT_CHANNELS, {"overload": 0, "ambiguity": 1, "novelty": 1, "association_demand": 1})
    high = update_neurodynamic_state(0.65, DEFAULT_CHANNELS, {"overload": 1, "ambiguity": 1, "novelty": 1, "redundancy": 1, "governance_restriction": 1, "association_demand": 1})
    low_by_role = {c["role"]: c for c in low["channels"]}
    high_by_role = {c["role"]: c for c in high["channels"]}
    for role in ("ambiguity", "color_algebraics", "external_neighbor"):
        assert high_by_role[role]["a"] < low_by_role[role]["a"]
        assert high_by_role[role]["alpha"] == 0.0


def test_leak_only_recovery_moves_voltage_toward_rest():
    config = NeurodynamicConfig(v_rest=0.45, leak=0.2, dt=0.1)
    high = update_neurodynamic_state(0.8, [], {}, config)["neural_state"]["V"]
    low = update_neurodynamic_state(0.2, [], {}, config)["neural_state"]["V"]
    assert high < 0.8
    assert low > 0.2


def test_policy_tightens_monotonically_at_saturation():
    stable = association_control_policy(0.50)
    saturated = association_control_policy(0.80)
    critical = association_control_policy(0.95)
    assert stable["max_candidates"] > saturated["max_candidates"] > critical["max_candidates"]
    assert stable["min_compound_confidence"] < critical["min_compound_confidence"]
    assert critical["max_external_neighbors"] == 0
    assert critical["non_destructive"] is True


def test_policy_application_is_non_destructive():
    base = AssociationConfig()
    before = copy.deepcopy(base)
    effective = apply_association_control_policy(base, association_control_policy(0.95))
    assert base == before
    assert effective.max_path_depth == 1
    assert effective.max_candidates == 24
    assert effective.min_path_confidence == 0.75


def test_field_adjustments_fail_closed_and_are_bounded():
    import pytest

    with pytest.raises(ValueError, match="UNAUTHORIZED"):
        accept_field_adjustment(DEFAULT_CHANNELS, {"authorized": False})
    original = copy.deepcopy(DEFAULT_CHANNELS)
    adjusted = accept_field_adjustment(
        DEFAULT_CHANNELS,
        {"adjustment_id": "adj-1", "issuer": "S12", "authorized": True, "target_roles": ["external_neighbor"], "g_scale": 9, "alpha_scale": 0.1, "beta_scale": 9},
    )
    assert DEFAULT_CHANNELS == original
    target = next(c for c in adjusted if c["role"] == "external_neighbor")
    assert target["g"] == 1.0
    assert target["alpha_base"] <= 1.0
    assert target["beta_base"] == 1.0


def test_color_algebraics_remains_epistemically_separate():
    relation = evaluate_color_algebraics(_color("a", [50, 10, 4], 0.1), _color("b", [52, 12, 3], 0.2))
    capsule = update_neurodynamic_state(0.55, DEFAULT_CHANNELS, {"ambiguity": relation["uncertainty"], "novelty": 1 - relation["harmony"], "association_demand": 0.7})
    assert relation["epistemic_state"] == "inferred"
    assert relation["semantic_identity_claimed"] is False
    assert "color_algebraics" in {c["role"] for c in capsule["channels"]}


def test_capsule_and_policy_conform_to_contracts():
    capsule_schema = json.loads((SCHEMAS / "neural_field_capsule.schema.json").read_text())
    policy_schema = json.loads((SCHEMAS / "association_control_policy.schema.json").read_text())
    capsule = update_neurodynamic_state(0.45, DEFAULT_CHANNELS, {})
    assert set(capsule_schema["required"]) - set(capsule) == set()
    assert set(policy_schema["required"]) - set(capsule["control_policy"]) == set()
    assert capsule["type"] == capsule_schema["properties"]["type"]["const"]
    assert capsule["system"] == capsule_schema["properties"]["system"]["const"]
    assert capsule["control_policy"]["operating_region"] in policy_schema["properties"]["operating_region"]["enum"]


def test_canonical_digest_is_stable_and_order_independent():
    assert canonical_digest({"b": 1, "a": 2}) == canonical_digest({"a": 2, "b": 1})
    assert canonical_digest({"a": 1}).startswith("sha256:")
