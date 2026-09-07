"""Cross-process execution lock and process-ownership guards for FRED OS.

The runtime lock is advisory and process-owned. On POSIX it uses ``flock`` so
the kernel releases ownership automatically if a worker exits or is SIGKILLed.
The lock file's JSON payload is diagnostic metadata only; it is never used as
an authority source and stale metadata does not prevent recovery.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import IO


class RuntimeLockTimeout(TimeoutError):
    """The runtime transaction lock could not be acquired before its deadline."""


class ProcessOwnershipError(RuntimeError):
    """A process-local runtime/service resource was used after fork inheritance."""


def assert_process_owner(owner_pid: int, component: str) -> None:
    """Fail closed if a process-local object was inherited into another PID.

    M2.2 intentionally requires runtime/gateway resources to be constructed in
    the worker that uses them. This prevents future pre-fork supervisors from
    accidentally sharing inherited SQLite handles, event-loop state, or an
    already-open transaction-lock descriptor.
    """
    current_pid = os.getpid()
    if int(owner_pid) != current_pid:
        raise ProcessOwnershipError(
            f"{component} belongs to pid {owner_pid}, but is being used by pid {current_pid}; "
            "construct FRED OS service resources post-fork in each worker"
        )


@dataclass(frozen=True)
class RuntimeLockOwner:
    pid: int
    acquired_at: float


class InterProcessRuntimeLock:
    """Exclusive advisory lock around BOOT authority and TX_START..TX_COMMIT/ABORT."""

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0, poll_seconds: float = 0.025) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        self.poll_seconds = float(poll_seconds)
        self._handle: IO[str] | None = None
        self.owner_pid = os.getpid()

    def acquire(self) -> RuntimeLockOwner:
        assert_process_owner(self.owner_pid, "InterProcessRuntimeLock")
        if self._handle is not None:
            raise RuntimeError("runtime lock is already held by this object")
        handle = self.path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self._try_lock(handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise RuntimeLockTimeout(
                        f"timed out acquiring runtime transaction lock {self.path} after {self.timeout_seconds:.3f}s"
                    )
                time.sleep(self.poll_seconds)
        owner = RuntimeLockOwner(pid=os.getpid(), acquired_at=time.time())
        handle.seek(0)
        handle.truncate(0)
        handle.write(json.dumps({"pid": owner.pid, "acquired_at": owner.acquired_at}, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle
        return owner

    def release(self) -> None:
        assert_process_owner(self.owner_pid, "InterProcessRuntimeLock")
        handle = self._handle
        if handle is None:
            return
        try:
            self._unlock(handle)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> "InterProcessRuntimeLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    @staticmethod
    def _try_lock(handle: IO[str]) -> None:
        if os.name == "nt":  # pragma: no cover - CI is POSIX; retained for local portability.
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BlockingIOError from exc
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle: IO[str]) -> None:
        if os.name == "nt":  # pragma: no cover
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
