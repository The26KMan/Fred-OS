# Dream Review — Fred-OS vNext Migration

**Protocol:** DREAM_REVIEW — Divergent Roadmap Exploration and Architecture Mapping  
**Inventory digest:** `c0eb4a2226239d4b`  
**Scope:** Repository migration branches, current runtime implementation, System-1 port, TSC source, System-2 migration material, and current architecture contracts.  
**Boundary:** This is an engineering roadmap. It does not claim that any un-wired module is active in a runtime, nor does it authorize automatic persistence or adaptation.

## Evidence-led status map

| Area | Current status | Basis | Required correction |
|---|---|---|---|
| RuntimeKernel | implemented baseline | Config, governance pre-scan, memory service, registry, and routing are constructed at boot. | Add the temporal service and real adapter wiring to its turn path. |
| Semantic Memory Lake | implemented baseline | Versioned artifacts, fragments, source locators, audit trail, and local retrieval surface exist. | Add formal TSC-shard reference support and restoration/migration tests. |
| System-1 core mapper | implemented baseline | Modular code, schema, example, and local tests are present. | Use the richer runtime adapter rather than the earlier direct plugin. |
| System-1 runtime adapter | implemented but unwired | Adds situation model, temporal cues, gaps, and candidate-only memory posture. | Register it and cover it with an end-to-end kernel test. |
| TSC | implemented but unwired | Bounded working/contextual/episodic data structures, commitments, and heuristic projections are present. | Instantiate it in RuntimeKernel and record turn shards explicitly. |
| TSC ↔ Memory Lake contract | documented only | Current architecture requires reciprocal references. | Add `tsc_shard_id` to durable memory provenance and attach returned node IDs to temporal shards. |
| System-2 | documented migration target | Complete spec and migration guide describe typed associations, uncertainty threading, bridge selection, and modular extraction. | Port only after S1/TSC/Memory are connected and testable. |
| Systems 3–13 | mixed candidate/placeholder/prototype | Maturity labels make this visible. | Migrate one bounded vertical slice at a time; do not re-label a spec as implementation. |
| CI | missing | Local tests exist, but no committed workflow is present. | Add a minimal Python test workflow before merging a foundation branch. |

## Architecture blockers

1. **TSC is not in the active kernel turn path.** The current kernel constructs configuration, governance, observability, memory, registry, and routing, then gives S1 only memory/governance context. It does not construct a `TemporalSphere` or record a shard after a turn.
2. **The registry imports the older S1 plugin.** The richer `System1RuntimeAdapter` is available on the migration branch but not selected by `default_plugins()`.
3. **The TSC/Memory Lake reference is one-sided.** TSC can carry Memory Lake identifiers, but the durable repository does not yet persist a reciprocal `tsc_shard_id` provenance field.
4. **Configuration remains only partly authoritative.** The RuntimeKernel revision correctly identifies the risk of “config theater.” The next patch must not add thresholds or routing policy that bypasses TOML configuration.
5. **Current system maturity must stay honest.** The adapter registry is useful scaffolding, but only S1 and the memory/runtime core have meaningful executable depth today.

## Candidate paths evaluated

| Path | Score | Outcome | Reason |
|---|---:|---|---|
| Integration-first vertical slice | 0.5172 | **recommended** | Directly repairs S1/TSC/Memory/Kernel continuity, then creates an evidence-bearing basis for System-2. |
| Memory-temporal consolidation | 0.4881 | deferred | Still depends on the unwired System-1 runtime adapter to produce meaningful temporal shards. |
| Association-layer first | 0.4950 | rejected for now | Blocked by un-wired S1, un-wired TSC, and the missing reciprocal Memory Lake/TSC contract. |
| Parallel subsystem breadth | 0.3243 | rejected for now | Expands surface area while leaving critical integration and testability gaps unresolved. |

## Recommended staged plan

### Stage 1 — Wire System-1 runtime semantics

Replace the registry binding to the legacy S1 plugin with `System1RuntimeAdapter`. Preserve the existing mapper as the semantic engine beneath it.

**Pass gate:** A kernel turn emits `context_graph`, `gaps`, `signals`, `temporal_state`, candidate-only memory-write status, and a Mermaid map without exceptions.

### Stage 2 — Make TSC a real kernel-owned service

Create `TemporalSphere` during boot from TOML configuration. Before S1, obtain its contextual packet; after S1 and the route complete, call `record_turn()` and emit a shard receipt. TSC remains explicit per-turn code, not a background process.

**Pass gate:** Two related turns demonstrate working/contextual cues, commitment lookup, temporal entropy, and deterministic snapshot output.

### Stage 3 — Restore the bidirectional Memory Lake ↔ TSC contract

Extend the artifact/repository record model with optional `tsc_shard_id`; once an explicit persistence event is approved, write the Memory Lake node/fragment reference onto the temporal shard and the TSC reference into durable provenance.

**Pass gate:** An integration test resolves both directions from a stored memory record to the TSC shard and from that shard to a source DeepLink.

### Stage 4 — Establish integration evidence and CI

Add kernel-to-memory-to-TSC tests, a temporary database fixture, migration/snapshot tests, and a minimal GitHub Actions workflow. Keep current local test outcomes separate from CI evidence until CI actually runs.

**Pass gate:** Tests pass locally and in GitHub Actions; status records cite the exact executed test set.

### Stage 5 — Complete System-2 on the proven vertical slice

Port System-2 as a modular association engine. It should consume the S1 context graph and temporal packet, emit typed semantic/analogical/transitive/causal-*hypothesis* edges, account for added uncertainty, rank benefit-per-token bridges, and send bounded handoffs to S6/S7/S8.

**Pass gate:** S1 → TSC → S2 integration tests cover sparse input, uncertainty budget pruning, causal-label honesty, Mermaid output, and DeepLink-carrying evidence context.

## Follow-on sequence after the first vertical slice

1. **System-8 governance hardening:** replace simple cue scanning with evidence-aware policy/covenant records, immutable audit links, and escalation receipts.
2. **System-3 structured NLP:** add an optional parser adapter for NER, dependency triples, and coreference while retaining the dependency-free fallback.
3. **System-6 Influence Map:** consume typed S2 edges and emit graph/diagnostic contributions to the Memory Lake and TSC.
4. **Systems 5 and 9:** implement explicit affect/value-policy contracts; do not treat affect labels or values as private model feelings.
5. **System-7 then System-12:** add bounded adaptation proposals and health diagnostics only after stable metrics and audit inputs exist. System-7 must propose parameter changes through the configuration/policy boundary; it must never override S8.
6. **System-4 and System-10:** add optional quantum-inspired and artistic adapters with capability flags and clear simulation boundaries.
7. **Systems 11 and 13:** reserve evolutionary/adaptive mechanisms for last, after replayable evaluation data, human review, rollback, and calibration harnesses exist.

## Principle retained

The goal is not maximum subsystem count. It is a small, truthful, testable runtime in which each next system has a real contract, an evidence trail, and a reason to exist.
