# Base44 Development Notes

## Project Overview

FRED OS vNext is a Python runtime/library (not a web app). It provides a
transactional kernel, governance, cognitive routing, semantic memory, and an
MCP (Model Context Protocol) transport adapter.

## Running the app

```bash
docker compose -f docker-compose.base44.yml up -d
```

- Web entry point: http://localhost:3000 (status page at `/`, MCP at `/mcp`)
- Base image: `python:3.12-slim` with the repo bind-mounted at `/app`
- Dependencies installed at startup: `pip install -e '.[dev,http]'`
- Dev server: `uvicorn --factory fred_os.dev_server:build_app` (live-reload not
  configured; restart the container after source edits to `dev_server.py` or
  kernel modules)
- Local dev token (`FRED_OS_TOKEN`) is set in compose `environment:` — it is a
  local auth credential, not an external secret. The auth registry JSON is
  generated from it at startup by `dev_server._write_auth_registry`.

## Key files

- `src/fred_os/dev_server.py` — dev ASGI app (HTML status + MCP transport)
- `src/fred_os/cli.py` — CLI entry point (`fred` / `fred-os`)
- `src/fred_os/runtime/kernel.py` — `RuntimeKernel.boot()` transactional core
- `src/fred_os/mcp/server.py` — MCP streamable-http adapter
- `config/systemos_base.toml` — frozen runtime configuration
- `config/profiles/development.toml` — dev profile overrides

## System-2 Concept Association port

- `src/fred_os/systems/system2_concept_association.py` — ported reference S2
  runtime (bounded, non-mutating association overlays). Logic is verbatim from
  the reference bundle `0.3.0-draft.5`; only the shared-kernel import is relative.
- `src/fred_os/systems/neurodynamic_kernel.py` — vendored shared controller,
  digest-pinned (`sha256:978a879b…`). Do not edit without updating the digest.
- `src/fred_os/systems/graph_envelope.py` — builds/validates the reference S1
  Graph Envelope (`schema://S1/graph-envelope/1.0`) that S2 consumes.
- `src/fred_os/systems/system2_adapter.py` — `SystemPlugin` adapter registered in
  `adapters.py` (replaces the former S2 stub). Consumes `payload.graph_envelope`
  or bridges `context["s1"]`; emits `schema://S2/association-envelope/1.0`.
- Schemas under `schemas/system1/` (envelope/context-graph/common) and
  `schemas/system2/`.
- S2 is a **required** system in the `default` and `deep_review` routes, so its
  `process()` must never raise on ordinary input — it returns a status
  (`no_source_graph` / `invalid_source_graph` / `association_overlay`) instead.

**Config-hash gotcha:** changing `config/systemos_base.toml` changes the frozen
config hash. A kernel boot against stale committed state then fails with
"Committed StateCapsule config hash … does not match active config …". Reset the
gitignored dev state (`data/runtime_state.jsonl`, `data/runtime.wal.jsonl`) to
start a fresh genesis.

## Tests

```bash
docker compose -f docker-compose.base44.yml exec -T app python -m pytest -q
```

86 tests: runtime recovery, routing, gateway, MCP, temporal, repository
pipeline, and the System-2 port (`test_system2_concept_association.py`,
`test_system2_adapter.py`).

## Notes

- The repo's `Docker file` (with a space) references a nonexistent
  `system_os_launcher.py` and uses Python 3.10; it is not used by Base44.
- Python >=3.11 is required (pyproject.toml); the compose uses 3.12-slim.
- No external service credentials are needed — the project is self-contained.
