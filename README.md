# Fred-OS vNext

Fred-OS vNext is the current, evidence-governed implementation path for System-OS.

It does **not** claim background cognition, hidden persistence, independent agency, or a proprietary model-internal memory. It provides explicit runtime components that a host application can instantiate, inspect, test, and persist:

- a deterministic `RuntimeKernel` with frozen TOML configuration;
- governance pre-scan before routing or retrieval;
- a dependency-resolved registry for explicit S1–S13 adapters;
- a Semantic Memory Lake with versioned artifacts, immutable DeepLinks, authority/lifecycle labels, and recall receipts;
- a local SQLite ledger with hash-linked audit events;
- structured observability events carrying the active configuration hash.

## Migration status

This branch, `revamp/systemos-runtime-vnext`, is an executable migration foundation. The kernel and semantic-memory vertical slice are implemented and locally tested. System adapters are explicitly labeled by maturity in configuration; registration does not claim that every historical System specification has been fully ported.

Legacy `main` remains untouched as the original-architecture baseline.

## Quick start

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

## Architecture

```text
RuntimeKernel
  config → invariants → governance → observability → semantic memory → registry → router
                                              │
                     artifacts / revisions / fragments / DeepLinks / audit events
```

See `MIGRATION_STATUS.md` and the configuration under `config/`.
