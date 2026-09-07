# M2.2 — Service Lifecycle & Deployment Hardening

Status: implementation milestone

## Purpose

M2.2 hardens the real Streamable HTTP service lifecycle over the M2.1 process-safe substrate. It does **not** change cognitive routing, governance, idempotency semantics, StateCapsule authority, or the `TX_COMMIT` / `TX_ABORT` transaction boundary.

The service layer owns only process lifecycle concerns:

```text
process supervisor
    |
    v
FRED OS HTTP worker
    |- post-fork resource ownership
    |- serialized bootstrap/schema initialization
    |- liveness/readiness probes
    |- drain-aware SIGTERM/SIGINT handling
    `- transport quiescence before socket close
    |
    v
MCP adapter
    |
    v
CommandGateway
    |
    v
RuntimeKernel
    |
    v
TX_COMMIT / TX_ABORT + StateCapsule authority
```

## Authority invariant

Coordination still manages access to authority; it never becomes authority.

- service bootstrap lock = who may initialize/verify process resources
- runtime `flock` = who may mutate authoritative runtime state
- gateway lease = who owns one logical idempotent request
- StateCapsule = reconstructable durable state
- `TX_COMMIT` = authoritative transaction decision

Neither `/readyz`, a lifecycle state, a PID owner marker, nor the bootstrap lock can create or advance authoritative state.

## 1. Post-fork ownership

`InterProcessRuntimeLock`, `IdempotencyStore`, `CommandGateway`, and service lifecycle objects record the PID that constructed them. Using an inherited object from another PID raises `ProcessOwnershipError` and fails closed.

This establishes the worker contract:

> FRED OS runtime, gateway, SQLite coordination objects, event-loop state, and service lifecycle objects must be created inside the process that serves requests.

A supervisor may fork before FRED OS initialization, or use spawn / fork+exec. A child must not continue using parent-created FRED OS service resources.

## 2. Serialized bootstrap

The CLI builds the runtime/gateway under a separate configured bootstrap lock:

```text
service.bootstrap.lock
    |
    |- RuntimeKernel.boot()
    |- runtime authority verification / genesis if needed
    |- IdempotencyStore schema create/migrate
    |- CommandGateway creation
    `- token validation
```

The bootstrap lock is released before request serving. It is deliberately distinct from the runtime transaction lock so startup/migration coordination does not become transaction authority.

Current defaults:

```toml
[service]
bootstrap_lock_path = "data/service.bootstrap.lock"
bootstrap_timeout_seconds = 30.0
bootstrap_probe_timeout_seconds = 0.02
shutdown_grace_seconds = 30.0
drain_quiesce_seconds = 0.25
```

## 3. Service states

Each Streamable HTTP worker owns a `ServiceLifecycle`:

```text
STARTING -> READY -> DRAINING -> STOPPED
```

- `STARTING`: socket/lifespan startup has not completed; `/readyz` fails.
- `READY`: new MCP tool calls may enter the request scope.
- `DRAINING`: process is alive but no new cognitive tool call may start.
- `STOPPED`: service has exited its serving lifecycle.

The HTTP runner does not mark READY until Uvicorn reports that server startup has completed.

## 4. Graceful drain

FRED OS installs its own SIGTERM/SIGINT handlers for the supervised HTTP worker and disables Uvicorn's competing signal capture in the embedded server instance.

Signal handling is non-raising:

```text
SIGTERM / SIGINT
    |
    v
mark DRAINING
    |
    |- refuse new MCP cognitive calls
    `- do not cancel the active synchronous Gateway/RuntimeKernel call
            |
            v
       TX_COMMIT / TX_ABORT
            |
            v
       gateway result finalization
            |
            v
       active request count -> 0
            |
            v
       short MCP transport-quiescence window
            |
            v
       close HTTP listener and exit
```

The signal handler avoids acquiring the lifecycle condition lock because Python signals may arrive while the main thread already owns that lock. It only sets process-local drain markers.

### Transport quiescence

MCP Streamable HTTP clients may send protocol cleanup traffic after the tool result has been delivered. Closing the listener immediately after the cognitive request scope reaches zero can therefore produce a client-side connection failure even though the transaction committed correctly.

M2.2 keeps the listener open for a short configurable quiescence interval after cognitive work has drained. The service remains `DRAINING`, so new FRED OS tool calls are still rejected while MCP teardown can complete.

## 5. `/healthz` and `/readyz`

### `/healthz`

Liveness answers whether the process/event loop is responding. A draining worker remains live:

```json
{
  "status": "ok",
  "state": "DRAINING",
  "pid": 1234,
  "active_requests": 1
}
```

### `/readyz`

Readiness is fail-closed and verifies that the worker can reasonably accept new state-mutating gateway traffic. It checks:

- lifecycle is `READY`
- kernel is `READY`
- gateway SQLite can obtain short-lived write intent and verify its schema
- bootstrap/migration lock is not active
- worker's process-local StateCapsule view can synchronize with the latest committed authority when the runtime transaction lock is available

Ordinary runtime transaction contention does **not** make a worker unready. If another worker currently owns the authoritative transaction lock, readiness reports `state_tail="transaction_busy"` without treating that coordinated contention as a fault.

An externally held/busy SQLite write transaction does make `/readyz` return `503` while `/healthz` remains `200`.

## 6. Multi-process service topology

M2.2 validates multiple independent Streamable HTTP worker processes sharing one state directory. Each worker owns:

- its PID-bound runtime/gateway/service objects
- its own HTTP socket/port in the acceptance suite
- its own event loop

They share only the M2.1 coordinated substrate:

- runtime WAL and StateCapsule store
- runtime advisory lock
- gateway SQLite WAL idempotency database
- bootstrap lock

The built-in CLI still launches one Uvicorn worker per process. Production horizontal replication should be owned by systemd, Docker, Kubernetes, or another supervisor until a later deployment tranche explicitly validates a same-listener multi-worker process-manager configuration.

## 7. Acceptance proof

`tests/test_m2_2_service_lifecycle.py` proves:

1. a fork-inherited `CommandGateway` fails closed with `ProcessOwnershipError`, while a freshly constructed child process succeeds;
2. real SIGTERM during an active MCP-over-HTTP turn allows the turn to return `SUCCESS`, writes the expected `TX_COMMIT`, finalizes the canonical `mcp:<host-idempotency-key>` gateway row as `COMPLETE`, and exits code 0;
3. eight concurrent HTTP worker subprocesses can bootstrap one fresh state directory, producing exactly one genesis commit and one valid gateway schema while all workers reach `/readyz`;
4. rolling handover from worker A to worker B preserves the authoritative StateCapsule chain and accepts new work after A drains;
5. `/healthz` stays 200 while `/readyz` fails 503 when the gateway SQLite database cannot obtain write intent;
6. once lifecycle state becomes DRAINING, a new MCP tool call is rejected before any new WAL transaction begins.

The full repository acceptance run for the implementation branch passed 59 tests.

## Known boundary

M2.2 proves service-process lifecycle behavior for independently supervised worker processes. It does not claim that arbitrary pre-fork ASGI managers can preload a fully constructed FRED OS application and safely share inherited objects. The opposite is enforced: inherited process-local resources fail closed and must be reconstructed post-fork.
