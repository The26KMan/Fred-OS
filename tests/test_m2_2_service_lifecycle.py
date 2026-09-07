from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest
from mcp import Client

from fred_os.gateway import CommandGateway, GatewayRequest, IdempotencyStore, TokenAuthenticator, TokenRecord, hash_token
from fred_os.mcp import (
    MCPAdapterConfig,
    ProbeASGIApp,
    ServiceLifecycle,
    ServiceProbeConfig,
    ServiceReadinessProbe,
    build_mcp_server,
)
from fred_os.runtime import RuntimeJournal, RuntimeKernel
from fred_os.runtime.locking import ProcessOwnershipError


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "session_m2_2_service"
TOKEN = "m2-2-service-secret"
CALLER = "m2-2-service-client"


DELAYED_SERVICE_CODE = r'''
from __future__ import annotations
import asyncio
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from fred_os.cli import _build_gateway, _resolve_service_lock
from fred_os.mcp import (
    MCPAdapterConfig,
    ServiceLifecycle,
    ServiceProbeConfig,
    ServiceReadinessProbe,
    build_mcp_server,
    build_streamable_http_app,
    serve_streamable_http,
)

root = Path(sys.argv[1])
registry = Path(sys.argv[2])
port = int(sys.argv[3])
marker = Path(sys.argv[4])
token = sys.argv[5]
session = sys.argv[6]

args = SimpleNamespace(
    root=str(root),
    profile="development",
    auth_registry=str(registry),
    idempotency_store=None,
    session_id=session,
)
kernel, gateway = _build_gateway(args, token)
original = kernel._execute_turn

def delayed(raw_input, command_id):
    marker.write_text(command_id, encoding="utf-8")
    time.sleep(1.25)
    return original(raw_input, command_id)

kernel._execute_turn = delayed
lifecycle = ServiceLifecycle()
server = build_mcp_server(
    gateway,
    MCPAdapterConfig(token=token, session_id=session),
    lifecycle=lifecycle,
)
probe = ServiceReadinessProbe(
    lifecycle,
    gateway,
    ServiceProbeConfig(
        bootstrap_lock_path=_resolve_service_lock(root, kernel.config),
        bootstrap_probe_timeout_seconds=0.02,
    ),
)
app = build_streamable_http_app(server, lifecycle=lifecycle, readiness=probe)
try:
    asyncio.run(
        serve_streamable_http(
            app,
            lifecycle,
            host="127.0.0.1",
            port=port,
            shutdown_grace_seconds=5.0,
        )
    )
finally:
    gateway.close()
    kernel.shutdown()
'''


