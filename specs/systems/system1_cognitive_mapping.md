# System-1: Cognitive Mapping

**Version:** vNext 0.1  
**Status:** Implemented baseline; deterministic lexical extraction with optional upstream NLP enrichment.  
**Maturity:** `implemented` for the current runtime contract; not a claim that every historical S1 extension is production-complete.

## Purpose

System-1 converts supplied text into an inspectable cognitive map: enriched concepts, typed graph edges, required/missing facets, bounded uncertainty, KPI signals, and a Mermaid representation. It is the first runtime stage after governance pre-scan and may recall evidence from the Semantic Memory Lake.

## Current contract

**Input**

```json
{"text":"...", "context":["optional context"], "enable_emergence":true}
```

**Output**

- `enriched_concepts`: canonical concept records with domain, abstraction, bridges, affect labels, and emergence potential.
- `multi_hop_connections`: direct, analogical, and cross-domain edges.
- `cognitive_graph` plus `mermaid` text.
- `insight_metrics`: normalized graph-quality measures.
- `kpi_signals`: completeness, trajectory-fit contribution, facets, and retrieval recommendation.
- `uncertainty`: score, visible drivers, and unresolved gaps.
- `memory_context`: evidence recall hits, including immutable `deeplink://` locators when a memory backend is available.
- `memory_write_candidate`: always candidate-only. System-1 does not persist inferred facts by itself.

The exact structural validation is in `schemas/systems/system1_cognitive_mapping.schema.json`.

## Processing sequence

```text
text + optional upstream context
  → deterministic candidate extraction
  → normalization and domain enrichment
  → direct / analogical / cross-domain graph edges
  → optional synthesis concepts
  → metrics, facets, KPI, and uncertainty
  → evidence-aware recall packet and Mermaid graph
```

The extractor deliberately does **not** require repeated phrases. The legacy port’s frequency-only threshold could return an empty map for normal, nonrepetitive prompts; vNext ranks domain cues, known System-OS phrases, bridge signals, n-gram structure, and occurrence order.

## KPI behavior

`completeness_contribution` is `domains_covered / target_domains`, with eight target regions: mathematics, physics, philosophy, psychology, logic, spirituality, general, and synthesis. `trajectory_fit_contribution` is bounded to `0.2 × insight_score`.

Required facets are selected from task shape:

- procedural: steps, success criteria, prerequisites, validation;
- comparison: dimensions, contrasts, trade-offs, decision criteria;
- explanation: definition, examples, analogies, applications;
- System-OS/runtime work adds integration contracts and evidence provenance.

When completeness falls below the configured floor, S1 emits `retrieve_increase_completeness`; it does not manufacture absent evidence.

## Memory and DeepLink boundary

When the kernel supplies a Semantic Memory Lake, S1 performs bounded recall and surfaces the receipt. It never treats recall as proof beyond the authority and lifecycle labels attached to the returned source. A new inference remains a candidate until a separate governance-approved persistence path records it.

## Optional telemetry overlay

`system1_neural_overlay.py` is an optional bounded diagnostic model. Its potential, channel gains, and thresholds are clamped to `[0,1]`; it cannot change routing, memory, governance, or system configuration by itself. Its only output is telemetry suitable for S7/S12 review.

## Related artifacts

- Implementation: `src/fred_os/systems/system1_cognitive_mapping.py`
- Optional overlay: `src/fred_os/systems/system1_neural_overlay.py`
- Schema: `schemas/systems/system1_cognitive_mapping.schema.json`
- Tests: `tests/test_system1_cognitive_mapping.py`
- Example: `examples/system1_cognitive_mapping_demo.py`
- Legacy source material should be treated as lineage after this migration, not as a moving runtime authority.
