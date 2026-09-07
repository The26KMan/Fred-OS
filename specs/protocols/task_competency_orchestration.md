# Task–Competency Orchestration Layer (TCOL)

**Version:** 0.1.1

**Status:** Runtime integration specification

**Purpose:** Preserve and modernize the original Task Understanding, Competency Mapping, and Integration/Synthesis expert pattern as an explicit, inspectable, fail-closed runtime layer inside the transactional FRED OS execution path.

## Role in the consolidated runtime

TCOL consumes current-turn state already produced by the RuntimeKernel:

- System-1 task state and uncertainty;
- kernel GovernanceLayer verdict;
- selected protocol route;
- SystemRegistry capability evidence;
- frozen runtime configuration.

It produces a task contract, competency map, execution authorization, and audit-ready explanation. It does not generate final user prose, override GovernanceLayer, mutate configuration, or treat a declared adapter as proof that a capability is implemented.

The consolidated M0 runtime additionally requires that TCOL execution itself be covered by the transaction receipt chain and that any resulting execution effect be accounted for before `TX_COMMIT`.

## PseuLang abstraction logic

```pseulang
DEFINE LAYER TCOL:TaskCompetencyOrchestration
  VERSION: "0.1.1"
  PARADIGM: "config_governed_task_analysis_and_capability_routing"

  INPUTS:
    raw_input: STRING
    s1_state: MAP
    governance_verdict: MAP
    route: MAP
    capability_report: MAP
    config: RuntimeConfig[FROZEN]

  OUTPUTS:
    task_contract: MAP
    competency_map: MAP
    execution_authorization: MAP
    audit_receipt: MAP

  INVARIANTS:
    I-TCOL-01: configuration is the policy source for route, maturity, and competency declarations.
    I-TCOL-02: governance BLOCK terminates downstream provider execution.
    I-TCOL-03: every required competency resolves to at least one execution-ready provider.
    I-TCOL-04: every hard-gate competency resolves to at least one hard-gate-ready provider.
    I-TCOL-05: candidate, disabled, unregistered, unhealthy, or uninitialized providers never satisfy required capability.
    I-TCOL-06: optional providers may be skipped only with explicit observability evidence.
    I-TCOL-07: planning is descriptive; only RuntimeKernel executes systems.
    I-TCOL-08: TCOL runs inside the RuntimeKernel transaction and contributes an ExecutionReceipt.

  FUNCTION ANALYZE_TASK(raw_input, s1_state, governance_verdict, config) RETURNS task_contract:
    normalized := LOWERCASE(raw_input)
    objectives := MATCH_ALL(normalized, config.task_competency.objective_terms)
    constraints := MATCH_ALL(normalized, config.task_competency.constraint_terms)
    explicit_systems := EXTRACT_SYSTEM_IDENTIFIERS(raw_input)
    uncertainty := CLAMP(s1_state.uncertainty, 0, 1)

    gaps := []
    IF s1_state.task_class IN config.task_competency.objective_required_task_classes
       AND LEN(objectives) = 0:
      APPEND "objective_not_detected" TO gaps

    requires_review := (
      governance_verdict.decision = "REVIEW"
      OR uncertainty >= config.task_competency.uncertainty_review_threshold
    )

    RETURN {
      task_class: s1_state.task_class,
      objectives: UNIQUE(objectives),
      constraints: UNIQUE(constraints),
      explicit_systems: explicit_systems,
      uncertainty: uncertainty,
      requires_review: requires_review,
      gaps: gaps
    }
  END FUNCTION

  FUNCTION MAP_COMPETENCIES(route, capability_report, config) RETURNS competency_map:
    competencies := config.task_competency.route_competencies[route.key]
    provider_map := config.task_competency.competency_providers
    resolved := []
    missing_required := []
    missing_hard_gates := []

    FOR competency IN competencies:
      providers := provider_map[competency]
      hard_gate := ANY(provider IN route.hard_gate_systems FOR provider IN providers)
      ready_providers := []

      FOR provider IN providers:
        status := capability_report.systems[provider]
        eligible := status.hard_gate_ready IF hard_gate ELSE status.execution_ready
        IF eligible:
          APPEND provider TO ready_providers

      APPEND {
        competency: competency,
        providers: providers,
        selected_providers: ready_providers,
        hard_gate: hard_gate,
        status: "READY" IF LEN(ready_providers) > 0 ELSE "GAP"
      } TO resolved

      IF LEN(ready_providers) = 0:
        IF hard_gate:
          APPEND competency TO missing_hard_gates
        ELSE:
          APPEND competency TO missing_required

    RETURN {
      route_key: route.key,
      resolutions: resolved,
      missing_required: missing_required,
      missing_hard_gates: missing_hard_gates
    }
  END FUNCTION

  FUNCTION AUTHORIZE(task_contract, competency_map, governance_verdict) RETURNS execution_authorization:
    IF governance_verdict.decision = "BLOCK":
      RETURN {status: "BLOCKED", reason: "governance_block"}
    IF LEN(competency_map.missing_hard_gates) > 0:
      RETURN {status: "BLOCKED", reason: "hard_gate_competency_gap", gaps: competency_map.missing_hard_gates}
    IF LEN(competency_map.missing_required) > 0:
      RETURN {status: "BLOCKED", reason: "required_competency_gap", gaps: competency_map.missing_required}
    IF LEN(task_contract.gaps) > 0:
      RETURN {status: "REVIEW", reason: "task_contract_incomplete", gaps: task_contract.gaps}
    RETURN {status: "AUTHORIZED", reason: "required_competencies_resolved"}
  END FUNCTION
END LAYER
```

## Transaction integration

```text
S1
 ↓
Router
 ↓
CapabilityRegistry.assess_route
 ↓
TaskPlanning
 ↓
TCOL.assess
 ↓
Execution authorization
 ↓
System execution
 ↓
ExecutionReceipt chain
 ↓
StateDelta
 ↓
StateCapsule
 ↓
TX_COMMIT
```

## Integration contract

| Source | Use |
|---|---|
| S1 | Task classification, grounding and uncertainty |
| GovernanceLayer | Pre-execution safety status |
| Router | Route identity, required systems, hard gates and optional providers |
| SystemRegistry | Per-system maturity, health and readiness evidence |
| RuntimeConfig | Route, capability and competency policies |
| RuntimeKernel | Transaction owner and only executor |

## Migration limits

TCOL does not infer implementation maturity from naming, documentation, or registration alone. The SystemRegistry capability ledger remains the evidence source for execution readiness. Optional or future capability richness must be added as declared contracts with tests rather than undocumented behavior.
