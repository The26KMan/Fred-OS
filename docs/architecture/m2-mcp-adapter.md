# M2 — Model Context Protocol Adapter

Status: implementation milestone

## Purpose

M2 exposes the M1 `CommandGateway` through Model Context Protocol without moving any cognitive, governance, routing, or state authority into the transport layer.

```text
MCP host/model
    |
    v
MCP transport (stdio or Streamable HTTP)
    |
    v
MCP adapter
    |- authorized tools/list projection
    |- tools/call -> GatewayRequest translation
    |- idempotency metadata mapping
    `- context-bounded forensic result formatting
    |
    v
CommandGateway.execute()
    |
    v
RuntimeKernel.dispatch()
```

## Transport lifecycle

### stdio — default local lifecycle

Use stdio for desktop/IDE/local agent hosts. The host launches `fred mcp serve` as a child process and owns its lifetime. One MCP process owns one booted RuntimeKernel + CommandGateway pair and exits when the stdio session ends.

This is the preferred initial integration mode because it has no listening port, naturally scopes credentials and state ownership to the launching host, and maps directly to MCP's client-spawned subprocess model.

### Streamable HTTP — supervised service lifecycle

Use Streamable HTTP for remote or shared clients. `fred mcp serve --transport streamable-http` runs a foreground ASGI service; systemd, Docker, Kubernetes, or another process supervisor should own daemonization, restart policy, TLS termination, and external secret injection.

The current runtime is single-writer, so M2 constrains the HTTP service to one worker and serializes calls inside one MCP process. Multi-worker or multi-process runtime dispatch remains out of scope until the WAL/StateCapsule layer has explicit concurrent-writer locking.

### SSE

M2 does not add new SSE transport support. Current MCP guidance supersedes SSE with Streamable HTTP for new deployments.

## Capability exposure

M2 does not hardcode tools. `tools/list` reads `RuntimeKernel.list_capabilities()` and filters each capability through the same `TokenAuthenticator` authorization rules used by M1. Unauthorized capabilities are not advertised to the host.

Each runtime capability descriptor maps directly to:

- MCP tool `name`
- deterministic description
- runtime-owned JSON `input_schema`

The low-level MCP server is used so FRED OS schemas are published exactly rather than regenerated from Python function signatures.

## Tool-call translation

A `tools/call` is translated to `GatewayRequest` with:

- `target_capability = MCP tool name`
- `payload = MCP arguments`
- configured gateway token
- runtime/MCP session id
- idempotency key derived from `fredos/idempotencyKey` request metadata when present
- otherwise the MCP request id

The model does not provide or select its authenticated principal. The MCP process is launched/configured with a gateway token; M1 resolves the principal.

## Idempotency

Hosts that can persist a tool-call identity SHOULD send:

```json
{
  "_meta": {
    "fredos/idempotencyKey": "host-stable-tool-call-id"
  }
}
```

That value maps to the M1 idempotency store, allowing a retried MCP request to replay the prior `CommandResult` even if its JSON-RPC request id changes.

M2 deliberately does not derive idempotency solely from tool arguments. Two legitimate calls may have identical arguments and still represent separate intended state transitions.

## Result projection

M2 returns a context-bounded forensic projection rather than dumping internal graphs or repositories. It includes:

- `status`
- caller id
- replay flag
- command id
- StateCapsule id
- receipt ids, parent links, statuses, and proof hashes
- StateDelta before/after hashes and mutation-key summary
- explicit rejection taxonomy when present
- structured ambiguity when present
- compact response/route/competency summaries when available

Raw embeddings, full cognitive graphs, thermal values, and temporal micro-state remain internal unless a future explicit capability exposes them.

A runtime `BLOCKED` result is still a successful MCP transport response because M0.1 intentionally rejected the execution. Gateway/schema/auth failures are returned as MCP tool errors that a model can read and recover from.

## Concurrency

M2 serializes calls through an `asyncio.Lock` and invokes synchronous `CommandGateway.execute()` on the same thread that owns the M1 SQLite idempotency connection. This preserves both the current single-writer RuntimeKernel contract and SQLite's thread-affinity contract.

The synchronous execution may temporarily occupy the MCP event loop during a turn. Moving gateway execution to worker threads is intentionally deferred until M1 storage and RuntimeKernel concurrency are explicitly redesigned for cross-thread execution.

This lock is not a substitute for M0 multi-process WAL locking. It only protects concurrent calls inside one MCP server process.

## CLI

Local stdio:

```bash
FRED_OS_TOKEN=... fred --root . --auth-registry gateway_tokens.json mcp serve
```

Supervised Streamable HTTP (install the optional HTTP extra):

```bash
pip install 'fred-os[http]'
FRED_OS_TOKEN=... fred --root . --auth-registry gateway_tokens.json mcp serve --transport streamable-http --host 127.0.0.1 --port 8765
```

The HTTP process should remain foreground; the deployment environment owns daemonization.
