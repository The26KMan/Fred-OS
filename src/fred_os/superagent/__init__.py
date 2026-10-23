"""Superagent integration fabric — bounded, plan-only agent-surface governance.

This package folds the FRED reference materials (the Supervisor K/P/G check
list, the offline ``fred-security-preflight`` Skill contract, the CaseWeave P0
Q1–Q6 symbolic engine, and the two-platform Superagent separation note) into the
vNext runtime as inspectable, deterministic code.

Nothing here performs an external call, holds a credential, or dispatches a
security scan. Every external surface is a *design contract* with
``enabled: false`` and ``approval_required: true`` until a trusted gateway
exists.
"""
from .adapter import SuperagentFabric
from .caseweave import (
    ACTORS,
    DEMO,
    LAWS,
    analyze_case,
    assess_output,
    compose_agency_note,
    tokenize_issue,
)
from .preflight import (
    SUPPORTED_TARGET_KINDS,
    DispatchDisabled,
    ScanPlan,
    ScanRequest,
    dispatch_security_scan,
    plan_security_check,
)
from .supervisor import CHECKS, supervise, supervise_caseweave
from .surfaces import AGENT_SURFACES, get_agent_surface, list_agent_surfaces

__all__ = [
    "ACTORS",
    "AGENT_SURFACES",
    "CHECKS",
    "DEMO",
    "DispatchDisabled",
    "LAWS",
    "SUPPORTED_TARGET_KINDS",
    "ScanPlan",
    "ScanRequest",
    "SuperagentFabric",
    "analyze_case",
    "assess_output",
    "compose_agency_note",
    "dispatch_security_scan",
    "get_agent_surface",
    "list_agent_surfaces",
    "plan_security_check",
    "supervise",
    "supervise_caseweave",
    "tokenize_issue",
]
