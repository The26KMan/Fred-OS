"""System-2: Concept Association adapter.

System-2 consumes an immutable reference to a validated S1 Graph Envelope and
proposes bounded, non-mutating association overlays. Proposal and admission are
separate stages; every emitted association is ``inferred``; the source graph is
never mutated.

Input contract:  ``schema://S1/graph-envelope/1.0``
Output contract: ``schema://S2/association-envelope/1.0``

The ported runtime lives in ``system2_concept_association``; the shared
digest-pinned controller lives in ``neurodynamic_kernel``.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from fred_os.runtime.contracts import SystemPlugin

from .graph_envelope import build_graph_envelope, canonical_digest, validate_graph_envelope
from .system2_concept_association import (
    AssociationConfig,
    admit,
    apply_association_control_policy,
    build_overlay,
    evaluate_color_algebraics,
    expand_external_neighbors,
    propose,
    select_explanatory_associations,
    update_neurodynamic_state_explicit,
)

ENVELOPE_VERSION = "1.0"
PAYLOAD_SCHEMA = "schema://S2/association-overlay/1.0"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def association_config_from_runtime(config: Any) -> AssociationConfig:
    """Build the S2 association config from frozen runtime configuration."""
    get = config.get
    return AssociationConfig(
        max_path_depth=int(get("systems.s2.max_path_depth", 4)),
        min_path_confidence=float(get("systems.s2.min_path_confidence", 0.35)),
        association_threshold=float(get("systems.s2.association_threshold", 0.60)),
        max_candidates=int(get("systems.s2.max_candidates", 256)),
        max_output_associations=int(get("systems.s2.max_output_associations", 64)),
        max_external_neighbors=int(get("systems.s2.max_external_neighbors", 8)),
        transitive_decay=float(get("systems.s2.transitive_decay", 0.85)),
        feedback_cycle_penalty=float(get("systems.s2.feedback_cycle_penalty", 0.65)),
        min_novelty=float(get("systems.s2.min_novelty", 0.35)),
    )


class System2ConceptAssociation(SystemPlugin):
    """Bounded association overlay over an immutable S1 graph envelope."""

    SYSTEM_ID = "S2"
    SYSTEM_NAME = "Concept Association"
    HARD_DEPENDENCIES = ("S1",)

    def initialize(self) -> None:
        self.association_config = association_config_from_runtime(self.config)
        self.harmony_tau = float(self.config.get("systems.s2.harmony_tau", 35.0))
        self.field_enabled = bool(self.config.get("systems.s2.field_enabled", True))
        self.runtime_profile = str(self.config.get("meta.profile", "development"))
        self.field_state: dict[str, Any] | None = None
        self.turn = 0
        self.initialized = True

    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = payload or {}
        self.turn += 1
        s1_output = context.get("s1") if isinstance(context, Mapping) else None

        envelope = payload.get("graph_envelope")
        if envelope is None and isinstance(s1_output, Mapping):
            envelope = build_graph_envelope(
                s1_output,
                source_id=f"s1.turn.{self.turn}",
                graph_id=f"graph-s1-turn-{self.turn}",
                revision=1,
                runtime_profile=self.runtime_profile,
            )

        if not isinstance(envelope, Mapping):
            return self._empty("no_source_graph", "no S1 graph envelope was supplied")

        violations = validate_graph_envelope(envelope)
        if violations:
            return self._empty("invalid_source_graph", "source graph envelope failed validation", violations=violations)

        control = self._advance_field(envelope, s1_output)
        effective = apply_association_control_policy(self.association_config, control["control_policy"])
        candidate_set = propose(envelope, effective)
        ledger = admit(candidate_set, effective)
        overlay = build_overlay(ledger, overlay_id=f"s2-overlay-{envelope['graph_id']}")

        result: dict[str, Any] = {
            "system_id": self.SYSTEM_ID,
            "system_name": self.SYSTEM_NAME,
            "status": "association_overlay",
            "source_graph_ref": overlay["source_graph_ref"],
            "association_envelope": {
                "envelope_version": ENVELOPE_VERSION,
                "overlay": overlay,
                "validation": {"status": "valid"},
                "content_digest": canonical_digest(overlay),
            },
            "association_overlay": overlay,
            "admission_records": ledger["admission_records"],
            "candidate_count": len(candidate_set["candidates"]),
            "admitted_count": len(ledger["admitted"]),
            "effective_config": asdict(effective),
            "field_control": control["field_control"],
            "execution_receipt": control["execution_receipt"],
            "source_graph_mutated": False,
            "output_schema": PAYLOAD_SCHEMA,
        }

        external = payload.get("external_proposals")
        if external:
            result["external_neighbor_set"] = expand_external_neighbors(envelope, list(external), effective)

        colors = payload.get("colors")
        if isinstance(colors, Mapping) and colors.get("left") and colors.get("right"):
            result["color_relation"] = evaluate_color_algebraics(
                colors["left"], colors["right"], float(colors.get("harmony_tau", self.harmony_tau))
            )

        result["explanatory_selection"] = select_explanatory_associations(
            candidate_set["candidates"], max_output=effective.max_output_associations
        )
        return result

    def _empty(self, status: str, reason: str, *, violations: list[dict[str, str]] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "system_id": self.SYSTEM_ID,
            "system_name": self.SYSTEM_NAME,
            "status": status,
            "reason": reason,
            "association_overlay": None,
            "candidate_count": 0,
            "admitted_count": 0,
            "source_graph_mutated": False,
        }
        if violations:
            result["violations"] = violations
        return result

    def _advance_field(self, envelope: Mapping[str, Any], s1_output: Any) -> dict[str, Any]:
        """Advance S2's own explicit field state through the shared controller."""
        if not self.field_enabled:
            from .system2_concept_association import association_control_policy

            policy = association_control_policy(0.45)
            return {
                "field_state": self.field_state,
                "control_policy": policy,
                "field_control": {"policy": policy, "non_destructive": True},
                "execution_receipt": None,
            }

        load = self._load_metrics(envelope, s1_output)
        demand = load["association_demand"]
        signals = []
        if demand > 0:
            signals.append(
                {
                    "signal_id": f"sig-s1-s2-association-demand-{self.turn}",
                    "source_system": "S1",
                    "target_system": "S2",
                    "signal_type": "association_demand",
                    "value": round(demand, 6),
                    "basis": ["missing_facets", "unresolved_relations"],
                    "authority": "operational",
                }
            )
        result = update_neurodynamic_state_explicit(
            {
                "field_state": self.field_state,
                "load_metrics": load,
                "signals": signals,
                "global_parameters": {"revision": "gp-s2-vnext", "values": {}},
            }
        )
        self.field_state = result["field_state"]
        return {
            "field_state": result["field_state"],
            "control_policy": result["field_control_decision"]["policy"],
            "field_control": {
                "policy": result["field_control_decision"]["policy"],
                "voltage": result["field_state"]["voltage"],
                "step": result["field_state"]["step"],
                "accepted_signals": result["neural_field_capsule"]["accepted_signals"],
                "non_destructive": True,
            },
            "execution_receipt": result["execution_receipt"],
        }

    @staticmethod
    def _load_metrics(envelope: Mapping[str, Any], s1_output: Any) -> dict[str, float]:
        nodes = envelope["payload"]["nodes"]
        edges = envelope["payload"]["edges"]
        situation = s1_output if isinstance(s1_output, Mapping) else {}
        uncertainty = float((situation.get("uncertainty") or {}).get("score", 0.0))
        missing_facets = len(((situation.get("kpi_signals") or {}).get("missing_facets")) or [])
        gaps = len(situation.get("gaps") or [])
        domains = {domain for node in nodes for domain in node.get("domains", [])}
        return {
            "overload": _clamp((len(nodes) + len(edges)) / 40.0),
            "ambiguity": _clamp(uncertainty),
            "novelty": _clamp(len(domains) / max(1, len(nodes))),
            "redundancy": 0.0,
            "governance_restriction": 0.0,
            "association_demand": _clamp(0.20 * missing_facets + 0.15 * gaps),
        }
