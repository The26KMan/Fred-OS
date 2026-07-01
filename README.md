# Fred-OS vNext

Fred-OS vNext is the current, evidence-governed implementation path for System-OS.

It does **not** claim background cognition, hidden persistence, independent agency, or a proprietary model-internal memory. It provides explicit runtime components that an application can instantiate, inspect, test, and persist:

- a deterministic `RuntimeKernel` with frozen TOML configuration;
- governance pre-scan before routing or retrieval;
- a plugin registry for explicit S1–S13 adapters;
- Semantic Memory Lake policy for thermal, graph, checkpoint, and outcome-gated recall;
- a durable SQLite Semantic Memory Repository with versioned artifacts and immutable DeepLinks;
- structured observability events carrying the active configuration hash.

## Migration status

This branch, `revamp/systemos-runtime-vnext`, is an executable migration foundation. The runtime kernel and memory layer are implemented and tested. System adapters are explicitly labeled by maturity in configuration; registration does not claim that every historical System specification has been fully ported.

Legacy `main` remains untouched as the original-architecture baseline.

## Quick start

```bash
python -m pip install -e '.[dev]'
fred-os boot --profile development
fred-os ingest --artifact-id architecture --file docs/architecture/current_runtime.md
fred-os query --text "semantic memory DeepLinks"
pytest -q
```

## Architecture

```text
RuntimeKernel
  config → invariants → governance → observability → memory → registry → protocol engine
                                              │
                              Semantic Memory Lake + Semantic Repository
                                              │
                            versioned artifacts / fragments / DeepLinks / audit
```

See `docs/architecture/current_runtime.md`, `docs/migration/REVAMP_PLAN.md`, and `docs/truthfulness_boundaries.md`.
