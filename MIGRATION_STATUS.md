# Fred-OS vNext Migration Status

`main` remains the original-architecture baseline. The runtime foundation is isolated on `revamp/systemos-runtime-vnext`; the first complete subsystem port is isolated on `revamp/system1-cognitive-mapping`.

## Implemented runtime foundation

- Python package metadata and minimal dependency policy.
- TOML configuration with development profile overlay.
- Frozen configuration hash and boot invariants.
- Kernel-level governance pre-scan.
- Structured event receipts.
- Explicit system-plugin contract and dependency registry.
- Semantic artifact store with versioned revisions, immutable DeepLinks, and audit events.

## System-1 migration tranche

System-1 is an executable, modular Cognitive Mapping port with deterministic extraction, concept normalization, typed graph edges, emergence candidates, uncertainty drivers, KPI signals, Mermaid output, candidate-only memory writes, configuration, schema, documentation, demo, and regression tests.

## Integration tranche in review

The Dream review selected an integration-first vertical slice before a System-2 port.

- The registry now selects the System-1 runtime adapter, which adds a situation model, temporal cues, gaps, and explicit memory-write candidates.
- The kernel now owns a bounded Temporal Sphere Component and records a temporal shard after each allowed turn.
- Recalled immutable source fragments can be linked to TSC shard IDs through a durable many-to-many ledger; this preserves reciprocal provenance without automatically treating turn text as durable knowledge.
- The new temporal-runtime test covers a recalled DeepLink, an emitted shard receipt, and reverse lookup from shard to source.

These changes are branch-local until the test suite is run and reviewed. They do not prove hosted-chat persistence, background execution, or completion of the remaining System ports.

## Remaining work

1. Run the full suite locally and in GitHub Actions before merge.
2. Complete the System-2 association port on the integrated S1/TSC/Memory contract.
3. Add optional upstream NLP adapters for dependency parsing, NER, and coreference resolution.
4. Harden System-8 governance and then migrate S6, S5/S9, and S7/S12 through the same spec → code → schema → config → example → test pattern.
5. Inventory and archive or rewrite remaining legacy modules by authority and maturity.

The repository distinguishes implemented code, tested prototypes, candidates, governance policy, and historical lineage. No artifact is treated as proof of hidden or autonomous runtime behavior.
