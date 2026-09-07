"""Command-line clients and transport entrances for FRED OS."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

from fred_os.gateway import CommandGateway, GatewayRequest, IdempotencyStore, TokenAuthenticator
from fred_os.runtime import RuntimeKernel
from fred_os.runtime.config import ConfigLoader
from fred_os.runtime.locking import InterProcessRuntimeLock


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fred", description="FRED OS gateway and MCP transport client")
    parser.add_argument("--root", default=".", help="FRED OS runtime root")
    parser.add_argument("--profile", default="development", help="runtime configuration profile")
    parser.add_argument("--auth-registry", required=True, help="JSON registry containing SHA-256 token hashes")
    parser.add_argument("--token", default=None, help="gateway token; prefer FRED_OS_TOKEN environment variable")
    parser.add_argument("--idempotency-store", default=None, help="SQLite idempotency store path")

    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="execute one capability")
    run.add_argument("--capability", default="runtime.process_turn")
    run.add_argument("--input", required=True)
    run.add_argument("--idempotency-key", default=None)
    run.add_argument("--command-id", default=None)
    run.add_argument("--session-id", default=None)

    mcp = subparsers.add_parser("mcp", help="Model Context Protocol transport adapter")
    mcp_subparsers = mcp.add_subparsers(dest="mcp_command", required=True)
    serve = mcp_subparsers.add_parser("serve", help="serve authorized FRED OS capabilities over MCP")
    serve.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve.add_argument("--session-id", default=None)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    return parser


def _resolve_service_lock(root: Path, config) -> Path:
    value = Path(str(config.get("service.bootstrap_lock_path", "data/service.bootstrap.lock")))
    return value if value.is_absolute() else root / value


def _build_gateway(args: argparse.Namespace, token: str) -> tuple[RuntimeKernel, CommandGateway]:
    """Build process-local runtime/gateway resources under one bootstrap lock.

    The bootstrap lock serializes schema creation/migration and initial runtime
    authority inspection across workers. It is released before request serving
    and never becomes transaction authority.
    """
    root = Path(args.root).resolve()
    session_id = getattr(args, "session_id", None)
    config = ConfigLoader.build(root_dir=root, profile=args.profile)
    bootstrap_lock = InterProcessRuntimeLock(
        _resolve_service_lock(root, config),
        timeout_seconds=float(config.get("service.bootstrap_timeout_seconds", 30.0)),
    )
    kernel: RuntimeKernel | None = None
    with bootstrap_lock:
        try:
            kernel = RuntimeKernel.boot(root_dir=root, profile=args.profile, session_id=session_id)
            store_path = (
                Path(args.idempotency_store)
                if args.idempotency_store
                else root / "data" / "gateway_idempotency.sqlite3"
            )
            gateway = CommandGateway(
                kernel,
                TokenAuthenticator.from_file(args.auth_registry),
                IdempotencyStore(
                    store_path,
                    busy_timeout_ms=int(kernel.config.get("gateway.idempotency_busy_timeout_ms", 10_000)),
                    lease_seconds=float(kernel.config.get("gateway.idempotency_lease_seconds", 30.0)),
                    wait_seconds=float(kernel.config.get("gateway.idempotency_wait_seconds", 30.0)),
                    poll_seconds=float(kernel.config.get("gateway.idempotency_poll_seconds", 0.025)),
                ),
            )
            gateway.authenticator.authenticate(token)
            return kernel, gateway
        except Exception:
            if kernel is not None:
                kernel.shutdown()
            raise


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = args.token or os.environ.get("FRED_OS_TOKEN", "")
    if not token:
        print(json.dumps({"error": "gateway token required via FRED_OS_TOKEN or --token"}), file=sys.stderr)
        return 2

    kernel: RuntimeKernel | None = None
    gateway: CommandGateway | None = None
    try:
        kernel, gateway = _build_gateway(args, token)
        if args.command == "run":
            response = gateway.execute(
                GatewayRequest(
                    target_capability=args.capability,
                    payload={"input": args.input},
                    idempotency_key=args.idempotency_key or f"ik-{uuid.uuid4().hex}",
                    token=token,
                    session_id=args.session_id,
                    command_id=args.command_id,
                )
            )
            print(json.dumps(response.to_dict(), sort_keys=True, ensure_ascii=False))
            return 0

        if args.command == "mcp" and args.mcp_command == "serve":
            from fred_os.mcp import (
                MCPAdapterConfig,
                ServiceLifecycle,
                ServiceProbeConfig,
                ServiceReadinessProbe,
                build_mcp_server,
                build_streamable_http_app,
                run_stdio_server,
                serve_streamable_http,
            )

            if args.transport == "stdio":
                server = build_mcp_server(
                    gateway,
                    MCPAdapterConfig(token=token, session_id=args.session_id),
                )
                asyncio.run(run_stdio_server(server))
                return 0

            try:
                import uvicorn  # noqa: F401
            except ImportError as exc:  # pragma: no cover - packaging path
                raise RuntimeError("streamable-http requires `pip install 'fred-os[http]'`") from exc

            lifecycle = ServiceLifecycle()
            server = build_mcp_server(
                gateway,
                MCPAdapterConfig(token=token, session_id=args.session_id),
                lifecycle=lifecycle,
            )
            root = Path(args.root).resolve()
            probe = ServiceReadinessProbe(
                lifecycle,
                gateway,
                ServiceProbeConfig(
                    bootstrap_lock_path=_resolve_service_lock(root, kernel.config),
                    bootstrap_probe_timeout_seconds=float(
                        kernel.config.get("service.bootstrap_probe_timeout_seconds", 0.02)
                    ),
                ),
            )
            app = build_streamable_http_app(server, lifecycle=lifecycle, readiness=probe)
            asyncio.run(
                serve_streamable_http(
                    app,
                    lifecycle,
                    host=args.host,
                    port=args.port,
                    shutdown_grace_seconds=float(kernel.config.get("service.shutdown_grace_seconds", 30.0)),
                    drain_quiesce_seconds=float(kernel.config.get("service.drain_quiesce_seconds", 0.25)),
                )
            )
            return 0
        return 2
    except Exception as exc:
        print(json.dumps({"error": exc.__class__.__name__, "message": str(exc)}), file=sys.stderr)
        return 2
    finally:
        if gateway is not None:
            gateway.close()
        if kernel is not None:
            kernel.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
