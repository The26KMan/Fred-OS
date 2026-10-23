"""CaseWeave P0 — deterministic Q1–Q6 symbolic issue routing (Python port).

Behaviour-preserving port of the reference prototype
``systemos_caseweave/src/lib/caseWeaveEngine.js`` (SystemOS CaseWeave P0).

It does **not** perform quantum computation, decide legal rights, or
communicate with third parties. Inputs are explicitly sourced claims; outputs
are review-only draft coordination notes. Q1–Q6 are multi-axis symbolic
markers, not a physical quantum state or probability amplitude.

Symbolic fields (the reference "six symbolic fields" the Supervisor's K-Q1Q6
check asserts are preserved):

- Q1 evidence and source grades
- Q2 issue / need
- Q3 actor authority and dependencies
- Q4 legal citation plus privacy
- Q5 alternative factual/legal branches and epistemic status
- Q6 requested decision and priority
"""
from __future__ import annotations

import re
from typing import Any, Mapping

Q_FIELDS = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6")
EVIDENCE_GRADES = frozenset({"A", "B", "C"})
SYNTHETIC_PRIVACY = "SYNTHETIC_FIXTURE"
SENSITIVE_DOMAINS = ("raw medical records", "attorney-client communications")

ACTORS: dict[str, dict[str, Any]] = {
    "HACLA": {"title": "HACLA · PBV / Section 504", "can": ["subsidy", "move", "household", "accommodation", "hearing"], "cannot": ["adjudicate eviction", "issue LAHD citations"]},
    "LAHD": {"title": "LAHD · Housing / Tenant Protection", "can": ["repairs", "harassment", "inspection"], "cannot": ["issue HCV", "stay unlawful-detainer case"]},
    "NLSLA": {"title": "NLSLA · Eviction Defense", "can": ["court", "hearing", "settlement", "preservation"], "cannot": ["approve voucher", "make LAHD findings"]},
    "HUD": {"title": "HUD FHEO · Fair Housing", "can": ["accommodation", "harassment", "discrimination"], "cannot": ["issue tenant HCV directly", "control local court calendar"]},
    "CRD": {"title": "California CRD · Civil Rights", "can": ["accommodation", "discrimination", "harassment"], "cannot": ["approve PBV move", "file UD Answer"]},
    "OWNER": {"title": "Owner / Property Management", "can": ["repairs", "inspection", "settlement", "preservation"], "cannot": ["grant HACLA voucher", "declare a court stay"]},
    "SUPPORT": {"title": "AMFB / Care / Housing Navigation", "can": ["logistics", "evidence", "referral"], "cannot": ["authorize voucher", "offer legal representation"]},
}

LAWS: dict[str, dict[str, Any]] = {
    "PBV_MOVE": {"label": "24 CFR 983.261", "url": "https://www.law.cornell.edu/cfr/text/24/983.261", "scope": ["HACLA", "NLSLA"], "topic": "move"},
    "HCV_PORT": {"label": "24 CFR 982.355", "url": "https://www.law.cornell.edu/cfr/text/24/982.355", "scope": ["HACLA", "NLSLA"], "topic": "move"},
    "HCV_FAMILY": {"label": "24 CFR 982.551(h)", "url": "https://www.law.cornell.edu/cfr/text/24/982.551", "scope": ["HACLA", "NLSLA"], "topic": "household"},
    "HCV_HEARING": {"label": "24 CFR 982.555", "url": "https://www.law.cornell.edu/cfr/text/24/982.555", "scope": ["HACLA", "NLSLA"], "topic": "hearing"},
    "FHA_RA": {"label": "HUD/DOJ Reasonable Accommodation Guidance", "url": "https://www.justice.gov/crt/us-department-justice", "scope": ["HACLA", "HUD", "CRD", "NLSLA", "OWNER"], "topic": "accommodation"},
    "LA_TAHO": {"label": "LAHD Tenant Anti-Harassment Ordinance", "url": "https://housing.lacity.gov/residents/tenant-anti-harassment", "scope": ["LAHD", "NLSLA", "OWNER"], "topic": "harassment"},
    "LA_CODE": {"label": "LAHD Housing Code Complaints", "url": "https://housing.lacity.gov/residents/file-a-complaint", "scope": ["LAHD", "NLSLA", "OWNER"], "topic": "repairs"},
    "CA_FEHA": {"label": "California Civil Rights Department: Housing", "url": "https://calcivilrights.ca.gov/housing/", "scope": ["CRD", "HACLA", "NLSLA", "OWNER"], "topic": "discrimination"},
}

