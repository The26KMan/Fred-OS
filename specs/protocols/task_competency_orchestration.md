# Task–Competency Orchestration Layer (TCOL)

**Version:** 0.1.0

**Status:** Migration-sidecar specification

**Purpose:** Preserve and modernize the original Task Understanding, Competency Mapping, and Integration/Synthesis expert pattern as an explicit, inspectable, fail-closed runtime layer.

## Role in the vNext runtime

TCOL is a compatibility and planning layer, not a claim of autonomous agency or hidden cognition. It consumes the current-turn state already produced by the RuntimeKernel:

- System-1 task state and uncertainty;
- kernel GovernanceLayer verdict;
- the selected protocol route;
- SystemRegistry capability evidence;
- frozen runtime configuration.

It produces a task contract, a competency map, an execution authorization, and an audit-ready explanation. It does not generate final user prose, override GovernanceLayer, mutate configuration, or treat a declared adapter as proof that a capability is implemented.

## PseuLang abstraction logic

```pseulang
DEFINE LAYER TCOL:TaskCompetencyOrchestration
  VERSION: "0.1.0"
  PARADIGM: "config_governed_task_analysis_and_capability_routing"

  INPUTS:
    raw_input: STRING
    s1_state: MAP {
      task_class: STRING,
      entities: LIST<STRING>,
      uncertainty: FLOAT[0..1]
    }
    governance_verdict: MAP {
      decision: ENUM("PASS", "REVIEW", "BLOCK"),
      rationale: STRING,
      score: FLOAT[0..1]
    }
    route: MAP {
      key: STRING,
      name: STRING,
      systems: LIST<STRING>,
      hard_gate_systems: LIST<STRING>,
      optional_systems: LIST<STRING>
    }
    capability_report: MAP
    config: RuntimeConfig[FROZEN]

  OUTPUTS:
    task_contract: MAP
    competency_map: MAP
    execution_authorization: MAP
    audit_receipt: MAP

  INVARIANTS:
    I-TCOL-01: configuration is the sole policy source; no route, maturity, or competency default is hidden in code.
    I-TCOL-02: governance BLOCK terminates planning and execution.
    I-TCOL-03: every required competency must resolve to at least one execution-ready provider.
    I-TCOL-04: every hard-gate competency must resolve to at least one hard-gate-ready provider.
    I-TCOL-05: candidate, disabled, unregistered, unhealthy, or uninitialized providers never satisfy required capability.
    I-TCOL-06: optional providers may be skipped only with an explicit receipt.
    I-TCOL-07: planning is descriptive; only the RuntimeKernel executes systems.
    I-TCOL-08: every output includes route identity and configuration hash through the enclosing observability event.

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

      resolution := {
        competency: competency,
        providers: providers,
        selected_providers: ready_providers,
        hard_gate: hard_gate,
        status: "READY" IF LEN(ready_providers) > 0 ELSE "GAP"
      }
      APPEND resolution TO resolved

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
      RETURN {
        status: "BLOCKED",
        reason: "hard_gate_competency_gap",
        gaps: competency_map.missing_hard_gates
      }

    IF LEN(competency_map.missing_required) > 0:
      RETURN {
        status: "BLOCKED",
        reason: "required_competency_gap",
        gaps: competency_map.missing_required
      }

    IF LEN(task_contract.gaps) > 0:
      RETURN {
        status: "REVIEW",
        reason: "task_contract_incomplete",
        gaps: task_contract.gaps
      }

    RETURN {
      status: "AUTHORIZED",
      reason: "required_competencies_resolved"
    }
  END FUNCTION

  FUNCTION PROCESS(raw_input, s1_state, governance_verdict, route, capability_report, config) RETURNS MAP:
    task_contract := ANALYZE_TASK(raw_input, s1_state, governance_verdict, config)
    competency_map := MAP_COMPETENCIES(route, capability_report, config)
    authorization := AUTHORIZE(task_contract, competency_map, governance_verdict)

    RETURN {
      task_contract: task_contract,
      competency_map: competency_map,
      execution_authorization: authorization,
      audit_receipt: {
        event: "TCOL_ASSESSED",
        route_key: route.key,
        route_name: route.name,
        requested_systems: route.systems,
        hard_gate_systems: route.hard_gate_systems,
        authorization_status: authorization.status
      }
    }
  END FUNCTION
END LAYER
```

## Integration contract

### Upstream

| Source | Required fields | Use |
|---|---|---|
| S1 | `task_class`, `entities`, `uncertainty` | Task classification, grounding, uncertainty review signal |
| GovernanceLayer | `decision`, `rationale`, `score` | Pre-execution safety status |
| Router | `key`, `name`, declared systems and gates | Select the competency policy bundle |
| SystemRegistry | Per-system maturity, health, initialization, availability | Capability evidence |
| RuntimeConfig | Route, capability, and competency policies | Sole policy authority |

### Downstream

| Consumer | Handoff |
|---|---|
| RuntimeKernel | Uses authorization to stop a blocked plan before provider invocation |
| ObservabilityStack | Emits `TCOL_ASSESSED`, capability gap, and completion receipts with configuration hash |
| Semantic Memory Lake | Future milestone: persist approved task checkpoints with immutable DeepLinks only |
| System-7 | Future milestone: inspect task/competency gaps as adaptation evidence; never self-authorize a missing gate |

## Migration limits

This sidecar intentionally does not port all historical expert behavior. Its first executable responsibility is to make the original three-expert pattern honest and testable:

1. **Task Understanding** becomes a structured task contract based on S1 and configuration.
2. **Competency Mapping** becomes explicit provider resolution against registry capability evidence.
3. **Integration and Synthesis** becomes an execution authorization consumed by the RuntimeKernel.

Further expert richness—semantic embeddings, temporal history, DeepLink recall, S2 association packs, and S3 synthesis—must be added as declared contracts with schemas, examples, and tests rather than embedded as undocumented behavior.

## Related files

- `src/fred_os/runtime/task_competency.py` — executable sidecar
- `src/fred_os/runtime/kernel.py` — orchestration and enforcement
- `src/fred_os/runtime/routing.py` — configuration-led route selection
- `src/fred_os/runtime/registry.py` — provider readiness evidence
- `config/systemos_base.toml` — sole source for route and capability policies
- `tests/test_vnext_runtime.py` — contract and fail-closed test slice
