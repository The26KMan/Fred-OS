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


def _build_gateway(args: argparse.Namespace, token: str) -> tuple[RuntimeKernel, CommandGateway]:
    root = Path(args.root).resolve()
    session_id = getattr(args, "session_id", None)
    kernel = RuntimeKernel.boot(root_dir=root, profile=args.profile, session_id=session_id)
    store_path = Path(args.idempotency_store) if args.idempotency_store else root / "data" / "gateway_idempotency.sqlite3"
    gateway = CommandGateway(
        kernel,
        TokenAuthenticator.from_file(args.auth_registry),
        IdempotencyStore(store_path),
    )
    # Authenticate during process initialization so a bad configured MCP token
    # fails before a transport begins accepting requests.
    gateway.authenticator.authenticate(token)
    return kernel, gateway


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
            from fred_os.mcp import MCPAdapterConfig, build_mcp_server, build_streamable_http_app, run_stdio_server

            server = build_mcp_server(
                gateway,
                MCPAdapterConfig(token=token, session_id=args.session_id),
            )
            if args.transport == "stdio":
                asyncio.run(run_stdio_server(server))
                return 0

            # Long-lived remote mode runs in the foreground and should be
            # supervised by systemd, Docker, Kubernetes, or an equivalent host.
            # One worker preserves the current single-writer runtime contract.
            try:
                import uvicorn
            except ImportError as exc:  # pragma: no cover - packaging path
                raise RuntimeError("streamable-http requires `pip install 'fred-os[http]'`") from exc
            uvicorn.run(build_streamable_http_app(server), host=args.host, port=args.port, workers=1)
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