# Entirely fictionalized fixture: dates, persons, circumstances and IDs are not
# the client's actual data.
DEMO: dict[str, Any] = {
    "caseName": "Example case · de-identified training fixture",
    "privacy": SYNTHETIC_PRIVACY,
    "outcome": "Safe, authorized relocation with continuity of assistance and household review.",
    "evidence": [
        {"id": "SRC-1", "grade": "A", "kind": "Dated request", "description": "Illustrative PBV move and accommodation request acknowledged."},
        {"id": "SRC-2", "grade": "A", "kind": "Agency letter", "description": "Illustrative subsidy adverse-action notice; status remains unresolved."},
        {"id": "SRC-3", "grade": "B", "kind": "Later case summary", "description": "Illustrative condition/repair disputes; attribution unresolved."},
        {"id": "SRC-4", "grade": "C", "kind": "Unverified", "description": "Illustrative clinical necessity requires qualified verification."},
        {"id": "SRC-5", "grade": "A", "kind": "Case intake", "description": "Illustrative legal-aid intake; filing not verified."},
    ],
    "issues": [
        {"id": "I-MOVE", "topic": "move", "title": "Continued tenant-based assistance / Choice Mobility", "status": "PENDING", "target": ["HACLA"], "adjacent": ["NLSLA", "SUPPORT"], "sources": ["SRC-1"], "laws": ["PBV_MOVE", "HCV_PORT"], "next": "Determine PBV right-to-move eligibility, availability, priority and any disability-related exception; identify portability steps only after voucher issuance.", "priority": 100},
        {"id": "I-HOUSE", "topic": "household", "title": "Prospective adult family-member status and continuity", "status": "PENDING", "target": ["HACLA"], "adjacent": ["NLSLA", "SUPPORT"], "sources": ["SRC-1"], "laws": ["HCV_FAMILY"], "next": "Make a separate admission/co-head determination; state documentation, consequences and remaining-family rules.", "priority": 96},
        {"id": "I-RA", "topic": "accommodation", "title": "Disability-related safe move and functional verification", "status": "VERIFICATION_NEEDED", "target": ["HACLA"], "adjacent": ["HUD", "CRD", "NLSLA", "SUPPORT"], "sources": ["SRC-1", "SRC-4"], "laws": ["FHA_RA", "CA_FEHA"], "next": "Identify functional verification required and review individualized accommodation without demanding full medical charts.", "priority": 94, "sensitivity": "medical"},
        {"id": "I-HEARING", "topic": "hearing", "title": "Proposed subsidy termination / administrative hearing", "status": "PENDING", "target": ["HACLA"], "adjacent": ["NLSLA"], "sources": ["SRC-2"], "laws": ["HCV_HEARING"], "next": "Confirm assistance/HAP status, hearing rights, notice and whether pretermination hearing protection applies.", "priority": 92},
        {"id": "I-CODE", "topic": "repairs", "title": "Housing defects and disputed attribution", "status": "DISPUTED", "branches": ["owner-responsible", "family-responsible", "mixed"], "target": ["LAHD", "OWNER"], "adjacent": ["HACLA", "NLSLA"], "sources": ["SRC-3"], "laws": ["LA_CODE"], "next": "Investigate specific conditions, actual repair status and allocation; do not assume a finding from a complaint.", "priority": 80},
        {"id": "I-TAHO", "topic": "harassment", "title": "Alleged harassment and protected activity", "status": "ALLEGED", "target": ["LAHD"], "adjacent": ["NLSLA", "HUD", "CRD", "HACLA"], "sources": ["SRC-3"], "laws": ["LA_TAHO", "CA_FEHA"], "next": "Assess dated incidents and evidence under applicable protections; no finding of motive is assumed.", "priority": 81},
        {"id": "I-COURT", "topic": "court", "title": "Unlawful-detainer defense and service", "status": "UNCONFIRMED", "target": ["NLSLA"], "adjacent": ["HACLA", "LAHD"], "sources": ["SRC-5"], "laws": [], "next": "Verify filed and accepted Answer, service record, trial calendar and any actual court stay.", "priority": 99, "sensitivity": "privileged"},
        {"id": "I-COST", "topic": "logistics", "title": "Moving, storage, animals and search support", "status": "PENDING", "target": ["SUPPORT"], "adjacent": ["HACLA", "LAHD", "NLSLA"], "sources": ["SRC-3"], "laws": [], "next": "Prepare logistics ledger, assistance-animal/pet status, housing search needs and reimbursement questions for proper decision-makers.", "priority": 78},
    ],
}

