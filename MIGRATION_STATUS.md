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

System-1 is now an executable, modular Cognitive Mapping port with:

- deterministic extraction that does not require repeated phrases;
- concept normalization, typed graph edges, emergence candidates, uncertainty drivers, KPI signals, and Mermaid output;
- required/missing facet tracking plus bounded retrieval recommendation;
- versioned-memory recall handoff and candidate-only write posture;
- optional bounded telemetry overlay for S7/S12 review;
- configuration, schema, specification, algorithm note, demo, and regression tests.

## Remaining work

1. Validate the branch in GitHub Actions before merge.
2. Add optional upstream NLP adapters for dependency parsing, NER, and coreference resolution.
3. Migrate System-2 through System-13 using the same spec → code → schema → config → example → test pattern.
4. Inventory and archive or rewrite remaining legacy modules by authority and maturity.

The repository distinguishes implemented code, tested prototypes, candidates, governance policy, and historical lineage. No artifact is treated as proof of hidden or autonomous runtime behavior.
