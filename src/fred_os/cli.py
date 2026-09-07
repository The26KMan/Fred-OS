"""Command-line client for the M1 FRED OS Command Gateway."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from fred_os.gateway import CommandGateway, GatewayRequest, IdempotencyStore, TokenAuthenticator
from fred_os.runtime import RuntimeKernel


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fred-os", description="Dispatch commands through the FRED OS M1 Command Gateway")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = args.token or os.environ.get("FRED_OS_TOKEN", "")
    if not token:
        print(json.dumps({"error": "gateway token required via FRED_OS_TOKEN or --token"}), file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    kernel = RuntimeKernel.boot(root_dir=root, profile=args.profile, session_id=args.session_id)
    store_path = Path(args.idempotency_store) if args.idempotency_store else root / "data" / "gateway_idempotency.sqlite3"
    gateway = CommandGateway(
        kernel,
        TokenAuthenticator.from_file(args.auth_registry),
        IdempotencyStore(store_path),
    )
    try:
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
        return 2
    except Exception as exc:
        print(json.dumps({"error": exc.__class__.__name__, "message": str(exc)}), file=sys.stderr)
        return 2
    finally:
        gateway.close()
        kernel.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
