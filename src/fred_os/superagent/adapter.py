"""SA1 — Superagent Integration Fabric adapter.

SA1 is the signalization point that folds the FRED reference materials into a
governed runtime turn. It is **non-mutating**: it reads the turn's structured
outputs and emits an independent supervision record, the registered agent
surfaces, and a plan-only assurance posture. It never dispatches, never holds a
credential and never raises on ordinary input — like S2 it returns a status.

Registered in ``fred_os.systems.adapters.default_plugins`` and enabled through
``[systems] enabled`` in ``config/systemos_base.toml``.
"""
from __future__ import annotations

from typing import Any, Mapping

from fred_os.runtime.contracts import SystemPlugin

from .preflight import plan_security_check, scan_request_from_mapping
from .supervisor import supervise
from .surfaces import surface_summary

STATUS_SUPERVISION_RECORD = "supervision_record"
STATUS_SUPERVISION_ERROR = "supervision_error"


class SuperagentFabric(SystemPlugin):
    """Independent K/P/G supervision over one governed turn, plus agent surfaces."""

    SYSTEM_ID = "SA1"
    SYSTEM_NAME = "Superagent Integration Fabric"
    HARD_DEPENDENCIES = ("S1", "S8")

    def initialize(self) -> None:
        self.external_operations_allowed = bool(
            self.config.get("systems.superagent.external_operations_allowed", False)
        )
        self.initialized = True

    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = payload or {}
        try:
            bundle = self._build_bundle(payload, context if isinstance(context, Mapping) else {})
            report = supervise(bundle, bundle_id=self._bundle_id(context))
        except Exception as exc:  # never break a required route
            return {
                "system_id": self.SYSTEM_ID,
                "system_name": self.SYSTEM_NAME,
                "status": STATUS_SUPERVISION_ERROR,
                "reason": repr(exc),
                "verdict": "UNKNOWN",
                "non_authoritative": True,
                "external_dispatch_enabled": False,
            }

        failing = [item["id"] for item in report["checks"] if item["status"] == "FAIL"]
        result: dict[str, Any] = {
            "system_id": self.SYSTEM_ID,
            "system_name": self.SYSTEM_NAME,
            "status": STATUS_SUPERVISION_RECORD,
            "verdict": report["summary"]["verdict"],
            "supervision": report,
            "failing_checks": failing,
            "learning_record": (
                {
                    "status": "non_authoritative",
                    "proposed_for": "S7 / update-skills review",
                    "failing_checks": failing,
                }
                if failing
                else None
            ),
            "agent_surfaces": surface_summary(),
            "assurance": {
                "status": "NOT_SCANNED",
                "can_dispatch": False,
                "external_dispatch_enabled": self.external_operations_allowed,
                "note": "a local plan is not a scan, a finding or an approval",
            },
            "non_authoritative": True,
            "source_graph_mutated": False,
            "execution_receipt": {
                "component": self.SYSTEM_ID,
                "action": "supervise_turn",
                "non_mutating": True,
                "checks_run": len(report["checks"]),
                "content_digest": report["content_digest"],
            },
        }

        scan_request = payload.get("scan_request")
        if isinstance(scan_request, Mapping):
            plan = plan_security_check(scan_request_from_mapping(scan_request))
            result["assurance_plan"] = {
                "target_kind": plan.target_kind,
                "target": plan.target,
                "recommended_interface": plan.recommended_interface,
                "status": plan.status,
                "can_dispatch": plan.can_dispatch,
                "evidence_status": plan.evidence_status,
                "note": plan.note,
            }
        return result

    def _bundle_id(self, context: Any) -> str:
        """Stable per-turn identity so the record stays deterministic under replay."""
        if isinstance(context, Mapping):
            s1 = context.get("s1")
            if isinstance(s1, Mapping):
                turn_id = (s1.get("context_graph") or {}).get("turn_id") if isinstance(s1.get("context_graph"), Mapping) else None
                if turn_id:
                    return f"turn-{turn_id}"
        return "turn"

    def _build_bundle(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
        """Project the turn's structured outputs into a supervision bundle.

        Anything this turn does not carry stays absent, so the corresponding
        check reports UNKNOWN instead of an invented pass.
        """
        bundle: dict[str, Any] = dict(payload.get("supervision_bundle") or {})

        s1 = context.get("s1")
        sources: list[dict[str, Any]] = []
        if isinstance(s1, Mapping):
            for hit in s1.get("memory_context", ()) or ():
                if isinstance(hit, Mapping) and "rank" in hit:
                    sources.append(
                        {
                            "id": str(hit.get("deeplink") or f"rank-{hit.get('rank')}"),
                            "reference": str(hit.get("deeplink", "")),
                            "authority": str(hit.get("authority", "")),
                        }
                    )
        bundle.setdefault("sources", sources or None)

        s2 = context.get("s2")
        if "overlay" not in bundle:
            overlay = None
            if isinstance(s2, Mapping) and s2.get("status") == "association_overlay":
                raw = s2.get("association_overlay") or {}
                edges = [item for item in raw.get("edges", ()) if isinstance(item, Mapping)]
                overlay = {
                    "source_graph_mutated": bool(s2.get("source_graph_mutated", False)),
                    "associations": [
                        {"id": edge.get("id"), "epistemic_state": edge.get("epistemic_state")}
                        for edge in edges
                    ],
                    "s1_facts": [],
                }
            bundle["overlay"] = overlay

        planning = context.get("task_planning")
        if "plan" not in bundle:
            bundle["plan"] = (
                {"operations": [], "source": "runtime.task_planning"}
                if isinstance(planning, Mapping)
                else None
            )

        bundle.setdefault("security", {"status": "NOT_SCANNED", "source": "local_preflight"})
        return bundle
