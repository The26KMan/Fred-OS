# Dream Protocol — Architecture Review and Roadmap Exploration

**Status:** Implemented planning instrument.  
**Scope:** Explicit repository review, dependency-aware roadmap generation, and auditable recommendation.  
**Non-goal:** Dream does not execute migrations, mutate runtime settings, write memory, or claim autonomous background planning.

## Purpose

Dream is the System-OS planning protocol used **before** a substantial implementation tranche. It translates a project inventory into several feasible build paths, tests those paths against architectural constraints, and returns a bounded recommendation with assumptions, blockers, and verification gates.

The name is operational: **Divergent Roadmap Exploration and Architecture Mapping**.

Dream is intentionally separate from the runtime protocol selector. A runtime route decides what components process a user turn. Dream decides what engineering work should happen next.

## Inputs

```pseulang
ENTITY Component {
  id, label, status, maturity, dependencies,
  evidence, risk, estimated_effort, unlock_value, notes
}

ENTITY Constraint {
  id, severity, description, affected_components,
  required_before_progress
}

ENTITY ProjectInventory {
  components: List<Component>
  constraints: List<Constraint>
  architecture_principles: List<String>
}
```

`status` must be explicit: `implemented`, `implemented_unwired`, `tested_prototype`, `documented`, `candidate`, `placeholder`, or `blocked`.

`maturity` records the quality of evidence, not the aspiration of a component.

## PseuLang Logic

```pseulang
PROTOCOL DREAM_REVIEW(inventory: ProjectInventory) -> DreamReview {
  REQUIRE inventory.components ≠ ∅

  graph        := BUILD_DEPENDENCY_GRAPH(inventory.components)
  violations   := CHECK_ARCHITECTURE_CONSTRAINTS(inventory, graph)
  readiness    := MEASURE_COMPONENT_READINESS(inventory.components, graph)
  blockers     := FIND_BLOCKERS(violations, readiness)

  paths := [
    PATH("integration_first", INTEGRATION_WORK(graph)),
    PATH("vertical_slice_first", MINIMUM_END_TO_END_SLICE(graph)),
    PATH("memory_temporal_first", MEMORY_AND_TSC_CONSOLIDATION(graph)),
    PATH("breadth_first", PARALLEL_SUBSYSTEM_PORTS(graph))
  ]

  FOR path IN paths {
    path.order       := TOPOLOGICAL_ORDER(path.work, graph)
    path.score       := SCORE(path,
                              dependency_readiness,
                              evidence_strength,
                              architectural_fit,
                              unlock_value,
                              risk_penalty)
    path.rejections  := EXPLAIN_UNMET_PRECONDITIONS(path, blockers)
  }

  selected := ARGMAX(paths WHERE path.rejections is empty,
                     score)
  plan := STAGE(selected.order,
                gates=[tests, contract_validation, source_provenance, review])

  RETURN DreamReview {
    inventory_digest,
    evidence_boundary,
    blockers,
    candidate_paths: paths,
    recommended_path: selected,
    staged_plan: plan,
    assumptions,
    rejection_log
  }
}

POLICY DREAM_BOUNDARIES {
  NEVER classify a documented or placeholder component as implemented.
  NEVER treat a spec as runtime proof.
  NEVER recommend a downstream port before its required runtime contract exists.
  NEVER recommend automatic persistence or autonomous execution.
  REQUIRE each stage to name a measurable verification gate.
}
```

## Scoring

For each candidate path:

```text
score = 0.30 × dependency_readiness
      + 0.25 × architectural_fit
      + 0.20 × evidence_strength
      + 0.20 × unlock_value
      + 0.05 × reversibility
      − risk_penalty
```

A path with an unresolved critical blocker cannot be selected even if its raw score is high.

## Expected output

Dream returns a structured review containing:

- a normalized component inventory;
- integration and truthfulness blockers;
- multiple candidate paths, including rejected paths;
- one recommended staged plan;
- explicit test, contract, and review gates;
- a source/evidence boundary describing what was inspected.

## Current Fred-OS application

The first Dream review is expected to validate the runtime foundation, connect TSC and the System-1 runtime adapter into the actual kernel, restore the intended bidirectional Memory Lake ↔ TSC cross-reference, then complete System-2 as the first association layer. Only after that vertical slice is tested should additional subsystem ports proceed.
