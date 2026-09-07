# M2.1 — Runtime Concurrency & Transaction Isolation

Status: implementation milestone

## Purpose

M2.1 hardens the shared FRED OS state directory for multiple OS worker processes while preserving the core M0 rule that cognitive state mutation is logically single-writer.

The milestone does **not** make individual transactions parallel. It makes concurrent worker contention deterministic and crash-safe.

```text
Worker A ---------\
                   \
Worker B ------------> InterProcessRuntimeLock
                   /             |
Worker C ---------/              v
                         refresh committed tail
                                  |
                                  v
                         TX_START ... execute
                                  |
                              StateDelta
                                  |
                              CAS parent
                                  |
                         TX_COMMIT / TX_ABORT
                                  |
                                  v
                           release OS lock
```

## Authority model

The authority hierarchy is unchanged:

1. WAL `TX_COMMIT` remains the sole transaction commit authority.
2. StateCapsule records without a matching commit remain non-authoritative candidates.
3. The inter-process lock controls **who may attempt mutation**, not which state is authoritative.
4. Gateway leases control idempotency reservation ownership, not runtime state authority.

## Inter-process runtime lock

`InterProcessRuntimeLock` owns the interval around:

- genesis/boot authority selection
- authoritative state refresh before dispatch
- `TX_START`
- System execution
- StateDelta creation
- candidate StateCapsule persistence
- `TX_COMMIT` or `TX_ABORT`

On POSIX the implementation uses advisory `flock(LOCK_EX)`. The OS releases the lock automatically if a worker exits or is killed. The JSON written into the lock file contains only diagnostic `pid` and acquisition time metadata; stale text never blocks recovery.

A configurable acquisition timeout prevents indefinite application-level waits:

```toml
[runtime]
lock_path = "data/runtime.tx.lock"
lock_timeout_seconds = 30.0
```

## Worker refresh and StateCapsule CAS

A worker may have booted before another process committed. Therefore acquiring the execution lock is followed by an authoritative refresh:

```text
worker.current_capsule
       |
       v
acquire runtime lock
       |
       v
journal.committed_capsule_ids()
       |
       v
StateStore.latest_committed()
       |
       v
rehydrate TSC if tail changed
```

Immediately before candidate persistence/commit, `_assert_authoritative_tail()` verifies:

- the latest WAL commit references the transaction's `before.capsule_id`
- the latest committed StateStore capsule is the same capsule
- the committed sequence equals the transaction parent's sequence

Any mismatch raises `STATE_CAS_MISMATCH` and the normal M0 exception path emits `TX_ABORT`.

The lock prevents legitimate concurrent workers from reaching this mismatch. The CAS check exists as a second invariant against out-of-band writes, corrupted coordination, or future locking regressions.

## Gateway SQLite concurrency

The idempotency store now uses:

- SQLite `journal_mode=WAL`
- configurable `busy_timeout`
- `synchronous=FULL`
- operation-scoped SQLite connections rather than one thread-affine persistent connection
- atomic `BEGIN IMMEDIATE` reservation creation
- reservation owner tokens
- renewable reservation leases
- expired-owner reclamation

Configuration:

```toml
[gateway]
idempotency_busy_timeout_ms = 10000
idempotency_lease_seconds = 30.0
idempotency_wait_seconds = 30.0
idempotency_poll_seconds = 0.025
```

A second worker presenting the same logical request never deletes another live worker's `PENDING` row. It waits for `COMPLETE`, or, if the owner lease expires, checks the authoritative runtime WAL before attempting to claim the reservation.

## Crash recovery

### Worker killed while holding runtime lock

POSIX `flock` is process-owned. `SIGKILL` closes the worker's file descriptors and releases the lock without a stale-lock cleanup protocol.

If the worker had already written `TX_START` but not `TX_COMMIT`, the next worker:

1. acquires the released lock
2. reads the last committed StateCapsule
3. ignores the interrupted transaction as non-authoritative
4. records the interrupted command through existing WAL reconciliation
5. proceeds with a new transaction

### Worker killed while owning idempotency lease

The gateway reservation remains `PENDING` until its renewable lease expires. Because the heartbeat thread dies with the process, another worker can subsequently:

1. observe lease expiry
2. inspect the runtime WAL while holding the runtime lock
3. replay/refuse if an authoritative prior result is known
4. otherwise atomically claim the expired reservation
5. execute against the last committed runtime state

The known M1 post-commit/result-cache gap remains explicit: if `TX_COMMIT` exists but the complete `CommandResult` was never persisted in the gateway store or journal, duplicate execution is refused rather than guessed.

## Acceptance proof

`tests/test_m2_1_runtime_concurrency.py` covers:

- four simultaneous worker processes with unique requests produce one contiguous StateCapsule chain
- two workers racing the same idempotency key execute exactly one transaction and return one replay
- a stale in-memory worker is refreshed before dispatch
- the StateCapsule CAS guard explicitly rejects a stale parent
- a worker is `SIGKILL`ed after `TX_START` while holding the runtime lock; a later worker acquires the lock after process death, waits for gateway lease expiry, recovers the WAL, and successfully commits from the previous authoritative capsule
- the gateway SQLite store remains in WAL mode and finishes the reclaimed reservation as `COMPLETE`

## Deployment boundary

M2.1 proves that multiple OS processes may safely contend for one FRED OS runtime directory. It does not automatically enable arbitrary HTTP worker counts in the CLI.

The next deployment-focused tranche should test the actual Streamable HTTP process manager, worker startup/shutdown, signal handling, health probes, and rolling restart behavior before changing the conservative `workers=1` default.
