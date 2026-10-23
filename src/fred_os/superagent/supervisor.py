"""Supervisor — independent Knowledge, Performance and Governance checks.

Reference: ``SUPERVISOR.md`` (FRED Knowledge, Performance and Governance
Checks, v0.2). The role is to *assess the actual trace and outcomes
independently of an Agent's confidence or claimed completion*, and to flag
uncertainty and missing evidence. Permissions are never granted by praise,
natural-language agreement or checkbox.

Design rules held by this module:

- Checks are computed from **structured outputs**, never from LLM self-reports.
- A check that cannot see its evidence returns ``UNKNOWN`` — it is never
  silently promoted to ``PASS``.
- The report is explicitly **non-authoritative**: it is a learning record. S7
  and ``update-skills`` may propose changes from it; they cannot change
  governance or source authority without review.
- ``NOT_SCANNED`` remains the only valid local status for the external security
  preflight (``SEC-BOUNDARY``).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from .caseweave import DEMO, Q_FIELDS, assess_output, compose_agency_note, tokenize_issue

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

#: Operations that must never enter a local plan unapproved.
FORBIDDEN_EXTERNAL_OPERATIONS: frozenset[str] = frozenset(
    {
        "external_write",
        "send_message",
        "dispatch_note",
        "source_export",
        "credential_use",
        "payment",
        "scan_dispatch",
    }
)

def _rendered_private_material(
    note: Mapping[str, Any], case_data: Mapping[str, Any], actor_id: str
) -> list[str]:
    """Independently detect raw private material in a rendered CaseWeave note.

    Reads the composed output, not a redaction flag: a medical issue is clean
    only when its raw title/request and its medical evidence source are absent,
    and a privileged issue is clean only when it is absent outside its holder.
    """
    text = str(note.get("text", ""))
    leaked: list[str] = []
    for issue in case_data.get("issues", ()):
        sensitivity = str(issue.get("sensitivity", "ordinary"))
        if sensitivity == "medical":
            if str(issue.get("next", "")) in text or str(issue.get("title", "")) in text:
                leaked.append(f"raw-medical-issue:{issue.get('id')}")
            if "SRC-4" in issue.get("sources", ()) and "SRC-4" in text:
                leaked.append("medical-evidence-source:SRC-4")
        elif sensitivity == "privileged" and actor_id != "NLSLA":
            if str(issue.get("title", "")) in text:
                leaked.append(f"privileged-issue:{issue.get('id')}")
    return leaked

CHECKS: tuple[str, ...] = (
    "K-SOURCE",
    "K-OVERLAY",
    "K-Q1Q6",
    "P-REPLAY",
    "P-LEDGER",
    "P-BASELINE",
    "P-ROLE",
    "G-PLAN",
    "G-NOSEND",
    "G-CONSENT",
    "G-PRIVACY",
    "SEC-BOUNDARY",
)

_GROUP: dict[str, str] = {
    "K-SOURCE": "K",
    "K-OVERLAY": "K",
    "K-Q1Q6": "K",
    "P-REPLAY": "P",
    "P-LEDGER": "P",
    "P-BASELINE": "P",
    "P-ROLE": "P",
    "G-PLAN": "G",
    "G-NOSEND": "G",
    "G-CONSENT": "G",
    "G-PRIVACY": "G",
    "SEC-BOUNDARY": "SEC",
}

_STATEMENT: dict[str, str] = {
    "K-SOURCE": "admitted source claims exist and retain exact references.",
    "K-OVERLAY": "inferred S2 overlays remain distinct from S1 graph facts.",
    "K-Q1Q6": "synthetic CaseWeave issues preserve all six symbolic fields.",
    "P-REPLAY": "AADN event reducer replays consistently.",
    "P-LEDGER": "Temporal Sphere produces and validates hash-chain lineage.",
    "P-BASELINE": "the fixed multi-hop fixture performs at least as well as a one-hop comparison; fixture-limited evidence only.",
    "P-ROLE": "primary versus adjacent agency scope is respected.",
    "G-PLAN": "no forbidden external operation entered the local plan.",
    "G-NOSEND": "a generated note is a draft, not dispatched.",
    "G-CONSENT": "cross-agency exchange is not treated as consented.",
    "G-PRIVACY": "medical and privileged material is not placed into shared projection.",
    "SEC-BOUNDARY": "a security scan proposal or eligibility result is not a security finding, a test receipt or an approval.",
}


def _digest(value: Any) -> str:
    packed = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _missing(bundle: Mapping[str, Any], key: str) -> bool:
    value = bundle.get(key)
    return value is None or (isinstance(value, (list, tuple, Mapping, str)) and len(value) == 0)


def _check_k_source(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "sources"):
        return UNKNOWN, "no admitted source claims were supplied for this trace"
    sources = list(bundle["sources"])
    unreferenced = [
        str(item.get("id", index))
        for index, item in enumerate(sources)
        if not str(item.get("reference", "")).strip()
    ]
    if unreferenced:
        return FAIL, f"source claims without an exact reference: {', '.join(unreferenced)}"
    return PASS, f"{len(sources)} admitted source claim(s) retain exact references"


def _check_k_overlay(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "overlay"):
        return UNKNOWN, "no S2 association overlay was supplied for this trace"
    overlay = bundle["overlay"]
    if not isinstance(overlay, Mapping):
        return FAIL, "overlay record is not a structured mapping"
    if overlay.get("source_graph_mutated"):
        return FAIL, "the S1 source graph was mutated by the S2 overlay"
    inferred = [item for item in overlay.get("associations", ()) if isinstance(item, Mapping)]
    promoted = [
        str(item.get("id", "?"))
        for item in inferred
        if str(item.get("epistemic_state", "")) != "inferred"
    ]
    if promoted:
        return FAIL, f"overlay associations not marked inferred: {', '.join(promoted)}"
    s1_ids = {str(item) for item in overlay.get("s1_facts", ())}
    collisions = [str(item.get("id")) for item in inferred if str(item.get("id")) in s1_ids]
    if collisions:
        return FAIL, f"S2 overlay identifiers collide with S1 graph facts: {', '.join(collisions)}"
    return PASS, f"{len(inferred)} inferred overlay association(s) stay distinct from S1 graph facts"


def _check_k_q1q6(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "caseweave_issues"):
        return UNKNOWN, "no CaseWeave issue set was supplied for this trace"
    incomplete: list[str] = []
    for issue in bundle["caseweave_issues"]:
        tokens = issue.get("tokens") if isinstance(issue, Mapping) else None
        if not isinstance(tokens, Mapping):
            tokens = tokenize_issue(issue)
        missing = [
            field
            for field in Q_FIELDS
            if not isinstance(tokens.get(field), Mapping) or not tokens.get(field)
        ]
        if missing:
            incomplete.append(f"{issue.get('id', '?')}:{','.join(missing)}")
    if incomplete:
        return FAIL, f"issues missing symbolic fields: {'; '.join(incomplete)}"
    return PASS, f"{len(bundle['caseweave_issues'])} issue(s) preserve all six symbolic fields"


def _check_p_replay(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "aadn"):
        return UNKNOWN, "no AADN event trace was supplied for this trace"
    aadn = bundle["aadn"]
    events = list(aadn.get("events", ()))
    replays = [list(run) for run in aadn.get("replays", ())]
    if len(replays) < 2:
        return FAIL, "fewer than two reducer replays were recorded; consistency is not established"
    baseline = _digest(events)
    divergent = [index for index, run in enumerate(replays) if _digest(run) != baseline]
    if divergent:
        return FAIL, f"reducer replay diverged at run index/indices {divergent}"
    return PASS, f"{len(replays)} reducer replays reproduce the event trace exactly"


def _check_p_ledger(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "ledger"):
        return UNKNOWN, "no Temporal Sphere ledger was supplied for this trace"
    records = [item for item in bundle["ledger"].get("records", ()) if isinstance(item, Mapping)]
    if not records:
        return FAIL, "ledger contains no hash-chain records"
    previous: str | None = None
    seen: set[str] = set()
    for index, record in enumerate(records):
        current = str(record.get("hash", "")).strip()
        if not current:
            return FAIL, f"ledger record {index} has no hash"
        if current in seen:
            return FAIL, f"ledger record {index} reuses hash {current[:12]}…"
        seen.add(current)
        if index == 0:
            if str(record.get("prev") or "").strip():
                return FAIL, "genesis ledger record carries a predecessor hash"
        elif str(record.get("prev", "")).strip() != previous:
            return FAIL, f"ledger lineage breaks at record {index}"
        previous = current
    return PASS, f"{len(records)} hash-chain record(s) validate end to end"


def _check_p_baseline(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "baseline"):
        return UNKNOWN, "no fixed multi-hop fixture comparison was supplied"
    baseline = bundle["baseline"]
    try:
        multi_hop = float(baseline.get("multi_hop"))
        one_hop = float(baseline.get("one_hop"))
    except (TypeError, ValueError):
        return FAIL, "baseline fixture does not report numeric multi-hop and one-hop results"
    if multi_hop < one_hop:
        return FAIL, f"multi-hop fixture {multi_hop} underperforms the one-hop comparison {one_hop}"
    return PASS, (
        f"multi-hop fixture {multi_hop} at least matches the one-hop comparison {one_hop}; "
        "fixture-limited evidence only"
    )


def _check_p_role(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "agency"):
        return UNKNOWN, "no agency scope record was supplied for this trace"
    agency = bundle["agency"]
    actor = str(agency.get("actor_id", ""))
    if not actor:
        return FAIL, "agency record names no actor"
    primary = [item for item in agency.get("primary", ()) if isinstance(item, Mapping)]
    adjacent = [item for item in agency.get("adjacent", ()) if isinstance(item, Mapping)]
    scope_errors: list[str] = []
    for item in primary:
        if actor not in item.get("target", ()):
            scope_errors.append(f"{item.get('id', '?')} listed as primary outside {actor} authority")
    for item in adjacent:
        if actor in item.get("target", ()):
            scope_errors.append(f"{item.get('id', '?')} listed as adjacent while {actor} is the primary owner")
    if scope_errors:
        return FAIL, "; ".join(scope_errors)
    return PASS, f"{actor} holds {len(primary)} primary and {len(adjacent)} adjacent issue(s) within scope"


def _check_g_plan(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "plan"):
        return UNKNOWN, "no local plan was supplied for this trace"
    operations = [item for item in bundle["plan"].get("operations", ()) if isinstance(item, Mapping)]
    offending = [
        str(item.get("id", item.get("kind", "?")))
        for item in operations
        if str(item.get("kind", "")) in FORBIDDEN_EXTERNAL_OPERATIONS
        or (item.get("external") and not item.get("approved"))
    ]
    if offending:
        return FAIL, f"forbidden external operation(s) entered the local plan: {', '.join(offending)}"
    return PASS, f"local plan declares {len(operations)} operation(s), none forbidden or unapproved-external"


def _check_g_nosend(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "note"):
        return UNKNOWN, "no generated note was supplied for this trace"
    note = bundle["note"]
    status = str(note.get("status", "")).lower()
    gate = note.get("gate", {}) if isinstance(note.get("gate"), Mapping) else {}
    if gate.get("maySend") or status in {"sent", "dispatched", "delivered"}:
        return FAIL, f"generated note is not a draft (status='{status or 'maySend=true'}')"
    if status != "draft":
        return UNKNOWN, f"generated note status '{status}' is not a recognised draft marker"
    return PASS, "generated note is a draft and was not dispatched"


def _check_g_consent(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "sharing"):
        return UNKNOWN, "no cross-agency sharing record was supplied for this trace"
    sharing = bundle["sharing"]
    if not bool(sharing.get("cross_agency")):
        return PASS, "no cross-agency exchange was proposed"
    if sharing.get("consent_recorded") and sharing.get("review_approved"):
        return PASS, "cross-agency exchange carries recorded consent and human review"
    if sharing.get("consent_required_by_gate"):
        return PASS, "cross-agency exchange requires recipient consent and is not treated as consented"
    return FAIL, "cross-agency exchange was treated as consented without recipient consent and review"


def _check_g_privacy(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "projection"):
        return UNKNOWN, "no shared projection was supplied for this trace"
    # ``contains`` is the material that actually reached the shared projection,
    # so a non-empty list is the failure — not a keyword match on boilerplate.
    leaked = [str(item) for item in bundle["projection"].get("contains", ())]
    if leaked:
        return FAIL, f"private material reached the shared projection: {', '.join(leaked)}"
    return PASS, "no medical or privileged material reached the shared projection"


def _check_sec_boundary(bundle: Mapping[str, Any]) -> tuple[str, str]:
    if _missing(bundle, "security"):
        return UNKNOWN, "no security-assurance record was supplied for this trace"
    security = bundle["security"]
    status = str(security.get("status", "")).upper()
    if status == "NOT_SCANNED":
        return PASS, "NOT_SCANNED recorded; no external provider claim was promoted"
    if status in {"", "UNKNOWN"}:
        return FAIL, "security-assurance record carries no valid status"
    missing = [
        field
        for field in ("run_id", "target_revision", "evidence")
        if not security.get(field)
    ]
    if missing:
        return FAIL, (
            f"external provider claim '{status}' cannot be promoted without {', '.join(missing)}"
        )
    return PASS, f"external provider claim '{status}' carries run id, target revision and evidence"


_CHECKS: dict[str, Callable[[Mapping[str, Any]], tuple[str, str]]] = {
    "K-SOURCE": _check_k_source,
    "K-OVERLAY": _check_k_overlay,
    "K-Q1Q6": _check_k_q1q6,
    "P-REPLAY": _check_p_replay,
    "P-LEDGER": _check_p_ledger,
    "P-BASELINE": _check_p_baseline,
    "P-ROLE": _check_p_role,
    "G-PLAN": _check_g_plan,
    "G-NOSEND": _check_g_nosend,
    "G-CONSENT": _check_g_consent,
    "G-PRIVACY": _check_g_privacy,
    "SEC-BOUNDARY": _check_sec_boundary,
}


def _verdict(statuses: list[str]) -> str:
    if FAIL in statuses:
        return FAIL
    if UNKNOWN in statuses:
        return "INCOMPLETE"
    return PASS


def supervise(bundle: Mapping[str, Any] | None = None, *, bundle_id: str = "trace") -> dict[str, Any]:
    """Run every K/P/G check over a structured trace bundle.

    A check whose evidence is absent returns ``UNKNOWN``. The report never
    infers a pass from an agent's own claim of completion.
    """
    bundle = dict(bundle or {})
    results: list[dict[str, Any]] = []
    for check_id in CHECKS:
        status, detail = _CHECKS[check_id](bundle)
        results.append(
            {
                "id": check_id,
                "group": _GROUP[check_id],
                "statement": _STATEMENT[check_id],
                "status": status,
                "detail": detail,
            }
        )

    statuses = [item["status"] for item in results]
    summary = {
        "pass": statuses.count(PASS),
        "fail": statuses.count(FAIL),
        "unknown": statuses.count(UNKNOWN),
        "total": len(statuses),
        "verdict": _verdict(statuses),
    }
    return {
        "bundle_id": str(bundle_id),
        "checks": results,
        "summary": summary,
        "non_authoritative": True,
        "remediation_policy": (
            "Failing check IDs and proposed remediation are a non-authoritative learning record; "
            "S7 and update-skills may propose changes but cannot change governance or source authority "
            "without review."
        ),
        "content_digest": _digest({"bundle_id": str(bundle_id), "checks": results}),
    }


def supervise_caseweave(
    case_data: Mapping[str, Any] | None = None,
    *,
    actor_id: str = "HACLA",
    consent_to_share: bool = False,
    review_approved: bool = False,
    bundle_id: str = "caseweave",
) -> dict[str, Any]:
    """Build a trace bundle from a CaseWeave run and supervise it.

    This is the concrete path that exercises K-Q1Q6, P-ROLE, G-NOSEND,
    G-CONSENT and G-PRIVACY against real reference behaviour rather than a
    hand-written bundle.
    """
    case_data = DEMO if case_data is None else case_data
    note = compose_agency_note(
        actor_id,
        case_data,
        consent_to_share=consent_to_share,
        review_approved=review_approved,
    )
    review = assess_output(note)

    bundle = {
        "caseweave_issues": [
            {"id": item.get("id"), "tokens": tokenize_issue(item)}
            for item in case_data.get("issues", ())
        ],
        "agency": {
            "actor_id": actor_id,
            "primary": note["primary"],
            "adjacent": note["adjacent"],
        },
        "note": {"status": "draft", "gate": note["gate"]},
        "sharing": {
            "cross_agency": len(note["adjacent"]) > 0,
            "consent_recorded": consent_to_share,
            "review_approved": review_approved,
            "consent_required_by_gate": bool(note["gate"]["needsRecipientConsent"]),
        },
        # The shared projection is the rendered note. G-PRIVACY inspects the
        # rendered text for the *raw* medical/privileged material, not the
        # redaction instruction that legitimately mentions it.
        "projection": {"contains": _rendered_private_material(note, case_data, actor_id)},
    }
    report = supervise(bundle, bundle_id=bundle_id)
    report["caseweave"] = {
        "actor_id": actor_id,
        "tokenized_issue_count": len(bundle["caseweave_issues"]),
        "assessment": review,
        "gate_reasons": note["gate"]["reasons"],
        "may_send": note["gate"]["maySend"],
    }
    return report
