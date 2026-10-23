"""Superagent Integration Fabric (SA1): CaseWeave port, preflight, supervisor, wiring."""
from __future__ import annotations

from pathlib import Path

import pytest

from fred_os.runtime.config import ConfigLoader
from fred_os.runtime.contracts import CommandEnvelope
from fred_os.runtime.kernel import RuntimeKernel
from fred_os.superagent import (
    ACTORS,
    CHECKS,
    DEMO,
    DispatchDisabled,
    ScanRequest,
    SuperagentFabric,
    analyze_case,
    assess_output,
    compose_agency_note,
    dispatch_security_scan,
    get_agent_surface,
    list_agent_surfaces,
    plan_security_check,
    supervise,
    supervise_caseweave,
    tokenize_issue,
)
from fred_os.systems.adapters import default_plugins

ROOT = Path(__file__).resolve().parents[1]


# --- CaseWeave P0 port (reference parity) ----------------------------------------


def test_every_issue_tokenizes_into_six_symbolic_fields():
    for issue in DEMO["issues"]:
        tokens = tokenize_issue(issue)
        assert set(tokens) == {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6"}
        assert all(tokens[field] for field in tokens)
        assert tokens["Q1"]["admission"] == "SOURCE_LINKED"
        assert tokens["Q3"]["primary"], "every issue names at least one primary authority"


def test_unknown_actor_is_blocked():
    with pytest.raises(ValueError):
        compose_agency_note("NOT_AN_AGENCY")


def test_hacla_gets_subsidy_authority_and_not_lahd_citations():
    note = compose_agency_note("HACLA")
    assert "24 CFR 983.261" in note["text"]
    assert "issue LAHD citations" in note["gate"]["actorLimits"]


def test_lahd_is_not_instructed_to_issue_a_voucher():
    note = compose_agency_note("LAHD")
    assert "24 CFR 982" not in note["text"]
    assert note["lawIds"], "LAHD still receives its own code/harassment authorities"
    assert set(note["lawIds"]) <= {"LA_TAHO", "LA_CODE"}


def test_court_defense_is_assigned_to_legal_aid_only():
    primary_actors = {issue["id"]: issue["target"] for issue in DEMO["issues"]}
    assert primary_actors["I-COURT"] == ["NLSLA"]
    assert "Unlawful-detainer defense and service" not in compose_agency_note("HACLA")["text"]
    assert "Unlawful-detainer defense and service" in compose_agency_note("NLSLA")["text"]


def test_default_cross_agency_sharing_is_blocked_without_consent_or_review():
    note = compose_agency_note("HACLA")
    assert note["gate"]["maySend"] is False
    assert note["gate"]["needsRecipientConsent"] is True
    assert note["gate"]["needsHumanApproval"] is True
    assert "NO_AUTOSEND_BY_DESIGN" in note["gate"]["reasons"]
    assert assess_output(note)["status"] == "REVIEW"

    approved = compose_agency_note("HACLA", consent_to_share=True, review_approved=True)
    assert approved["gate"]["needsRecipientConsent"] is False
    assert assess_output(approved) == {"status": "PASS", "errors": []}


def test_medical_evidence_stays_out_of_the_shared_note():
    note = compose_agency_note("HACLA")
    assert "SRC-4" not in note["text"]
    assert "without demanding full medical charts" not in note["text"]
    assert "Disability-related accommodation process (functional verification by secure channel)" in note["text"]


def test_privileged_issue_is_omitted_outside_counsel():
    assert "Attorney-client communications:" not in compose_agency_note("HACLA")["text"]
    assert "Unlawful-detainer defense and service" not in compose_agency_note("LAHD")["text"]


def test_unverified_causal_allegation_remains_alleged():
    alleged = next(issue for issue in DEMO["issues"] if issue["id"] == "I-TAHO")
    assert alleged["status"] == "ALLEGED"
    assert "alleged" in compose_agency_note("LAHD")["text"].lower()


def test_caseweave_is_deterministic():
    assert compose_agency_note("HACLA") == compose_agency_note("HACLA")
    assert analyze_case()["trace"]["autoSend"] is False
    assert analyze_case()["trace"]["synthetic"] is True


# --- offline security preflight ---------------------------------------------------


def test_preflight_blocks_private_and_unapproved_targets():
    private = plan_security_check(
        ScanRequest(kind="public_mcp_repo", target="acme/private", sensitivity="private", owner_approved_external_submission=True)
    )
    assert private.status == "BLOCKED"
    assert private.can_dispatch is False
    assert private.evidence_status == "NOT_SCANNED"

    unapproved = plan_security_check(ScanRequest(kind="public_mcp_repo", target="modelcontextprotocol/servers"))
    assert unapproved.status == "BLOCKED"
    assert "owner approval" in unapproved.note

    unsupported = plan_security_check(ScanRequest(kind="internal_database", target="db://x", owner_approved_external_submission=True))
    assert unsupported.status == "BLOCKED"
    assert unsupported.recommended_interface == "unmapped"


def test_preflight_eligible_candidate_is_still_not_a_scan():
    plan = plan_security_check(
        ScanRequest(
            kind="public_mcp_repo",
            target="modelcontextprotocol/servers",
            owner_approved_external_submission=True,
            reason="Review candidate repository",
        )
    )
    assert plan.status == "ELIGIBLE_CANDIDATE"
    assert plan.recommended_interface == "superagent_sh.scan_mcp"
    assert plan.can_dispatch is False
    assert plan.evidence_status == "NOT_SCANNED"
    assert "not a scan" in plan.note


def test_scan_dispatch_is_disabled_by_design():
    plan = plan_security_check(
        ScanRequest(kind="public_package", target="example-package", owner_approved_external_submission=True)
    )
    with pytest.raises(DispatchDisabled):
        dispatch_security_scan(plan)


# --- agent surfaces ---------------------------------------------------------------


def test_agent_surfaces_cover_the_requested_hosts_and_stay_disabled():
    names = {surface["name"] for surface in list_agent_surfaces()}
    assert {"github", "supabase", "gemini"} <= names
    for name in ("github", "supabase", "gemini"):
        surface = get_agent_surface(name)
        assert surface["enabled"] is False
        assert surface["approval_required"] is True
        assert surface["transport"] == "mcp-streamable-http"
        assert surface["endpoint_path"] == "/mcp"
        assert "sa1.superagent_supervision" in surface["allowed_capabilities"]


def test_unknown_agent_surface_is_rejected():
    with pytest.raises(KeyError):
        get_agent_surface("not-a-host")


# --- supervisor K/P/G checks ------------------------------------------------------


def test_supervisor_reports_every_check_and_flags_missing_evidence():
    report = supervise({}, bundle_id="empty")
    assert [check["id"] for check in report["checks"]] == list(CHECKS)
    assert report["summary"]["verdict"] == "INCOMPLETE"
    assert report["summary"]["unknown"] == len(report["checks"])
    assert report["non_authoritative"] is True
    assert report["content_digest"].startswith("sha256:")


def test_supervisor_fails_a_source_claim_without_a_reference():
    report = supervise({"sources": [{"id": "SRC-1", "reference": ""}]})
    assert _status(report, "K-SOURCE") == "FAIL"


def test_supervisor_keeps_inferred_overlays_distinct_from_s1_facts():
    clean = supervise(
        {
            "overlay": {
                "source_graph_mutated": False,
                "associations": [{"id": "s2e_1", "epistemic_state": "inferred"}],
                "s1_facts": ["n1"],
            }
        }
    )
    assert _status(clean, "K-OVERLAY") == "PASS"

    mutated = supervise(
        {"overlay": {"source_graph_mutated": True, "associations": [], "s1_facts": []}}
    )
    assert _status(mutated, "K-OVERLAY") == "FAIL"

    promoted = supervise(
        {"overlay": {"source_graph_mutated": False, "associations": [{"id": "s2e_1", "epistemic_state": "source"}], "s1_facts": []}}
    )
    assert _status(promoted, "K-OVERLAY") == "FAIL"


def test_supervisor_validates_the_hash_chain_ledger():
    good = supervise(
        {"ledger": {"records": [{"hash": "a", "prev": None}, {"hash": "b", "prev": "a"}]}}
    )
    assert _status(good, "P-LEDGER") == "PASS"

    broken = supervise(
        {"ledger": {"records": [{"hash": "a", "prev": None}, {"hash": "b", "prev": "zzz"}]}}
    )
    assert _status(broken, "P-LEDGER") == "FAIL"


def test_supervisor_baseline_is_fixture_limited_and_never_underperforms():
    good = supervise({"baseline": {"multi_hop": 0.8, "one_hop": 0.7}})
    assert _status(good, "P-BASELINE") == "PASS"
    assert "fixture-limited" in _detail(good, "P-BASELINE")

    bad = supervise({"baseline": {"multi_hop": 0.4, "one_hop": 0.7}})
    assert _status(bad, "P-BASELINE") == "FAIL"


def test_supervisor_blocks_forbidden_external_operations_in_the_plan():
    clean = supervise({"plan": {"operations": [{"id": "op1", "kind": "read_local"}]}})
    assert _status(clean, "G-PLAN") == "PASS"

    forbidden = supervise({"plan": {"operations": [{"id": "op1", "kind": "source_export"}]}})
    assert _status(forbidden, "G-PLAN") == "FAIL"

    unapproved = supervise({"plan": {"operations": [{"id": "op1", "kind": "http_post", "external": True, "approved": False}]}})
    assert _status(unapproved, "G-PLAN") == "FAIL"


def test_supervisor_requires_a_draft_and_not_a_dispatch():
    assert _status(supervise({"note": {"status": "draft", "gate": {"maySend": False}}}), "G-NOSEND") == "PASS"
    assert _status(supervise({"note": {"status": "sent", "gate": {}}}), "G-NOSEND") == "FAIL"
    assert _status(supervise({"note": {"status": "draft", "gate": {"maySend": True}}}), "G-NOSEND") == "FAIL"


def test_supervisor_privacy_fails_when_private_material_reached_the_projection():
    assert _status(supervise({"projection": {"contains": []}}), "G-PRIVACY") == "PASS"
    assert _status(supervise({"projection": {"contains": ["raw-medical-issue:I-RA"]}}), "G-PRIVACY") == "FAIL"


def test_sec_boundary_never_promotes_an_external_claim_without_evidence():
    assert _status(supervise({"security": {"status": "NOT_SCANNED"}}), "SEC-BOUNDARY") == "PASS"

    unpromotable = supervise({"security": {"status": "CLEAN", "provider": "superagent.sh"}})
    assert _status(unpromotable, "SEC-BOUNDARY") == "FAIL"
    assert "run_id" in _detail(unpromotable, "SEC-BOUNDARY")

    evidenced = supervise(
        {
            "security": {
                "status": "FINDINGS",
                "run_id": "run-123",
                "target_revision": "abc123",
                "evidence": ["finding-1"],
            }
        }
    )
    assert _status(evidenced, "SEC-BOUNDARY") == "PASS"


def test_caseweave_supervision_passes_the_checks_it_can_see():
    report = supervise_caseweave(actor_id="HACLA")
    assert report["summary"]["fail"] == 0
    assert report["caseweave"]["assessment"] == {"status": "REVIEW", "errors": ["SHARING_CONSENT_NOT_ESTABLISHED"]}
    for check_id in ("K-Q1Q6", "P-ROLE", "G-NOSEND", "G-CONSENT", "G-PRIVACY"):
        assert _status(report, check_id) == "PASS", check_id
    # Evidence this trace genuinely does not carry must stay UNKNOWN.
    for check_id in ("K-SOURCE", "P-REPLAY", "P-LEDGER", "SEC-BOUNDARY"):
        assert _status(report, check_id) == "UNKNOWN", check_id


def test_caseweave_supervision_fails_role_scope_violations():
    report = supervise(
        {
            "agency": {
                "actor_id": "LAHD",
                "primary": [{"id": "I-MOVE", "target": ["HACLA"]}],
                "adjacent": [],
            }
        }
    )
    assert _status(report, "P-ROLE") == "FAIL"


def _status(report: dict, check_id: str) -> str:
    return next(check["status"] for check in report["checks"] if check["id"] == check_id)


def _detail(report: dict, check_id: str) -> str:
    return next(check["detail"] for check in report["checks"] if check["id"] == check_id)


# --- framework wiring -------------------------------------------------------------


def test_fabric_is_registered_and_enabled():
    assert SuperagentFabric in default_plugins()
    config = ConfigLoader.build(root_dir=ROOT, profile="development")
    assert "SA1" in config.get("systems.enabled")
    assert config.get("systems.maturity.SA1") == "implemented_adapter"
    assert config.get("systems.superagent.external_operations_allowed") is False


def test_fabric_process_is_non_mutating_and_never_raises():
    config = ConfigLoader.build(root_dir=ROOT, profile="development")
    fabric = SuperagentFabric(config)
    fabric.initialize()

    empty = fabric.process({}, {})
    assert empty["status"] == "supervision_record"
    assert empty["non_authoritative"] is True
    assert empty["assurance"]["external_dispatch_enabled"] is False
    assert empty["assurance"]["status"] == "NOT_SCANNED"
    assert empty["source_graph_mutated"] is False

    broken = fabric.process({}, {"s1": "not-a-mapping"})  # type: ignore[arg-type]
    assert broken["status"] in {"supervision_record", "supervision_error"}


def test_kernel_turn_exposes_sa1_supervision_and_capability():
    kernel = RuntimeKernel.boot(root_dir=ROOT, profile="development")
    try:
        result = kernel.process_turn("Design a governed agent integration surface for GitHub and Gemini.")
        assert "SA1" in result["outputs"], result["capability_report"]
        sa1 = result["outputs"]["SA1"]
        assert sa1["status"] == "supervision_record"
        assert sa1["verdict"] in {"PASS", "INCOMPLETE", "FAIL"}
        assert sa1["supervision"]["summary"]["total"] == 12
        assert {surface["name"] for surface in sa1["agent_surfaces"]} >= {"github", "supabase", "gemini"}
        assert result["capability_report"]["systems"]["SA1"]["execution_ready"] is True

        names = {item["name"] for item in kernel.list_capabilities()}
        assert "sa1.superagent_supervision" in names

        envelope = CommandEnvelope(
            command_id="cmd-sa1",
            target_capability="sa1.superagent_supervision",
            payload={"input": "Supervise this governed turn."},
            session_id=kernel.get_current_capsule().session_id,
            idempotency_key="ik-sa1",
        )
        dispatched = kernel.dispatch(envelope)
        assert dispatched.status == "SUCCESS"
        assert dispatched.outputs["outputs"]["SA1"]["status"] == "supervision_record"
    finally:
        kernel.close()


def test_supervision_record_is_deterministic():
    config = ConfigLoader.build(root_dir=ROOT, profile="development")
    fabric = SuperagentFabric(config)
    fabric.initialize()
    context = {"s1": {"context_graph": {"turn_id": "t-1"}, "memory_context": []}}

    first = fabric.process({}, context)
    second = fabric.process({}, context)
    assert first == second

    bundle = {"sources": [{"id": "SRC-1", "reference": "deeplink://a/b/c@1#f"}]}
    assert supervise(bundle, bundle_id="b") == supervise(bundle, bundle_id="b")


def test_actors_registry_exposes_authority_limits():
    for actor_id, actor in ACTORS.items():
        assert actor["can"] and actor["cannot"], actor_id
