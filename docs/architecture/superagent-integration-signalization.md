# Superagent integration — reference analysis and signalization map

This document answers one question: **given the attached FRED reference
materials, where does each piece land in the vNext runtime, and what is
actually implemented versus still plan-only?**

It accompanies the SA1 adapter (`src/fred_os/superagent/`).

## 1. What was analysed

| Reference artifact | What it actually contains |
|---|---|
| `SUPERVISOR.md` | The K/P/G check list (K-SOURCE, K-OVERLAY, K-Q1Q6, P-REPLAY, P-LEDGER, P-BASELINE, P-ROLE, G-PLAN, G-NOSEND, G-CONSENT, G-PRIVACY) plus `SEC-BOUNDARY`. Independent assessment, never LLM self-report. |
| `fred-security-preflight.zip` | A Skill (`SKILL.md`), an AADN profile, and a machine contract: `ScanRequest → ScanPlan(can_dispatch=false, evidence_status=NOT_SCANNED)`. Three gates: local eligibility, trusted connector, promotion. |
| `SystemOS_CaseWeave_P0_Prototype.zip` | A deterministic JavaScript engine: actors with explicit authority limits, Q1–Q6 symbolic tokenization, non-send gates, `assessOutput` error codes. 11 passing Node tests. |
| `BASE44_SETUP.md` | Owner-side workflow for a Base44 **native Superagent** — a separate product that this runtime cannot provision. |
| `PLATFORM_COMPARISON.md` | Two unrelated "Superagent" products: Base44's work agent vs. Superagent.sh's security factory. Staged integration P0→P4. |
| `SYSTEM_IMAGE.md` | `systemos.plugin-fabric` compiled image: Functionings F01–F06, constraints C01–C10, canonical-state rules. |

## 2. Where each piece signalizes

| Reference element | Signalization point in this repo | State |
|---|---|---|
| K/P/G check list | `superagent/supervisor.py` — 12 deterministic checks over a structured trace bundle | **implemented** |
| Supervisor "independent, not self-report" rule | `supervise()` returns `PASS`/`FAIL`/**`UNKNOWN`** per check; a check with no evidence returns `UNKNOWN`, never a promoted pass | **implemented** |
| Supervisor "non-authoritative learning record" | `report["non_authoritative"]`, `report["remediation_policy"]`, and `adapter`'s `learning_record` for failing checks | **implemented** |
| `SEC-BOUNDARY` / `NOT_SCANNED` | `supervisor._check_sec_boundary` — an external provider claim without `run_id` + `target_revision` + `evidence` **fails** | **implemented** |
| Offline preflight contract | `superagent/preflight.py` — `ScanRequest`/`ScanPlan`, `can_dispatch` always `False`, `evidence_status` always `NOT_SCANNED` | **implemented** |
| Preflight Skill procedure (LOCATE→VERIFY) | `fred superagent preflight --kind … --target … [--owner-approved]` | **implemented** |
| Scan dispatch | `dispatch_security_scan()` raises `DispatchDisabled` — no executor exists | **disabled by design** |
| CaseWeave Q1–Q6 engine | `superagent/caseweave.py` — behaviour-preserving Python port (actors, laws, fixture, gates, `assess_output`) | **implemented** |
| CaseWeave React page | not ported — the reference itself never deployed it | **not integrated** |
| Agent hosts: GitHub / Supabase / Gemini | `superagent/surfaces.py` — design contracts over the runtime's own MCP endpoint (`/mcp`), all `enabled: false`, `approval_required: true` | **plan-only** |
| Base44 native Superagent | `surfaces.py` entry `base44_superagent`; provisioning is an owner-side action | **not provisioned** |
| Superagent.sh security workers | `surfaces.py` entry `superagent_sh`; `SUPERAGENT_API_KEY` is a user-supplied secret that has not been set | **not connected** |
| Plugin-fabric Functionings F01–F06 | the capability-descriptor + MCP projection already in `runtime/kernel.py` + `mcp/tools.py`; SA1 adds one governed capability | **partially implemented** |

## 3. The SA1 adapter

`SA1 — Superagent Integration Fabric` is registered in
`fred_os.systems.adapters.default_plugins` and enabled via `[systems] enabled`
in `config/systemos_base.toml` at maturity `implemented_adapter`. It is an
**optional** system on the `default` and `deep_review` routes, so it never
hard-gates a turn and never raises.

Per governed turn it emits, non-mutating:

- `supervision` — the 12-check K/P/G record with an explicit verdict
  (`PASS` / `INCOMPLETE` / `FAIL`);
- `failing_checks` + `learning_record` — the non-authoritative remediation
  input for S7 / `update-skills`;
- `agent_surfaces` — the registered hosts with their enabled/approval flags;
- `assurance` — `NOT_SCANNED`, `can_dispatch: false`.

It reads only structured outputs already present in the turn context
(`s1`, `s2`, `task_planning`). Anything the turn does not carry stays absent so
the matching check reports `UNKNOWN`.

### Capability surface

`sa1.superagent_supervision` is advertised through `RuntimeKernel.list_capabilities()`
and is therefore projected automatically into an MCP tool by
`mcp/tools.py:capability_to_mcp_tool` for any principal the
`TokenAuthenticator` authorises. That is the same path GitHub, Supabase or
Gemini would use to consume the runtime as an agent — they configure the
`/mcp` endpoint with a bearer token, nothing more.

### CLI surface (no kernel boot, no network)

```bash
fred superagent surfaces
fred superagent preflight --kind public_mcp_repo --target modelcontextprotocol/servers --owner-approved
fred superagent caseweave --actor HACLA [--consent] [--review-approved]
fred superagent supervise --bundle trace.json
```

## 4. Honest coverage boundaries

These checks report `UNKNOWN` in a normal governed turn because the runtime
does not yet carry their evidence. They are **not** silently passing:

| Check | Why it is `UNKNOWN` | What would close it |
|---|---|---|
| `P-REPLAY` | no AADN event reducer is integrated | port the AADN reducer and supply `{events, replays}` |
| `P-LEDGER` | the Temporal Sphere in this repo has working/contextual/episodic structures but **no hash-chain lineage** | integrate the TSC draft-1 ledger |
| `P-BASELINE` | the fixed multi-hop fixture is a reference artifact, not a repo fixture | add the fixture and supply `{multi_hop, one_hop}` |
| `K-Q1Q6`, `P-ROLE`, `G-NOSEND`, `G-CONSENT`, `G-PRIVACY` | only meaningful with a CaseWeave case in the turn | call `supervise_caseweave()` / `fred superagent caseweave` |

Additional boundaries carried from the references:

- A positive preflight result is **not** proof of security — it is not a
  finding, a receipt or an approval.
- A compromised local process can still falsify results; SHA-256 is not remote
  attestation and not an authenticated signature.
- No proficiency promotion from one successful test.
- UI/client-side policy checks are not security boundaries.

## 5. Verification

`tests/test_superagent_fabric.py` — 31 tests covering the CaseWeave port
(including the reference's own negative cases), the preflight contract, the
agent surfaces, every supervisor check with both a passing and a failing
control, and the kernel wiring (registration, route membership, capability
dispatch).

```bash
docker compose -f docker-compose.base44.yml exec -T app python -m pytest -q
```