_UNVERIFIED_CONCLUSION = re.compile(
    r"has granted a stay|proved retaliation|voucher is already issued", re.IGNORECASE
)


def without_phi(issue: Mapping[str, Any]) -> dict[str, Any]:
    """Replace medical detail with a secure-channel instruction (reference parity)."""
    if issue.get("sensitivity") == "medical":
        return {
            **issue,
            "title": "Disability-related accommodation process (functional verification by secure channel)",
            "next": "Identify accommodation process and secure verification channel; do not share diagnosis or medical records.",
            "sources": [s for s in issue.get("sources", ()) if s != "SRC-4"],
        }
    return dict(issue)


def tokenize_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    """Project one issue through the six symbolic Q1–Q6 fields."""
    sources = list(issue.get("sources", ()))
    return {
        "Q1": {"evidence": sources, "admission": "SOURCE_LINKED" if sources else "GAP"},
        "Q2": {"issue": issue.get("topic"), "title": issue.get("title")},
        "Q3": {"primary": list(issue.get("target", ())), "dependent": list(issue.get("adjacent", ()))},
        "Q4": {"lawIds": list(issue.get("laws", ())), "sensitivity": issue.get("sensitivity", "ordinary")},
        "Q5": {"epistemicState": issue.get("status"), "alternatives": list(issue.get("branches", ()))},
        "Q6": {"requestedAction": issue.get("next"), "priority": issue.get("priority")},
    }


