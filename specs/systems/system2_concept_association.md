# System-2: Concept Association

**Version:** vNext 0.1 (ported from reference `0.3.0-draft.5`)
**Status:** Implemented adapter; bounded inferred association overlays over the reference S1 graph envelope.
**Maturity:** `implemented` for the current runtime contract; `production_observed: false`.

## Purpose

System-2 consumes an **immutable reference to a validated S1 Graph Envelope** and
proposes bounded semantic, structural, transitive, and analogical associations. It
emits an **Association Overlay** and never rewrites the canonical S1 graph.

- Input contract: `schema://S1/graph-envelope/1.0`
- Output contract: `schema://S2/association-envelope/1.0`
- Runtime module: `src/fred_os/systems/system2_concept_association.py`
- Adapter: `src/fred_os/systems/system2_adapter.py`
- Shared controller: `src/fred_os/systems/neurodynamic_kernel.py` (digest-pinned)

## Normative invariants

| ID | Requirement |
|---|---|
| S2-NONMUTATION-001 | S2 MUST NOT mutate its input graph or relabel source facts. |
| S2-INFERENCE-001 | Every generated node/edge MUST be `inferred`, `uncertain`, or `rejected`; never `source`. |
| S2-PROVENANCE-001 | Each admitted association MUST reference the input graph id, revision, digest, and supporting path. |
| S2-BOUNDS-001 | Traversal MUST obey depth, confidence, candidate, and output budgets. |
| S2-ADMISSION-001 | Proposal and admission are separate, auditable stages. |
| S2-COMPOSITION-001 | Multi-hop relations MUST use declared composition rules; reachability alone cannot choose semantic type. |
| S2-FEEDBACK-001 | Feedback/cyclic paths MUST be labeled and penalized before admission. |
| S2-EXTERNAL-001 | External neighbors MUST declare origin, anchors, uncertainty, and a source reference where applicable. |
| S2-NEURO-001 | `V_2` and channel gates MUST remain in `[0,1]`; capacitance MUST be positive. |
| S2-CONTROL-001 | Neural state MAY constrain traversal/output budgets but MUST NOT alter epistemic state, evidence, provenance, or confidence. |
| S2-BIOLOGY-001 | The controller is an HH-inspired control analogy, not a biological simulation. |

## Pipeline

```
validate S1 graph envelope
  → advance S2 field state through the shared controller (typed S1→S2 coupling)
  → derive non-destructive control policy
  → propose bounded candidates (bounded_paths + typed composition)
  → admit / reject (one disposition per candidate)
  → build Association Overlay
  → sparse explanatory selection (benefit-per-token)
  → serialize Association Envelope
```

## Path confidence

For path `p=(e_1…e_k)` with calibrated edge confidences `c_e` and decay `α`:

```
C(p) = (∏_{e∈p} c_e) · α^(max(0,k-1))
```

A candidate is admitted only when `C(p) ≥ association_threshold`, bounded by
`max_path_depth`, `max_candidates`, and `max_output_associations`. Paths that
traverse feedback receive `feedback_cycle_penalty`.

## Field control

S2 owns its own bounded control compartment (`V_2`, association-processing
pressure). The controller emits an `AssociationControlPolicy` that is a
**reversible projection over budgets** — it never deletes candidates or state.

| `V_2` region | Depth | Candidates | External | Output | Min path confidence |
|---|---:|---:|---:|---:|---:|
| underactive `< .35` | 4 | 192 | 8 | 32 | .30 |
| stable `< .60` | 4 | 256 | 8 | 48 | .35 |
| exploratory `< .75` | 3 | 128 | 6 | 24 | .45 |
| saturated `< .88` | 2 | 64 | 4 | 8 | .60 |
| critical `≥ .88` | 1 | 24 | 0 | 4 | .75 |

## S1 → S2 coupling

The adapter maps S1 situational signals into S2's own profile — never
`V_target = V_source`:

```
S1 missing facets / unresolved relations → association_demand → S2 structural channel and association budget
```

The signal carries `signal_id`, source, target, type, bounded value, basis, and
authority. S2's field state is explicit and persists across turns in the adapter.

## Configuration

```toml
[systems.s2]
max_path_depth = 4
min_path_confidence = 0.35
association_threshold = 0.60
max_candidates = 256
max_output_associations = 64
max_external_neighbors = 8
transitive_decay = 0.85
feedback_cycle_penalty = 0.65
min_novelty = 0.35
field_enabled = true
harmony_tau = 35.0
```

## Graph envelope bridge

The vNext S1 adapter predates the reference transport contract, so
`src/fred_os/systems/graph_envelope.py` bridges the live S1 output into
`schema://S1/graph-envelope/1.0` and structurally validates it (identity,
epistemic states, dangling edges, digest match) before S2 consumes it. S2 also
accepts a caller-supplied reference envelope directly via `payload.graph_envelope`.

## Capability surface

`kernel.list_capabilities()` exposes `s2.concept_association`, which runs the
transactional turn path and returns the System-2 association overlay in
`outputs.S2`.

## Evidence

- `tests/test_system2_concept_association.py` — 20 ported reference-runtime tests
  (non-mutation, admission, Color Algebraics, external neighbors, BPT selection,
  typed composition/feedback, controller bounds, long-horizon stability).
- `tests/test_system2_adapter.py` — 8 envelope-bridge and adapter/kernel
  integration tests.
- Shared controller digest: `sha256:978a879b9c2a643b6be83cefc1ad43b1889daeac0617174ce4f7fe6ea17268e3`.

Fixture: `tests/fixtures/system2/s1_subject_graph_handoff.json` is a full
reference S1 Graph Envelope used as an integration input.
