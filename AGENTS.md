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

## Tests

```bash
docker compose -f docker-compose.base44.yml exec -T app python -m pytest -q
```

53 tests covering runtime recovery, routing, gateway, MCP, temporal, and
repository pipeline.

## Notes

- The repo's `Docker file` (with a space) references a nonexistent
  `system_os_launcher.py` and uses Python 3.10; it is not used by Base44.
- Python >=3.11 is required (pyproject.toml); the compose uses 3.12-slim.
- No external service credentials are needed — the project is self-contained.