def analyze_case(case_data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic routing: tokenize, attach evidence, sort by priority, list gaps."""
    case_data = DEMO if case_data is None else case_data
    evidence = list(case_data.get("evidence", ()))
    evidence_map = {item.get("id"): item for item in evidence}

    issues: list[dict[str, Any]] = []
    for issue in case_data.get("issues", ()):
        item = dict(issue)
        item["tokens"] = tokenize_issue(issue)
        item["evidence"] = [evidence_map[source] for source in issue.get("sources", ()) if source in evidence_map]
        issues.append(item)
    issues.sort(key=lambda item: item.get("priority", 0), reverse=True)

    gaps = [
        {"issue": item.get("id"), "missingSource": source}
        for item in issues
        for source in item.get("sources", ())
        if source not in evidence_map
    ]
    gaps += [
        {"issue": "SOURCE", "missingSource": item.get("id")}
        for item in evidence
        if item.get("grade") not in EVIDENCE_GRADES
    ]

    return {
        "outcome": case_data.get("outcome"),
        "issues": issues,
        "gaps": gaps,
        "trace": {
            "engine": "CaseWeave-P0",
            "synthetic": case_data.get("privacy") == SYNTHETIC_PRIVACY,
            "autoSend": False,
            "deterministic": True,
        },
    }


def compose_agency_note(
    actor_id: str,
    case_data: Mapping[str, Any] | None = None,
    *,
    consent_to_share: bool = False,
    review_approved: bool = False,
) -> dict[str, Any]:
    """Compose one bounded, review-only draft coordination note for a single actor.

    The observer-within-agent: the same agent examines its proposed output
    against role authority and disclosure limits. No claim of consciousness.
    """
    case_data = DEMO if case_data is None else case_data
    if actor_id not in ACTORS:
        raise ValueError("Unknown actor")

    analysis = analyze_case(case_data)
    primary = [item for item in analysis["issues"] if actor_id in item.get("target", ())]
    adjacent = [
        item
        for item in analysis["issues"]
        if actor_id in item.get("adjacent", ()) and actor_id not in item.get("target", ())
    ]

    def visible(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            without_phi(item)
            for item in items
            if not (item.get("sensitivity") == "privileged" and actor_id != "NLSLA")
        ]

    visible_primary, visible_adjacent = visible(primary), visible(adjacent)

    law_ids: list[str] = []
    for item in visible_primary + visible_adjacent:
        for law in item.get("laws", ()):
            if law in LAWS and actor_id in LAWS[law]["scope"] and law not in law_ids:
                law_ids.append(law)

    own_tasks = [
        f"• {item['title']} [{item['status']}; {', '.join(item['sources'])}]\n  Request: {item['next']}"
        for item in visible_primary
    ]
    notes = []
    for item in visible_adjacent:
        owners = "/".join(ACTORS[target]["title"].split(" · ")[0] for target in item.get("target", ()))
        notes.append(
            f"• {item['title']}: {owners} leads. {str(item['status']).lower()} — please consider related "
            f"evidence [{', '.join(item['sources'])}] only within your authority."
        )
    legal = [f"{LAWS[law]['label']} ({LAWS[law]['url']})" for law in law_ids]

    intro = f"DRAFT FOR REVIEW — {ACTORS[actor_id]['title']}\nShared outcome: {case_data.get('outcome')}\n"
    body = "\n".join(
        [
            intro,
            "Direct requests within your authority:",
            *own_tasks,
            "\nInteragency context (not a demand that you decide another department’s case):",
            *notes,
            "\nPotentially relevant authorities (verify applicability):",
            *(legal or ["No direct statute assigned in this fixture."]),
            "\nNo claims are findings unless verified in source records. No automatic stay, voucher "
            "approval, medical conclusion, or filing is implied.",
        ]
    )

    needs_consent = (not consent_to_share) and len(visible_adjacent) > 0
    gate = {
        "maySend": False,
        "needsHumanApproval": not review_approved,
        "needsRecipientConsent": needs_consent,
        "blockedSensitiveDomains": list(SENSITIVE_DOMAINS),
        "actorLimits": list(ACTORS[actor_id]["cannot"]),
        "reasons": [
            *(["CONSENT_REQUIRED_FOR_CROSS_AGENCY_SHARING"] if needs_consent else []),
            *(["HUMAN_REVIEW_REQUIRED"] if not review_approved else []),
            "NO_AUTOSEND_BY_DESIGN",
        ],
    }

    return {
        "actorId": actor_id,
        "primary": visible_primary,
        "adjacent": visible_adjacent,
        "lawIds": law_ids,
        "text": body,
        "gate": gate,
        "receipt": {
            "sourceGrades": {item.get("id"): item.get("grade") for item in case_data.get("evidence", ())},
            "claimCount": len(visible_primary) + len(visible_adjacent),
            "draftOnly": True,
        },
    }


def assess_output(note: Mapping[str, Any]) -> dict[str, Any]:
    """Independent review of a composed note; returns REVIEW or PASS with error codes."""
    errors: list[str] = []
    gate = note.get("gate", {}) if isinstance(note.get("gate"), Mapping) else {}
    text = str(note.get("text", ""))

    if gate.get("maySend"):
        errors.append("PROHIBITED_AUTOSEND")
    if note.get("actorId") != "NLSLA" and "Attorney-client communications:" in text:
        errors.append("PRIVILEGE_DISCLOSURE")
    if _UNVERIFIED_CONCLUSION.search(text):
        errors.append("UNVERIFIED_LEGAL_CONCLUSION")
    if gate.get("needsRecipientConsent"):
        errors.append("SHARING_CONSENT_NOT_ESTABLISHED")

    return {"status": "REVIEW" if errors else "PASS", "errors": errors}
