# Fred-OS vNext Migration Status

`main` remains the original-architecture baseline. Active migration work is isolated on `revamp/systemos-runtime-vnext`.

Implemented foundation in this branch:

- Python package metadata and minimal dependency policy.
- TOML configuration with profile overlay.
- Frozen configuration hash and boot invariants.
- Kernel-level governance pre-scan.
- Structured event receipts.
- Explicit system-plugin contract and dependency registry.

Next implementation tranche:

1. Semantic Memory Lake with immutable DeepLinks and audit ledger.
2. RuntimeKernel, protocol selection, and declared system adapters.
3. Migration inventory and per-System modular ports with tests.

The branch distinguishes implemented code, tested prototypes, candidates, governance policy, and historical lineage. No repository artifact is treated as proof of hidden or autonomous runtime behavior.