def prepare(root: Path) -> Path:
    (root / "config" / "profiles").mkdir(parents=True)
    (root / "config" / "systemos_base.toml").write_text(
        (REPO_ROOT / "config" / "systemos_base.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "config" / "profiles" / "development.toml").write_text(
        (REPO_ROOT / "config" / "profiles" / "development.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    registry = root / "gateway_tokens.json"
    registry.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "token_hash": hash_token(TOKEN),
                        "caller_id": CALLER,
                        "permissions": ["gateway.execute", "capability:*"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return registry


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def spawn_cli_service(root: Path, registry: Path, port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "fred_os.cli",
            "--root",
            str(root),
            "--auth-registry",
            str(registry),
            "--token",
            TOKEN,
            "mcp",
            "serve",
            "--transport",
            "streamable-http",
            "--session-id",
            SESSION,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def spawn_delayed_service(root: Path, registry: Path, port: int, marker: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            DELAYED_SERVICE_CODE,
            str(root),
            str(registry),
            str(port),
            str(marker),
            TOKEN,
            SESSION,
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def probe_json(port: int, path: str, *, timeout: float = 1.0) -> tuple[int, dict]:
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def wait_ready(proc: subprocess.Popen[str], port: int, *, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    last = "not contacted"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=2)
            pytest.fail(f"service exited before readiness ({proc.returncode})\nstdout:\n{stdout}\nstderr:\n{stderr}")
        try:
            status, payload = probe_json(port, "/readyz", timeout=0.5)
            last = f"{status} {payload}"
            if status == 200:
                return payload
        except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = repr(exc)
        time.sleep(0.05)
    proc.kill()
    stdout, stderr = proc.communicate(timeout=5)
    pytest.fail(f"service never became ready; last={last}\nstdout:\n{stdout}\nstderr:\n{stderr}")


def stop_service(proc: subprocess.Popen[str], *, timeout: float = 15.0) -> tuple[str, str]:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        pytest.fail(f"service did not stop gracefully\nstdout:\n{stdout}\nstderr:\n{stderr}")
    if proc.returncode != 0:
        pytest.fail(f"service exited {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}")
    return stdout, stderr


def call_http_tool(port: int, text: str, key: str) -> dict:
    async def scenario() -> dict:
        async with Client(f"http://127.0.0.1:{port}/mcp") as client:
            result = await client.call_tool(
                "runtime.process_turn",
                {"input": text},
                meta={"fredos/idempotencyKey": key},
            )
            assert result.is_error is False
            assert isinstance(result.structured_content, dict)
            return dict(result.structured_content)

    return asyncio.run(scenario())


def boot_gateway(root: Path) -> tuple[RuntimeKernel, CommandGateway]:
    kernel = RuntimeKernel.boot(root_dir=root, profile="development", session_id=SESSION)
    auth = TokenAuthenticator(
        [TokenRecord(hash_token(TOKEN), CALLER, ("gateway.execute", "capability:*"))]
    )
    gateway = CommandGateway(
        kernel,
        auth,
        IdempotencyStore(root / "data" / "gateway_idempotency.sqlite3"),
    )
    return kernel, gateway


@pytest.mark.skipif(os.name == "nt", reason="fork ownership proof is POSIX-specific")
def test_prefork_inherited_gateway_fails_closed_but_fresh_process_executes(tmp_path: Path) -> None:
    root = tmp_path / "prefork"
    registry = prepare(root)
    kernel, gateway = boot_gateway(root)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - assertion is evaluated in child process
        os.close(read_fd)
        try:
            gateway.execute(
                GatewayRequest(
                    target_capability="runtime.process_turn",
                    payload={"input": "Design a deterministic migration plan."},
                    idempotency_key="fork-inherited",
                    token=TOKEN,
                    session_id=SESSION,
                )
            )
        except BaseException as exc:
            os.write(write_fd, exc.__class__.__name__.encode("utf-8"))
            os.close(write_fd)
            os._exit(0)
        os.write(write_fd, b"NO_ERROR")
        os.close(write_fd)
        os._exit(1)

    os.close(write_fd)
    child_result = os.read(read_fd, 256).decode("utf-8")
    os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    try:
        assert os.waitstatus_to_exitcode(status) == 0
        assert child_result == ProcessOwnershipError.__name__
    finally:
        gateway.close()
        kernel.shutdown()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "fred_os.cli",
            "--root",
            str(root),
            "--auth-registry",
            str(registry),
            "--token",
            TOKEN,
            "run",
            "--input",
            "Design a deterministic migration plan with immutable DeepLinks.",
            "--idempotency-key",
            "fresh-worker",
            "--session-id",
            SESSION,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["result"]["status"] == "SUCCESS"


@pytest.mark.skipif(os.name == "nt", reason="SIGTERM lifecycle proof is POSIX-specific")
def test_sigterm_mid_mcp_turn_drains_after_commit_and_exits_zero(tmp_path: Path) -> None:
    root = tmp_path / "sigterm"
    registry = prepare(root)
    port = free_port()
    marker = root / "tx-active.txt"
    proc = spawn_delayed_service(root, registry, port, marker)
    wait_ready(proc, port)

    holder: dict[str, object] = {}

    def invoke() -> None:
        try:
            holder["result"] = call_http_tool(
                port,
                "Design a deterministic semantic migration with immutable DeepLinks.",
                "graceful-sigterm",
            )
        except BaseException as exc:  # pragma: no cover - surfaced in main assertion
            holder["error"] = exc

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15.0
    while not marker.exists() and time.monotonic() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=2)
            pytest.fail(f"service exited before active TX marker\nstdout:\n{stdout}\nstderr:\n{stderr}")
        time.sleep(0.02)
    assert marker.exists(), "tool call never entered the delayed transaction"

    proc.send_signal(signal.SIGTERM)
    thread.join(timeout=15)
    assert not thread.is_alive(), "active MCP request did not drain"
    if "error" in holder:
        raise holder["error"]  # type: ignore[misc]
    result = holder["result"]
    assert isinstance(result, dict)
    assert result["status"] == "SUCCESS"

    stdout, stderr = proc.communicate(timeout=15)
    assert proc.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"

    command_id = marker.read_text(encoding="utf-8")
    journal = RuntimeJournal(root / "data" / "runtime.wal.jsonl")
    commits = [entry for entry in journal.entries() if entry.entry_type == "TX_COMMIT"]
    assert any(entry.payload.get("command_id") == command_id for entry in commits)
    with sqlite3.connect(root / "data" / "gateway_idempotency.sqlite3") as connection:
        row = connection.execute(
            "SELECT status,result_json FROM gateway_idempotency WHERE caller_id=? AND idempotency_key=?",
            (CALLER, "mcp:graceful-sigterm"),
        ).fetchone()
    assert row is not None and row[0] == "COMPLETE" and row[1]


def test_eight_concurrent_http_boots_serialize_schema_and_all_become_ready(tmp_path: Path) -> None:
    root = tmp_path / "boot-race"
    registry = prepare(root)
    ports = [free_port() for _ in range(8)]
    workers = [spawn_cli_service(root, registry, port) for port in ports]
    try:
        payloads = [wait_ready(proc, port, timeout=45.0) for proc, port in zip(workers, ports)]
        assert all(payload["status"] == "ready" for payload in payloads)
        journal = RuntimeJournal(root / "data" / "runtime.wal.jsonl")
        entries = journal.entries()
        assert len([entry for entry in entries if entry.entry_type == "GENESIS_COMMIT"]) == 1
        with sqlite3.connect(root / "data" / "gateway_idempotency.sqlite3") as connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='gateway_idempotency'"
            ).fetchone()
        assert table is not None
    finally:
        for proc in workers:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        for proc in workers:
            stdout, stderr = proc.communicate(timeout=20)
            assert proc.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"


@pytest.mark.skipif(os.name == "nt", reason="rolling SIGTERM handover proof is POSIX-specific")
def test_rolling_restart_handover_keeps_new_worker_serviceable(tmp_path: Path) -> None:
    root = tmp_path / "rolling"
    registry = prepare(root)
    port_a, port_b = free_port(), free_port()
    worker_a = spawn_cli_service(root, registry, port_a)
    worker_b: subprocess.Popen[str] | None = None
    try:
        wait_ready(worker_a, port_a)
        first = call_http_tool(
            port_a,
            "Design semantic migration stage one with immutable DeepLinks.",
            "rolling-a",
        )
        assert first["status"] == "SUCCESS"

        worker_b = spawn_cli_service(root, registry, port_b)
        ready_b = wait_ready(worker_b, port_b)
        assert ready_b["status"] == "ready"
        assert ready_b["state_tail"] == first["state_capsule_id"]

        stop_service(worker_a)
        second = call_http_tool(
            port_b,
            "Design semantic migration stage two with immutable DeepLinks.",
            "rolling-b",
        )
        assert second["status"] == "SUCCESS"
        assert second["state_capsule_id"] != first["state_capsule_id"]
    finally:
        if worker_a.poll() is None:
            stop_service(worker_a)
        if worker_b is not None and worker_b.poll() is None:
            stop_service(worker_b)

    journal = RuntimeJournal(root / "data" / "runtime.wal.jsonl")
    commits = [entry for entry in journal.entries() if entry.entry_type == "TX_COMMIT"]
    assert [int(entry.payload["capsule_sequence"]) for entry in commits] == [1, 2]


def test_healthz_stays_live_while_readyz_fails_closed_on_busy_gateway_db(tmp_path: Path) -> None:
    root = tmp_path / "probes"
    prepare(root)
    kernel, gateway = boot_gateway(root)
    lifecycle = ServiceLifecycle()
    lifecycle.mark_ready()
    readiness = ServiceReadinessProbe(
        lifecycle,
        gateway,
        ServiceProbeConfig(
            bootstrap_lock_path=root / "data" / "service.bootstrap.lock",
            bootstrap_probe_timeout_seconds=0.02,
            idempotency_probe_timeout_ms=30,
        ),
    )

    async def inner(scope, receive, send):  # pragma: no cover - probes intercept first
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = ProbeASGIApp(inner, lifecycle, readiness)

    async def request(path: str) -> tuple[int, dict]:
        messages: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await app(
            {"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""},
            receive,
            send,
        )
        status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return int(status), json.loads(body.decode("utf-8"))

    try:
        health_status, _ = asyncio.run(request("/healthz"))
        ready_status, ready_payload = asyncio.run(request("/readyz"))
        assert health_status == 200
        assert ready_status == 200
        assert ready_payload["status"] == "ready"

        blocker = sqlite3.connect(root / "data" / "gateway_idempotency.sqlite3", isolation_level=None)
        blocker.execute("PRAGMA journal_mode=WAL")
        blocker.execute("BEGIN IMMEDIATE")
        try:
            health_status, health_payload = asyncio.run(request("/healthz"))
            ready_status, ready_payload = asyncio.run(request("/readyz"))
            assert health_status == 200
            assert health_payload["status"] == "ok"
            assert ready_status == 503
            assert ready_payload["status"] == "not_ready"
            assert ready_payload["idempotency_store"] == "unavailable"
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()
    finally:
        gateway.close()
        kernel.shutdown()


def test_mcp_rejects_new_call_once_lifecycle_is_draining(tmp_path: Path) -> None:
    root = tmp_path / "draining"
    prepare(root)
    kernel, gateway = boot_gateway(root)
    lifecycle = ServiceLifecycle()
    lifecycle.mark_ready()
    server = build_mcp_server(
        gateway,
        MCPAdapterConfig(token=TOKEN, session_id=SESSION),
        lifecycle=lifecycle,
    )
    entries_before = len(kernel.journal.entries())

    async def scenario() -> None:
        async with Client(server) as client:
            lifecycle.request_drain()
            result = await client.call_tool(
                "runtime.process_turn",
                {"input": "Design a deterministic migration plan."},
                meta={"fredos/idempotencyKey": "draining-reject"},
            )
            assert result.is_error is True
            assert result.structured_content["error"] == "ServiceDrainingError"

    try:
        asyncio.run(scenario())
        assert len(kernel.journal.entries()) == entries_before
    finally:
        gateway.close()
        kernel.shutdown()
