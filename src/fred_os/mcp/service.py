"""M2.2 service-process lifecycle for Streamable HTTP deployments.

This module owns process lifecycle semantics only. It does not own routing,
governance, idempotency authority, StateCapsule authority, or transaction
commit decisions.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import asyncio
import json
import os
from pathlib import Path
import signal
import threading
import time
from typing import Any, Iterator

from fred_os.runtime.locking import InterProcessRuntimeLock, RuntimeLockTimeout, assert_process_owner


class ServiceDrainingError(RuntimeError):
    """The service is alive but no longer accepting new work."""


@dataclass
class ServiceLifecycle:
    """Process-local readiness/draining state with active-request accounting."""

    owner_pid: int = field(default_factory=os.getpid)
    state: str = "STARTING"
    active_requests: int = 0
    drain_requested_at: float | None = None
    drain_signal: int | None = None

    def __post_init__(self) -> None:
        self._condition = threading.Condition()

    def _assert_owner(self) -> None:
        assert_process_owner(self.owner_pid, "ServiceLifecycle")

    def mark_ready(self) -> None:
        self._assert_owner()
        with self._condition:
            if self.state == "STARTING":
                self.state = "READY"
                self._condition.notify_all()

    def request_drain(self, sig: int | None = None) -> None:
        self._assert_owner()
        with self._condition:
            if self.state in {"STOPPED", "DRAINING"}:
                return
            self.state = "DRAINING"
            self.drain_requested_at = time.time()
            self.drain_signal = sig
            self._condition.notify_all()

    @contextmanager
    def request_scope(self) -> Iterator[None]:
        self._assert_owner()
        with self._condition:
            if self.state != "READY":
                raise ServiceDrainingError(f"service is not accepting work: {self.state}")
            self.active_requests += 1
        try:
            yield
        finally:
            with self._condition:
                self.active_requests -= 1
                self._condition.notify_all()

    def wait_for_idle(self, timeout_seconds: float) -> bool:
        self._assert_owner()
        deadline = time.monotonic() + max(float(timeout_seconds), 0.0)
        with self._condition:
            while self.active_requests:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def mark_stopped(self) -> None:
        self._assert_owner()
        with self._condition:
            self.state = "STOPPED"
            self._condition.notify_all()

    def health(self) -> dict[str, Any]:
        self._assert_owner()
        return {
            "status": "ok" if self.state != "STOPPED" else "stopped",
            "state": self.state,
            "pid": self.owner_pid,
            "active_requests": self.active_requests,
        }


@dataclass(frozen=True)
class ServiceProbeConfig:
    bootstrap_lock_path: Path
    bootstrap_probe_timeout_seconds: float = 0.02


class ServiceReadinessProbe:
    """Fail-closed readiness checks without becoming execution authority."""

    def __init__(self, lifecycle: ServiceLifecycle, gateway: Any, config: ServiceProbeConfig) -> None:
        self.lifecycle = lifecycle
        self.gateway = gateway
        self.config = config
        self.owner_pid = os.getpid()

    def check(self) -> tuple[bool, dict[str, Any]]:
        assert_process_owner(self.owner_pid, "ServiceReadinessProbe")
        reasons: list[str] = []
        details: dict[str, Any] = {
            "state": self.lifecycle.state,
            "pid": self.owner_pid,
            "active_requests": self.lifecycle.active_requests,
        }
        if self.lifecycle.state != "READY":
            reasons.append(f"service_state:{self.lifecycle.state}")
        if self.gateway.kernel.status != "READY":
            reasons.append(f"kernel_state:{self.gateway.kernel.status}")

        try:
            self.gateway.idempotency_store.readiness_probe()
            details["idempotency_store"] = "ready"
        except Exception as exc:
            reasons.append(f"idempotency_store:{exc.__class__.__name__}")
            details["idempotency_store"] = "unavailable"

        # A separate bootstrap/migration lock distinguishes deployment startup
        # work from ordinary runtime transaction contention. /readyz should not
        # fail merely because another worker is executing a normal turn.
        try:
            probe_lock = InterProcessRuntimeLock(
                self.config.bootstrap_lock_path,
                timeout_seconds=self.config.bootstrap_probe_timeout_seconds,
                poll_seconds=min(self.config.bootstrap_probe_timeout_seconds or 0.001, 0.005),
            )
            with probe_lock:
                pass
            details["bootstrap_lock"] = "available"
        except RuntimeLockTimeout:
            reasons.append("bootstrap_lock:busy")
            details["bootstrap_lock"] = "busy"

        # Verify that the worker's observed capsule matches the latest committed
        # capsule. Reads are forensic only; TX_COMMIT remains the authority.
        try:
            committed = self.gateway.kernel.journal.committed_capsule_ids()
            latest = self.gateway.kernel.state_store.latest_committed(committed)
            current = self.gateway.kernel.get_current_capsule()
            if latest is None or latest.capsule_id != current.capsule_id:
                reasons.append("state_tail:stale")
                details["state_tail"] = "stale"
            else:
                details["state_tail"] = current.capsule_id
        except Exception as exc:
            reasons.append(f"state_tail:{exc.__class__.__name__}")
            details["state_tail"] = "unavailable"

        ready = not reasons
        return ready, {"status": "ready" if ready else "not_ready", "reasons": reasons, **details}


class ProbeASGIApp:
    """ASGI wrapper adding /healthz and /readyz around the MCP application."""

    def __init__(self, app: Any, lifecycle: ServiceLifecycle, readiness: ServiceReadinessProbe) -> None:
        self.app = app
        self.lifecycle = lifecycle
        self.readiness = readiness

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if path == "/healthz":
                await self._json(send, 200, self.lifecycle.health())
                return
            if path == "/readyz":
                ready, payload = self.readiness.check()
                await self._json(send, 200 if ready else 503, payload)
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _json(send: Any, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})


def install_drain_signal_handlers(lifecycle: ServiceLifecycle, stop_event: threading.Event) -> dict[int, Any]:
    """Install non-raising SIGTERM/SIGINT handlers and return previous handlers.

    The handler only marks the worker draining. Because it does not raise or
    cancel the active call, a synchronous in-flight RuntimeKernel transaction
    continues until its TX_COMMIT/TX_ABORT boundary before service shutdown.
    """
    lifecycle._assert_owner()
    previous: dict[int, Any] = {}

    def handler(sig: int, _frame: Any) -> None:
        lifecycle.request_drain(sig)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, handler)
    return previous


def restore_signal_handlers(previous: dict[int, Any]) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, handler)


class _NoSignalUvicornServer:
    """Compatibility wrapper built lazily so uvicorn remains an optional extra."""

    @staticmethod
    def build(config: Any) -> Any:
        import contextlib
        import uvicorn

        class NoSignalServer(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):
                yield

        return NoSignalServer(config)


async def serve_streamable_http(
    app: Any,
    lifecycle: ServiceLifecycle,
    *,
    host: str,
    port: int,
    shutdown_grace_seconds: float = 30.0,
) -> None:
    """Run one supervised HTTP worker with drain-aware signal semantics."""
    import uvicorn

    lifecycle._assert_owner()
    stop_event = threading.Event()
    previous = install_drain_signal_handlers(lifecycle, stop_event)
    server = _NoSignalUvicornServer.build(
        uvicorn.Config(app=app, host=host, port=int(port), workers=1, lifespan="on")
    )
    lifecycle.mark_ready()
    serve_task = asyncio.create_task(server.serve())
    try:
        while not stop_event.is_set() and not serve_task.done():
            await asyncio.sleep(0.05)
        if stop_event.is_set():
            lifecycle.request_drain(lifecycle.drain_signal)
            idle = lifecycle.wait_for_idle(shutdown_grace_seconds)
            server.should_exit = True
            if not idle:
                server.force_exit = True
            remaining = max(float(shutdown_grace_seconds), 0.1)
            try:
                await asyncio.wait_for(serve_task, timeout=remaining)
            except asyncio.TimeoutError:
                server.force_exit = True
                raise RuntimeError("HTTP worker exceeded graceful shutdown deadline")
        else:
            await serve_task
    finally:
        lifecycle.mark_stopped()
        restore_signal_handlers(previous)
