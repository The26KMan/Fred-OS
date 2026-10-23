"""Offline, plan-only security preflight (reference: ``fred-security-preflight``).

Machine contract (reference ``references/contract.md``):

    Input:  ScanRequest(kind, target, sensitivity,
                        owner_approved_external_submission, reason)
    Output: ScanPlan(target_kind, target, recommended_interface, status,
                     can_dispatch=false, evidence_status=NOT_SCANNED, note)

The plan never contains tokens, credential values, direct API invocations,
provider claims, or synthetic vulnerability findings. ``NOT_SCANNED`` is the
only valid local status. A positive candidate result is **not** proof of
security; it is not a finding, a receipt or an approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

#: Target kinds the offline planner recognises.
SUPPORTED_TARGET_KINDS: tuple[str, ...] = (
    "public_skill",
    "public_mcp_repo",
    "public_package",
    "public_web_page",
    "deployed_agent",
)

#: Only public material may be planned for external submission.
SUBMITTABLE_SENSITIVITIES: tuple[str, ...] = ("public",)

#: The only valid status for a local preflight.
EVIDENCE_STATUS_NOT_SCANNED = "NOT_SCANNED"

STATUS_ELIGIBLE = "ELIGIBLE_CANDIDATE"
STATUS_BLOCKED = "BLOCKED"

#: Design-contract mapping to the optional external provider interface.
PROVIDER_INTERFACES: dict[str, str] = {
    "public_skill": "superagent_sh.scan_skill",
    "public_mcp_repo": "superagent_sh.scan_mcp",
    "public_package": "superagent_sh.scan_package",
    "public_web_page": "superagent_sh.get_context_score",
    "deployed_agent": "superagent_sh.red_team_report",
}


@dataclass(frozen=True)
class ScanRequest:
    kind: str
    target: str
    sensitivity: str = "public"
    owner_approved_external_submission: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ScanPlan:
    target_kind: str
    target: str
    recommended_interface: str
    status: str
    can_dispatch: bool
    evidence_status: str
    note: str


class DispatchDisabled(RuntimeError):
    """Raised by the disabled dispatch path; there is no local scan executor."""


def scan_request_from_mapping(payload: Mapping[str, Any]) -> ScanRequest:
    return ScanRequest(
        kind=str(payload.get("kind", "")),
        target=str(payload.get("target", "")),
        sensitivity=str(payload.get("sensitivity", "public")),
        owner_approved_external_submission=bool(payload.get("owner_approved_external_submission", False)),
        reason=str(payload.get("reason", "")),
    )


def plan_security_check(request: ScanRequest | Mapping[str, Any]) -> ScanPlan:
    """Produce a plan-only eligibility record. Never contacts a provider."""
    if isinstance(request, Mapping):
        request = scan_request_from_mapping(request)

    kind = str(request.kind or "").strip()
    target = str(request.target or "").strip()
    sensitivity = str(request.sensitivity or "public").strip()

    def blocked(note: str) -> ScanPlan:
        return ScanPlan(
            target_kind=kind,
            target=target,
            recommended_interface=PROVIDER_INTERFACES.get(kind, "unmapped"),
            status=STATUS_BLOCKED,
            can_dispatch=False,
            evidence_status=EVIDENCE_STATUS_NOT_SCANNED,
            note=note,
        )

    if kind not in SUPPORTED_TARGET_KINDS:
        return blocked(
            f"unsupported target kind '{kind}'; supported: {', '.join(SUPPORTED_TARGET_KINDS)}"
        )
    if not target:
        return blocked("no target locator was supplied")
    if sensitivity not in SUBMITTABLE_SENSITIVITIES:
        return blocked(
            f"sensitivity '{sensitivity}' is not submittable; only {', '.join(SUBMITTABLE_SENSITIVITIES)} may be planned"
        )
    if not request.owner_approved_external_submission:
        return blocked("owner approval for external submission has not been recorded")

    return ScanPlan(
        target_kind=kind,
        target=target,
        recommended_interface=PROVIDER_INTERFACES[kind],
        status=STATUS_ELIGIBLE,
        can_dispatch=False,
        evidence_status=EVIDENCE_STATUS_NOT_SCANNED,
        note=(
            "eligible candidate for owner-reviewed external assessment; a local plan is not a scan, "
            "not a finding and not an approval"
        ),
    )


def dispatch_security_scan(plan: ScanPlan, *, trusted_executor: Any = None) -> None:
    """Disabled by design — all scan dispatches are off in this release.

    Later execution requires a real authenticated connector, an independent
    trusted policy decision, and evidence returned by the provider.
    """
    raise DispatchDisabled(
        "security-scan dispatch is disabled: no authenticated connector, no trusted executor "
        "and no provider evidence are present in this runtime"
    )
